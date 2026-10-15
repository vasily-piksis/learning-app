"""Opt-in real Docker deployment checks on disposable, labelled QA volumes."""

import json
import os
import shutil
import subprocess
import sys
import uuid

import pytest
from alembic.script import ScriptDirectory
from test_deploy_scripts import SOURCE, load_deploy

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_QA") != "1",
    reason="Set RUN_DOCKER_QA=1 with locally built QA images",
)
BEFORE = os.environ.get("DOCKER_QA_BEFORE", "learning-qa-before:20261014")
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
import hashlib
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
 Path('/data/question-images').mkdir(exist_ok=True)
 Image.new('RGB',(8,8),(20,100,40)).save('/data/question-images/picture.webp')
 raw=Path('/data/question-images/picture.webp').read_bytes()
 source={'kind':'image','asset_id':'b'*32,'sha256':hashlib.sha256(raw).hexdigest()}
 visual={'goal':'language','language':'pl','level':'A1','min_words':None,'max_words':None,'model_answer':'Zielone pole.',
 'rubric':[{'id':'task','label':'Opis','weight':100}], 'expected_points':[{'id':'green','text':'Zielone pole','essential':True,'sources':[source]}],'source':source}
 session.add(StudySession(id=3,user_id=1,topic_ids=[1],mode='quiz',position=0,status='active'));session.flush()
 session.add(SessionCard(id=3,session_id=3,position=0,snapshot={'id':3,'snapshot_version':4,'question':'Opisz obrazek.','question_type':'picture_description','mode':'quiz','language':'pl','exercise':visual,'answer':'Zielone pole.','sources':[]}));session.flush()
 session.add(ImageAsset(id='b'*32,filename='picture.webp',owner_user_id=1,stage='ready',width=8,height=8,sha256=source['sha256'],size=len(raw)));session.flush()
 session.add(SessionImage(session_card_id=3,asset_id='b'*32,slot='question',alt='',image_role='source'))
# Seed a completed voice evaluation plus a failed retained recording before the cold backup.
from datetime import datetime,timedelta,timezone
from app.models import Attempt,AudioAnswer,Evaluation,Job,TranscriptionRequest
import wave
with db.session() as session:
 session.get(StudySession,2).status='completed';session.get(StudySession,2).position=1
 job=Job(user_id=1,kind='evaluate_response',status='succeeded',payload={});session.add(job);session.flush()
 transcript='Ąžuolas yra medis.'
 grade={'version':2,'evaluation_id':1,'score':75,'correct':False,'word_count':4,'word_count_version':1,'word_limit':{'min':100,'max':150,'met':False},'language_match':True,'summary':'Aišku.','suggestions':[],'corrections':[],'rubric_scores':[{'criterion_id':'clarity','score':3,'explanation':'Aišku.'}],'point_checks':[{'point_id':'tree','met':True,'evidence':[]}],'input_method':'voice','voice':{'original_transcript':transcript,'original_word_count':3,'was_edited':True}}
 submission={'free_text':'Ąžuolas yra didelis medis.','audio_answer_id':'c'*32}
 session.add(Evaluation(id=1,session_card_id=2,user_id=1,job_id=job.id,request_key='qa-grade',fingerprint='d'*64,submission=submission,status='completed',applied_result=grade))
 session.add(Attempt(user_id=1,session_card_id=2,idempotency_key='qa-grade',value={**submission,'_grading':grade},correct=False))
 asr=Job(user_id=1,kind='transcribe_answer',status='succeeded',payload={});session.add(asr);session.flush()
 expiry=datetime.now(timezone.utc)+timedelta(hours=23)
 session.add(AudioAnswer(id='c'*32,session_card_id=2,user_id=1,job_id=asr.id,request_key='qa-ready-audio',sha256='e'*64,duration=1,expected_language='lt',detected_languages=['lt'],original_transcript=transcript,status='ready',was_edited=True,expires_at=expiry))
 session.add(TranscriptionRequest(id='d'*32,job_id=asr.id,user_id=1,request_key='qa-ready-audio',seconds=1,model='fixture-only',status='succeeded',reserved_at=datetime.now(timezone.utc)))
 session.add(StudySession(id=4,user_id=1,topic_ids=[1],mode='quiz',position=0,status='active'));session.flush()
 session.add(SessionCard(id=4,session_id=4,position=0,snapshot=snapshot));session.flush()
 failed=Job(user_id=1,kind='transcribe_answer',status='failed',payload={});session.add(failed);session.flush()
 directory=Path('/data/answer-audio');directory.mkdir(exist_ok=True);directory.chmod(0o700)
 path=directory/('f'*32+'.wav')
 with wave.open(str(path),'wb') as recording:
  recording.setparams((1,2,16000,0,'NONE','not compressed'));recording.writeframes(bytes(32000))
 path.chmod(0o600)
 session.add(AudioAnswer(id='f'*32,session_card_id=4,user_id=1,job_id=failed.id,request_key='qa-failed-audio',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),duration=1,raw_path=path.name,expected_language='lt',status='failed',error_code='failed',expires_at=expiry))
 (directory/('e'*32+'.part')).write_bytes(b'private-staged-upload')
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
    old_config = {
        "name": project,
        "services": {
            "app": {
                "image": BEFORE,
                "labels": {"traefik.enable": "false"},
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
    try:
        docker("volume", "create", "--label", f"learning.qa={token}", volume)
        # Docker copies the non-root image's /data ownership onto this fresh volume.
        command_image(BEFORE, volume, INIT)
        module.run(["docker", "compose", "up", "-d", "--no-build", "--wait"])
        yield module, root, volume, old_config, environment, override
    finally:
        unwinding = sys.exc_info()[0] is not None
        cleanup_errors = []
        for args in (
            ["docker", "compose", "down", "--remove-orphans"],
            ["docker", "volume", "rm", volume],
        ):
            try:
                result = subprocess.run(args, cwd=root, capture_output=True, check=False)
                result.check_returncode()
            except (OSError, subprocess.CalledProcessError) as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            if not unwinding:
                raise cleanup_errors[0]
            print(f"Owned QA cleanup needs attention: {project}: {cleanup_errors}", file=sys.stderr)


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
    assert len(current["tables"]["session_images"]["rows"]) == 2
    roles = current["tables"]["session_images"]
    assert {row[roles["columns"].index("image_role")] for row in roles["rows"]} == {
        "illustration",
        "source",
    }
    assert "question-images/picture.webp" in current["files"]
    assert "images/qa.png" in current["files"]
    assert len(current["tables"]["audio_answers"]["rows"]) == 2
    assert len(current["tables"]["evaluations"]["rows"]) == 1
    assert len(current["tables"]["transcription_requests"]["rows"]) == 1
    assert "answer-audio/" + "f" * 32 + ".wav" in current["files"]
    assert "answer-audio/" + "e" * 32 + ".part" in current["files"]
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
    (bad_context / "failure.py").chmod(0o644)
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


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_actual_compose_flags_reach_runtime_settings(tmp_path, enabled):
    environment = tmp_path / "sentinels.env"
    environment.write_text(
        f"FREE_RESPONSE_ENABLED={enabled}\nPICTURE_DESCRIPTION_ENABLED={enabled}\nOPENAI_VISION_ENABLED={enabled}\nIMAGE_GENERATION_ENABLED=false\nOPENAI_IMAGE_MODEL=\nOPENAI_API_KEY=\nFREE_RESPONSE_DAILY_REQUEST_LIMIT=37\nIMAGE_DAILY_REQUEST_LIMIT=13\nBUDGET_TIMEZONE=UTC\nIMAGE_BUDGET_TIMEZONE=Europe/Warsaw\nTRANSCRIPTION_ENABLED={enabled}\nOPENAI_TRANSCRIPTION_MODEL=operator-audio-test\nTRANSCRIPTION_DAILY_SECONDS_LIMIT=73\n"
    )
    configuration = json.loads(
        docker(
            "compose",
            "--env-file",
            str(environment),
            "-f",
            str(SOURCE / "compose.yaml"),
            "config",
            "--format",
            "json",
        )
    )
    config = configuration["services"]["app"]["environment"]
    names = [
        "TRANSCRIPTION_ENABLED",
        "OPENAI_TRANSCRIPTION_MODEL",
        "TRANSCRIPTION_DAILY_SECONDS_LIMIT",
        "FREE_RESPONSE_ENABLED",
        "PICTURE_DESCRIPTION_ENABLED",
        "OPENAI_VISION_ENABLED",
        "IMAGE_GENERATION_ENABLED",
        "OPENAI_IMAGE_MODEL",
        "FREE_RESPONSE_DAILY_REQUEST_LIMIT",
        "IMAGE_DAILY_REQUEST_LIMIT",
        "BUDGET_TIMEZONE",
        "IMAGE_BUDGET_TIMEZONE",
    ]
    args = [part for name in names for part in ("-e", f"{name}={config[name]}")]
    actual = json.loads(
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--label",
            "traefik.enable=false",
            *args,
            "--entrypoint",
            "python",
            AFTER,
            "-c",
            "import json; from app.config import Settings; s=Settings(_env_file=None); print(json.dumps({k:getattr(s,k.lower()) for k in "
            + repr(names)
            + "}))",
        )
    )
    assert actual["TRANSCRIPTION_ENABLED"] == (enabled == "true")
    assert actual["OPENAI_TRANSCRIPTION_MODEL"] == "operator-audio-test"
    assert actual["TRANSCRIPTION_DAILY_SECONDS_LIMIT"] == 73
    assert actual["PICTURE_DESCRIPTION_ENABLED"] == (enabled == "true")
    assert actual["FREE_RESPONSE_ENABLED"] == (enabled == "true")
    assert actual["OPENAI_VISION_ENABLED"] == (enabled == "true")
    assert actual["IMAGE_GENERATION_ENABLED"] is False and actual["OPENAI_IMAGE_MODEL"] == ""
    assert actual["FREE_RESPONSE_DAILY_REQUEST_LIMIT"] == 37
    assert actual["IMAGE_DAILY_REQUEST_LIMIT"] == 13
    assert actual["BUDGET_TIMEZONE"] == "UTC" and actual["IMAGE_BUDGET_TIMEZONE"] == "Europe/Warsaw"


def test_runtime_audio_codecs_nonroot(tmp_path):
    script = """
import os,subprocess,uuid
from pathlib import Path
from app.answer_audio import validate_audio
assert os.getuid()==10001
for extension,codec in [('wav','pcm_s16le'),('mp4','aac'),('webm','libopus'),('ogg','libopus')]:
 path=Path('/tmp')/(uuid.uuid4().hex+'.'+extension)
 subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=duration=0.2','-c:a',codec,str(path)],check=True)
 result=validate_audio(path)
 assert 0.19<=result.duration<=0.3
 result.normalized_path.unlink();path.unlink()
print('non-root runtime codecs: WAV MP4 WebM Ogg passed')
"""
    fixture = json.loads((SOURCE / "tests/fixtures/word-count-v1.json").read_text())
    script += "\nfrom app.free_responses import count_words\nimport sys\n"
    script += "assert sys.version_info[:2] == (3, 13)\n"
    script += "fixture=" + repr(fixture) + "\n"
    script += "assert all(count_words(row['text']) == row['count'] for row in fixture['cases'])\n"
    script += "print('Python',sys.version.split()[0], 'Unicode',fixture['unicode_category_version'],len(fixture['cases']),'shared fixtures passed')\n"
    output = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--label",
        "traefik.enable=false",
        "--entrypoint",
        "python",
        AFTER,
        "-c",
        script,
    )
    assert "WAV MP4 WebM Ogg passed" in output
    assert "Unicode 15.1.0 23 shared fixtures passed" in output
    print(output)
