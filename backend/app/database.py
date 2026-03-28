"""
SQLAlchemy + SQLite 数据库模块
"""
import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DB_PATH, DATA_DIR
from pathlib import Path

logger = logging.getLogger(__name__)

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and run migrations."""
    from app import models  # noqa: F401 — ensure models are loaded
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """Apply incremental schema migrations for existing databases."""
    with engine.connect() as conn:
        # PushLog: add admission_no column
        try:
            conn.execute(text("ALTER TABLE push_log ADD COLUMN admission_no VARCHAR(50) DEFAULT ''"))
            conn.commit()
            logger.info("迁移: push_log 增加 admission_no 列")
        except Exception:
            pass  # 列已存在，忽略

        # PushLog: add visit_number column
        try:
            conn.execute(text("ALTER TABLE push_log ADD COLUMN visit_number VARCHAR(20) DEFAULT ''"))
            conn.commit()
            logger.info("迁移: push_log 增加 visit_number 列")
        except Exception:
            pass  # 列已存在，忽略
