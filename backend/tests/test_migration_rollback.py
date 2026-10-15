"""Opt-in real Docker deployment checks on disposable, labelled QA volumes."""

import json
import os
import shutil
import subprocess
import uuid

import pytest
from alembic.script import ScriptDirectory
from test_deploy_scripts import SOURCE, load_deploy

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_QA") != "1",
    reason="Set RUN_DOCKER_QA=1 with locally built QA images",
)
BEFORE = "learning-qa-before:20261014"
AFTER = os.environ.get("DOCKER_QA_AFTER", "learning-qa-after:free-response-task4")
HEAD = ScriptDirectory(str(SOURCE / "backend/alembic")).get_current_head()


def docker(*args, input=None):
    return subprocess.run(
        ["docker", *args], input=input, check=True, text=True, capture_output=True
    ).stdout.strip()


INIT = """
from pathlib import Path
from app.db import Database
from app.config import Settings
from app.models import User,Subject,Topic,Document,SourcePage,Card,CardSource,StudySession,SessionCard,Attempt
settings=Settings(_env_file=None,data_dir=Path('/data'))
db=Database(settings)
with db.session() as s:
 s.add(User(id=1,username='qa',display_name='QA',password_hash='test-only-hash'))
 s.add(Subject(id=1,name='History'));s.flush()
 s.add(Topic(id=1,subject_id=1,name='Old topic'));s.flush()
 s.add(Document(id=1,topic_id=1,name='Lesson.pdf',filename='lesson.pdf',mime='application/pdf',size=16,sha256='a'*64,page_count=1,status='ready'));s.flush()
 s.add(SourcePage(id=1,document_id=1,number=1,text='Old source',language='pl'));s.flush()
 s.add(Card(id=1,topic_id=1,question='Old question',answer='Nil',mode='quiz',options=['Nil','Don'],correct_index=0,correct_indices=[0],status='saved'));s.flush()
 s.add(CardSource(card_id=1,page_id=1))
 s.add(StudySession(id=1,user_id=1,topic_ids=[1],mode='quiz',position=1,status='completed'));s.flush()
 s.add(SessionCard(id=1,session_id=1,position=0,snapshot={'id':1,'question':'Frozen old question','answer':'Nil','mode':'quiz','options':['Nil','Don'],'correct_index':0,'sources':[]},revealed=True));s.flush()
 s.add(Attempt(id=1,user_id=1,session_card_id=1,idempotency_key='old-answer',value={'choice':0},correct=True))
Path('/data/files/lesson.pdf').write_bytes(b'private-old-pdf')
Path('/data/youtube-cache').mkdir()
Path('/data/youtube-cache/retained.json').write_text('{"segments":[{"text":"Old captions","start":1}]}')
db.engine.dispose()
"""

CURRENT_CONTENT = """
from pathlib import Path
from PIL import Image
from app.config import Settings
from app.db import Database
from app.models import ImageAsset,SessionImage,StudySession,SessionCard
from app.quiz import build_free_snapshot
settings=Settings(_env_file=None,data_dir=Path('/data'))
db=Database(settings)
ref={'document_id':1,'page':1}
exercise={'goal':'language','language':'lt','level':'B2','min_words':100,'max_words':150,
 'model_answer':'Ąžuolas yra medis.','rubric':[{'id':'clarity','label':'Aiškumas','weight':100}],
 'expected_points':[{'id':'tree','text':'Medis','essential':True,'sources':[ref]}],
 'source_fragments':[{'source':ref,'text':'Ąžuolas yra medis.'}]}
snapshot=build_free_snapshot({'id':2,'question':'Aprašyk ąžuolą','question_type':'free_response',
 'mode':'quiz','language':'lt','exercise':exercise,'sources':[ref]},exercise['source_fragments'])
Path('/data/images').mkdir(exist_ok=True)
Image.new('RGB',(8,8),(20,100,40)).save('/data/images/qa.png')
with db.session() as session:
 session.add(StudySession(id=2,user_id=1,topic_ids=[1],mode='quiz',position=0,status='active'));session.flush()
 session.add(SessionCard(id=2,session_id=2,position=0,snapshot=snapshot));session.flush()
 session.add(ImageAsset(id='a'*32,filename='qa.png',owner_user_id=1,stage='ready',width=8,height=8,mime='image/png'));session.flush()
 session.add(SessionImage(session_card_id=2,asset_id='a'*32,slot='answer',alt='Ąžuolas'))
db.engine.dispose()
"""


READ = """
import hashlib,json,sqlite3
from pathlib import Path
connection=sqlite3.connect('file:/data/learning.sqlite3?mode=ro',uri=True)
names=[row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
tables={}
for name in names:
 quoted='"'+name.replace('"','""')+'"'
 cols=[row[1] for row in connection.execute('PRAGMA table_info('+quoted+')')]
 tables[name]={'columns':cols,'rows':list(connection.execute('SELECT * FROM '+quoted+' ORDER BY rowid'))}
files={str(p.relative_to('/data')):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/data').rglob('*') if p.is_file() and not p.name.startswith('learning.sqlite3')}
print(json.dumps({'tables':tables,'files':files,'integrity':connection.execute('PRAGMA integrity_check').fetchone()[0],'foreign_keys':list(connection.execute('PRAGMA foreign_key_check'))}))
"""


def command_image(image, volume, script):
    return docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--label",
        "traefik.enable=false",
        "--mount",
        f"type=volume,src={volume},dst=/data",
        "--entrypoint",
        "python",
        image,
        "-c",
        script,
    )


@pytest.fixture
def qa(tmp_path, monkeypatch):
    token = uuid.uuid4().hex[:12]
    project = f"learning-qa-{token}"
    volume = f"{project}-data"
    root = tmp_path / "server"
    root.mkdir()
    shutil.copytree(SOURCE / "scripts", root / "scripts")
    environment = b"PRIVATE_CONFIG=keep-qa-only\nOPENAI_API_KEY=\n"
    (root / ".env").write_bytes(environment)
    (root / ".env").chmod(0o600)
    override = b"services: {}\n"
    (root / "compose.override.yaml").write_bytes(override)
    docker("volume", "create", "--label", f"learning.qa={token}", volume)
    # Docker copies /data ownership from the non-root app image onto this fresh volume.
    command_image(BEFORE, volume, INIT)
    old_config = {
        "name": project,
        "services": {
            "app": {
                "image": BEFORE,
                "environment": {
                    "DATA_DIR": "/data",
                    "OPENAI_API_KEY": "",
                    "COOKIE_SECURE": "false",
                },
                "volumes": ["learning-data:/data"],
                "healthcheck": {
                    "interval": "1s",
                    "start_period": "1s",
                    "retries": 10,
                    "timeout": "5s",
                },
            }
        },
        "volumes": {"learning-data": {"name": volume, "external": True}},
    }
    (root / "compose.yaml").write_text(json.dumps(old_config))
    module = load_deploy()
    module.ROOT = root
    module.run(["docker", "compose", "up", "-d", "--no-build", "--wait"])
    try:
        yield module, root, volume, old_config, environment, override
    finally:
        subprocess.run(
            ["docker", "compose", "down", "--remove-orphans"],
            cwd=root,
            capture_output=True,
            check=True,
        )
        docker("volume", "rm", volume)


def assert_old_data(old, new):
    assert old["files"] == new["files"]
    assert new["integrity"] == "ok" and new["foreign_keys"] == []
    for name, table in old["tables"].items():
        if name == "alembic_version":
            continue
        columns = new["tables"][name]["columns"]
        projection = [
            [row[columns.index(col)] for col in table["columns"]]
            for row in new["tables"][name]["rows"]
        ]
        assert projection == table["rows"], name


def test_real_docker_migration_preserves_old_rows_json_private_files_and_env(qa):
    module, root, volume, config, environment, override = qa
    before = json.loads(command_image(BEFORE, volume, READ))
    config["services"]["app"].update(image=AFTER, build={"context": str(SOURCE)})
    (root / "compose.yaml").write_text(json.dumps(config))
    module.start()
    after = json.loads(command_image(AFTER, volume, READ))
    assert_old_data(before, after)
    assert after["tables"]["alembic_version"]["rows"] == [[HEAD]]
    columns = after["tables"]["cards"]["columns"]
    assert after["tables"]["cards"]["rows"][0][columns.index("question_type")] == "choice"
    assert (root / ".env").read_bytes() == environment
    assert (root / "compose.override.yaml").read_bytes() == override
    assert (root / ".env").stat().st_mode & 0o777 == 0o600
    assert len(list((root / "backups").glob("learning-*.tar.gz"))) == 1
    # New v3 snapshots and private image references/files also survive a real cold restore.
    module.run(["docker", "compose", "stop", "app"])
    command_image(AFTER, volume, CURRENT_CONTENT)
    current = json.loads(command_image(AFTER, volume, READ))
    assert len(current["tables"]["session_images"]["rows"]) == 1
    assert "images/qa.png" in current["files"]
    archive = module.cold_backup(module.private_backups(), os.environ.copy())
    command_image(
        AFTER,
        volume,
        "from pathlib import Path; Path('/data/images/qa.png').write_bytes(b'changed')",
    )
    module.restore_backup(archive, volume, AFTER)
    restored = json.loads(command_image(AFTER, volume, READ))
    assert restored == current
    module.run(["docker", "compose", "up", "-d", "--no-build", "--wait"])


@pytest.mark.parametrize("keep_previous_container", [True, False])
def test_real_docker_failed_partial_migration_restores_old_image_and_complete_backup(
    qa, tmp_path, keep_previous_container
):
    module, root, volume, config, environment, override = qa
    before = json.loads(command_image(BEFORE, volume, READ))
    if not keep_previous_container:
        module.run(["docker", "compose", "down", "--remove-orphans"])
    bad_context = tmp_path / "bad-image"
    bad_context.mkdir()
    (bad_context / "Dockerfile").write_text(
        f"FROM {AFTER}\nCOPY failure.py /app/alembic/versions/qa_failure.py\n"
    )
    (bad_context / "failure.py").write_text(f"""
from pathlib import Path
import sqlalchemy as sa
from alembic import op
revision='qa_failure'
down_revision='{HEAD}'
branch_labels=None
depends_on=None
def upgrade():
 op.add_column('cards',sa.Column('qa_partial',sa.String(),nullable=True))
 if op.get_bind().scalar(sa.text('SELECT count(*) FROM users')):
  Path('/data/failed-only.txt').write_text('failure marker')
  raise RuntimeError('Intentional isolated QA migration failure')
def downgrade():raise RuntimeError('Restore backup')
""")
    bad_image = f"learning-qa-bad:{uuid.uuid4().hex[:12]}"
    config["services"]["app"].update(image=bad_image, build={"context": str(bad_context)})
    (root / "compose.yaml").write_text(json.dumps(config))
    try:
        with pytest.raises(subprocess.CalledProcessError):
            module.start()
        after = json.loads(command_image(BEFORE, volume, READ))
        assert_old_data(before, after)
        assert before["tables"] == after["tables"]
        assert (root / ".env").read_bytes() == environment
        assert (root / "compose.override.yaml").read_bytes() == override
        if keep_previous_container:
            identifier = module.capture(["docker", "compose", "ps", "-q", "app"])
            assert module.capture(
                ["docker", "inspect", identifier, "--format", "{{.Image}}"]
            ) == docker("image", "inspect", BEFORE, "--format", "{{.Id}}")
        else:
            assert module.capture(["docker", "compose", "ps", "-q", "app"]) == ""
        assert len(list((root / "backups").glob("learning-*.tar.gz"))) == 2
        assert (root / "backups/failed-update.json").stat().st_mode & 0o777 == 0o600
    finally:
        docker("image", "rm", bad_image)
