"""Versioned, additive migrations. Preserve records and original classification."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, text


def migrate_v1_to_v2(engine):
    if engine.dialect.name == "sqlite" and engine.url.database and engine.url.database != ":memory:":
        source = Path(engine.url.database)
        if source.is_file():
            backups = source.parent / "backups"
            backups.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            with sqlite3.connect(source) as original, sqlite3.connect(backups / f"before-v2-{stamp}-{uuid4().hex[:8]}.sqlite3") as backup:
                original.backup(backup)
    with engine.begin() as connection:
        # SQLite may retain successful DDL after an interrupted upgrade.
        # Static names and definitions make retrying this additive migration safe.
        for table, column, definition in [
            ("accounts", "institution", "VARCHAR(64)"),
            ("accounts", "is_hidden", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("transactions", "review_acknowledged", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ]:
            columns = {c["name"] for c in inspect(connection).get_columns(table)}
            if column not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        connection.execute(text("UPDATE accounts SET institution=bank WHERE bank <> 'snowball'"))
        # The initial release supported one bank. Infer legacy portfolio affiliation
        # only when the owner's bank records identify exactly one institution.
        connection.execute(text("""UPDATE accounts SET institution=(
            SELECT CASE WHEN COUNT(DISTINCT b.bank)=1 THEN MIN(b.bank) ELSE NULL END
            FROM accounts b WHERE b.user_id=accounts.user_id AND b.bank <> 'snowball'
        ) WHERE bank='snowball'"""))
        connection.execute(text("UPDATE schema_version SET version=2 WHERE version=1"))


def migrate_v2_to_v3(engine):
    from .database import UserCategory
    if engine.dialect.name == "sqlite" and engine.url.database and engine.url.database != ":memory:":
        source = Path(engine.url.database)
        backups = source.parent / "backups"
        backups.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        with sqlite3.connect(source) as original, sqlite3.connect(backups / f"before-v3-{stamp}-{uuid4().hex[:8]}.sqlite3") as backup:
            original.backup(backup)
    with engine.begin() as connection:
        UserCategory.__table__.create(connection, checkfirst=True)
        connection.execute(text("UPDATE schema_version SET version=3 WHERE version=2"))
