"""Database engine, session and schema management (SQLAlchemy 2.0)."""

import logging
from datetime import datetime, timezone

from sqlalchemy import (
    BLOB,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), unique=True, nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("display_name", String(128), nullable=False),
    Column("school", String(255), nullable=False, server_default=""),
    Column("role", String(16), nullable=False, server_default="teacher"),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)

students = Table(
    "students",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("uq_students_user_name", "user_id", "name", unique=True),
)

face_encodings = Table(
    "face_encodings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("student_name", String(128), nullable=False),
    Column("encoding", BLOB, nullable=False),
    Column("photo_path", String(512), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("idx_encodings_user", "user_id"),
)

attendance_records = Table(
    "attendance_records",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("student_name", String(128), nullable=False),
    Column("date", String(10), nullable=False),  # YYYY-MM-DD
    Column("time", String(8), nullable=False),   # HH:MM:SS
    Column("source", String(32), nullable=False, server_default="camera"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("uq_attendance_user_name_date", "user_id", "student_name", "date", unique=True),
    Index("idx_attendance_user_date", "user_id", "date"),
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Enable sensible SQLite settings (WAL, busy timeout, FK enforcement)."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


class Database:
    """Thin wrapper around a SQLAlchemy engine + scoped session factory."""

    def __init__(self, url: str):
        self.url = url
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        self.engine = create_engine(url, **kwargs)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_schema(self):
        metadata.create_all(self.engine)
        logger.info("Database schema ready (engine=%s)", self.engine.name)

    def close(self):
        self.engine.dispose()

    @property
    def session(self):
        """A request-scoped session (or a fresh one outside an app context)."""
        from flask import g, has_app_context

        if has_app_context():
            sess = getattr(g, "_db_session", None)
            if sess is None:
                sess = self.session_factory()
                g._db_session = sess
            return sess
        return self.session_factory()

    def close_session(self):
        from flask import g, has_app_context

        if has_app_context():
            sess = g.pop("_db_session", None)
            if sess is not None:
                sess.close()


def utcnow():
    return datetime.now(timezone.utc)


def now_naive():
    """Local-naive timestamp string for attendance Date/Time columns."""
    return datetime.now()
