from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, event, false, inspect, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(primary_key=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[int] = mapped_column(BigInteger)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    ip: Mapped[str] = mapped_column(String(80), index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    at: Mapped[int] = mapped_column(BigInteger, index=True)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "bank", "external_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    bank: Mapped[str] = mapped_column(String(32))
    external_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    last4: Mapped[str | None] = mapped_column(String(4))
    source_url: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(String(300))
    last_attempt: Mapped[int | None] = mapped_column(BigInteger)
    institution: Mapped[str | None] = mapped_column(String(64))
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("account_id", "as_of", "source"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    as_of: Mapped[str] = mapped_column(String(32), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("user_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(200))
    adapter: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[str] = mapped_column(String(32))
    expires: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("account_id", "fingerprint", "occurrence"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    occurrence: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[str] = mapped_column(String(32), index=True)
    posted_at: Mapped[str] = mapped_column(String(32))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    original_amount_minor: Mapped[int] = mapped_column(BigInteger)
    original_currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(Text)
    card_last4: Mapped[str | None] = mapped_column(String(4))
    source_page: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    review_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class UserCategory(Base):
    __tablename__ = "user_categories"
    __table_args__ = (UniqueConstraint("user_id", "normalized_name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(240))


class CategoryRule(Base):
    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("user_id", "description", "direction"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    direction: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))


def make_database(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        (ROOT / ".local").mkdir(exist_ok=True)
        url = f"sqlite:///{(ROOT / '.local' / 'finance.sqlite3').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize(engine):
    from .migrations import migrate_v1_to_v2, migrate_v2_to_v3
    if inspect(engine).has_table("schema_version"):
        with engine.connect() as connection:
            versions = list(connection.execute(select(SchemaVersion.version)).scalars())
        if versions == [3]:
            return
        if versions == [2]:
            migrate_v2_to_v3(engine)
            return
        if versions == [1]:
            migrate_v1_to_v2(engine)
            migrate_v2_to_v3(engine)
            return
        if versions:
            raise RuntimeError("Unsupported database schema version; apply an explicit migration")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        current = db.get(SchemaVersion, 3)
        if not current:
            db.add(SchemaVersion(version=3))
            db.commit()
