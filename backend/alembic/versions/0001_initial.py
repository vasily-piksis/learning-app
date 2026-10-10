"""Initial immutable SQLite schema, frozen at version 0001."""

from alembic import op
from sqlalchemy import text

revision = "0001"
down_revision = None

DDL = [
    "CREATE TABLE subjects (\n\tid INTEGER NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tcreated DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)",
    "CREATE TABLE users (\n\tid INTEGER NOT NULL, \n\tusername VARCHAR(80) NOT NULL, \n\tdisplay_name VARCHAR(120) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (username)\n)",
    "CREATE TABLE auth_sessions (\n\tid VARCHAR(64) NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tcsrf VARCHAR(64) NOT NULL, \n\texpires DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)",
    "CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)",
    "CREATE TABLE jobs (\n\tid INTEGER NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tpayload JSON NOT NULL, \n\tresult JSON, \n\terror TEXT, \n\tcreated DATETIME NOT NULL, \n\tupdated DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)",
    "CREATE INDEX ix_jobs_status ON jobs (status)",
    "CREATE INDEX ix_jobs_user_id ON jobs (user_id)",
    "CREATE TABLE study_sessions (\n\tid INTEGER NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\ttopic_ids JSON NOT NULL, \n\tmode VARCHAR(20) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated DATETIME NOT NULL, \n\tupdated DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)",
    "CREATE INDEX ix_study_sessions_user_id ON study_sessions (user_id)",
    "CREATE TABLE topics (\n\tid INTEGER NOT NULL, \n\tsubject_id INTEGER NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcreated DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(subject_id) REFERENCES subjects (id)\n)",
    "CREATE INDEX ix_topics_subject_id ON topics (subject_id)",
    "CREATE TABLE cards (\n\tid INTEGER NOT NULL, \n\ttopic_id INTEGER NOT NULL, \n\tjob_id INTEGER, \n\tquestion TEXT NOT NULL, \n\tanswer TEXT NOT NULL, \n\tmode VARCHAR(20) NOT NULL, \n\toptions JSON NOT NULL, \n\tcorrect_index INTEGER, \n\tversion INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(topic_id) REFERENCES topics (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id)\n)",
    "CREATE INDEX ix_cards_topic_id ON cards (topic_id)",
    "CREATE TABLE documents (\n\tid INTEGER NOT NULL, \n\ttopic_id INTEGER NOT NULL, \n\tname VARCHAR(240) NOT NULL, \n\tfilename VARCHAR(80) NOT NULL, \n\tmime VARCHAR(40) NOT NULL, \n\tsize INTEGER NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tpage_count INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (topic_id, sha256), \n\tFOREIGN KEY(topic_id) REFERENCES topics (id), \n\tUNIQUE (filename)\n)",
    "CREATE INDEX ix_documents_topic_id ON documents (topic_id)",
    "CREATE TABLE session_cards (\n\tid INTEGER NOT NULL, \n\tsession_id INTEGER NOT NULL, \n\tposition INTEGER NOT NULL, \n\tsnapshot JSON NOT NULL, \n\trevealed BOOLEAN NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (session_id, position), \n\tFOREIGN KEY(session_id) REFERENCES study_sessions (id)\n)",
    "CREATE INDEX ix_session_cards_session_id ON session_cards (session_id)",
    "CREATE TABLE attempts (\n\tid INTEGER NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tsession_card_id INTEGER NOT NULL, \n\tidempotency_key VARCHAR(80) NOT NULL, \n\tvalue JSON NOT NULL, \n\tcorrect BOOLEAN NOT NULL, \n\tcreated DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, idempotency_key), \n\tUNIQUE (session_card_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(session_card_id) REFERENCES session_cards (id)\n)",
    "CREATE TABLE explanations (\n\tid INTEGER NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tsession_card_id INTEGER NOT NULL, \n\tparent_id INTEGER, \n\tquestion TEXT NOT NULL, \n\tresult JSON NOT NULL, \n\tcreated DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(session_card_id) REFERENCES session_cards (id), \n\tFOREIGN KEY(parent_id) REFERENCES explanations (id)\n)",
    "CREATE INDEX ix_explanations_session_card_id ON explanations (session_card_id)",
    "CREATE TABLE source_pages (\n\tid INTEGER NOT NULL, \n\tdocument_id INTEGER NOT NULL, \n\tnumber INTEGER NOT NULL, \n\ttext TEXT NOT NULL, \n\twarnings JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (document_id, number), \n\tFOREIGN KEY(document_id) REFERENCES documents (id)\n)",
    "CREATE INDEX ix_source_pages_document_id ON source_pages (document_id)",
    "CREATE TABLE card_sources (\n\tid INTEGER NOT NULL, \n\tcard_id INTEGER NOT NULL, \n\tpage_id INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(card_id) REFERENCES cards (id), \n\tFOREIGN KEY(page_id) REFERENCES source_pages (id)\n)",
    "CREATE INDEX ix_card_sources_card_id ON card_sources (card_id)",
]


def upgrade():
    for statement in DDL:
        op.execute(text(statement))


def downgrade():
    raise RuntimeError("Destructive downgrades are disabled; restore a backup instead")
