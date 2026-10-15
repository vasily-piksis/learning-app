from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[datetime] = mapped_column(DateTime)


class Subject(Base):
    __tablename__ = "subjects"
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created: Mapped[datetime] = mapped_column(default=now)


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(default=now)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("topic_id", "sha256"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    filename: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[datetime] = mapped_column(default=now)


class SourcePage(Base):
    __tablename__ = "source_pages"
    __table_args__ = (UniqueConstraint("document_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created: Mapped[datetime] = mapped_column(default=now)
    updated: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    question_type: Mapped[str] = mapped_column(
        String(40), default="choice", server_default="choice"
    )
    exercise: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mode: Mapped[str] = mapped_column(String(20))
    options: Mapped[list] = mapped_column(JSON, default=list)
    correct_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct_indices: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")


class CardSource(Base):
    __tablename__ = "card_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("source_pages.id"))


class StudySession(Base):
    __tablename__ = "study_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic_ids: Mapped[list] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created: Mapped[datetime] = mapped_column(default=now)
    updated: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class SessionCard(Base):
    __tablename__ = "session_cards"
    __table_args__ = (UniqueConstraint("session_id", "position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    revealed: Mapped[bool] = mapped_column(default=False)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("session_card_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    session_card_id: Mapped[int] = mapped_column(ForeignKey("session_cards.id"))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict] = mapped_column(JSON)
    correct: Mapped[bool] = mapped_column(Boolean)
    created: Mapped[datetime] = mapped_column(default=now)


class Explanation(Base):
    __tablename__ = "explanations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    session_card_id: Mapped[int] = mapped_column(ForeignKey("session_cards.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("explanations.id"), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON)
    created: Mapped[datetime] = mapped_column(default=now)


class ImageAsset(Base):
    __tablename__ = "image_assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(80), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String(40), default="image/webp")
    origin: Mapped[str] = mapped_column(String(20), default="upload")
    stage: Mapped[str] = mapped_column(String(20), default="writing", index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id"), nullable=True, index=True
    )
    target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[datetime] = mapped_column(default=now)
    updated: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class CardImage(Base):
    __tablename__ = "card_images"
    __table_args__ = (UniqueConstraint("card_id", "slot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("image_assets.id"), index=True)
    slot: Mapped[str] = mapped_column(String(20))
    alt: Mapped[str] = mapped_column(String(500), default="")
    image_role: Mapped[str] = mapped_column(
        String(20), default="illustration", server_default="illustration"
    )


class SessionImage(Base):
    __tablename__ = "session_images"
    __table_args__ = (UniqueConstraint("session_card_id", "slot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_card_id: Mapped[int] = mapped_column(
        ForeignKey("session_cards.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("image_assets.id"), index=True)
    slot: Mapped[str] = mapped_column(String(20))
    alt: Mapped[str] = mapped_column(String(500), default="")
    image_role: Mapped[str] = mapped_column(
        String(20), default="illustration", server_default="illustration"
    )


class JobImage(Base):
    __tablename__ = "job_images"
    __table_args__ = (UniqueConstraint("job_id", "asset_id", "role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("image_assets.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="candidate")


class ImageRequest(Base):
    __tablename__ = "image_requests"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no"),
        UniqueConstraint("user_id", "request_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(80))
    fingerprint: Mapped[str] = mapped_column(String(64))
    reserved_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    model: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSON)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint("session_card_id"),
        UniqueConstraint("user_id", "request_key"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_card_id: Mapped[int] = mapped_column(ForeignKey("session_cards.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    request_key: Mapped[str] = mapped_column(String(80))
    fingerprint: Mapped[str] = mapped_column(String(64))
    request_keys: Mapped[list] = mapped_column(JSON, default=list)
    submission: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    staged_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    applied_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created: Mapped[datetime] = mapped_column(default=now)
    updated: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class EvaluationRequest(Base):
    __tablename__ = "evaluation_requests"
    __table_args__ = (UniqueConstraint("job_id", "attempt_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(80))
    reserved_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    model: Mapped[str] = mapped_column(String(200))
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)


class PictureDraftRequest(Base):
    __tablename__ = "picture_draft_requests"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(80))
    fingerprint: Mapped[str] = mapped_column(String(64))
    card_id: Mapped[int] = mapped_column(Integer)
