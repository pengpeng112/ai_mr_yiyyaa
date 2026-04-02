"""
SQLAlchemy + SQLite 数据库模块
优化连接池配置，提高性能和稳定性
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool, QueuePool

from app.config import DB_PATH, DATA_DIR
from pathlib import Path

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# 优化的数据库引擎配置
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
    # 连接池配置
    poolclass=StaticPool,  # SQLite使用静态连接池
    pool_pre_ping=True,     # 连接健康检查
    # 性能优化
    echo_pool=False,
    # 注意：移除 isolation_level="AUTOCOMMIT"，
    # 因为 SessionLocal(autocommit=False) 依赖事务语义，
    # AUTOCOMMIT 与显式 session.commit()/rollback() 冲突
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency — yields a database session.
    使用上下文管理器确保连接正确关闭
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    创建所有表和索引
    包含性能优化和索引创建
    """
    from app import models  # noqa: F401 — ensure models are loaded

    # 创建表和索引
    Base.metadata.create_all(bind=engine)

    # PushLog 表迁移：为旧数据库添加新字段
    _migrate_push_log_columns()

    # SQLite 性能优化设置
    from sqlalchemy import text

    with engine.connect() as conn:
        # 启用 WAL 模式（Write-Ahead Logging）提高并发性能
        conn.execute(text("PRAGMA journal_mode=WAL;"))

        # 设置同步模式为 NORMAL，平衡性能和安全性
        conn.execute(text("PRAGMA synchronous=NORMAL;"))

        # 增加缓存大小（默认2MB，增加到10MB）
        conn.execute(text("PRAGMA cache_size=-10240;"))

        # 设置临时存储在内存中
        conn.execute(text("PRAGMA temp_store=MEMORY;"))

        # 优化查询计划器
        conn.execute(text("PRAGMA optimize;"))

    _ensure_debug_admin()


def _migrate_push_log_columns():
    """为旧数据库的 push_log 表添加新字段（兼容迁移）"""
    import logging
    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    new_columns = [
        ("admission_no", "VARCHAR(50) DEFAULT ''"),
        ("visit_number", "VARCHAR(20) DEFAULT ''"),
        ("request_json", "TEXT DEFAULT ''"),
        ("response_json", "TEXT DEFAULT ''"),
        ("parse_status", "VARCHAR(20) DEFAULT ''"),
        ("parse_error", "TEXT DEFAULT ''"),
        ("risk_score", "INTEGER DEFAULT 0"),
        ("ai_version", "VARCHAR(20) DEFAULT '1.0'"),
    ]

    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE push_log ADD COLUMN {col_name} {col_type}"))
                logger.info(f"push_log 表已添加字段: {col_name}")
            except Exception:
                pass  # 字段已存在，跳过

    _migrate_audit_dimension_result_columns()
    _migrate_audit_conclusion_columns()
    _migrate_qc_feedback_columns()


def _migrate_audit_dimension_result_columns():
    """为旧数据库的 audit_dimension_result 表添加新字段。"""
    import logging
    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    new_columns = [
        ("dimension_code", "VARCHAR(64) DEFAULT ''"),
        ("severity", "VARCHAR(20) DEFAULT ''"),
        ("confidence", "REAL DEFAULT 0"),
        ("issue_summary", "TEXT DEFAULT ''"),
        ("recommendation", "TEXT DEFAULT ''"),
        ("medical_evidence_json", "TEXT DEFAULT '[]'"),
        ("nursing_evidence_json", "TEXT DEFAULT '[]'"),
    ]

    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE audit_dimension_result ADD COLUMN {col_name} {col_type}"))
                logger.info(f"audit_dimension_result 表已添加字段: {col_name}")
            except Exception:
                pass


def _migrate_audit_conclusion_columns():
    """为旧数据库的 audit_conclusion 表添加新字段。"""
    import logging
    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    new_columns = [
        ("has_inconsistency", "INTEGER DEFAULT 0"),
        ("severity", "VARCHAR(20) DEFAULT ''"),
        ("risk_score", "INTEGER DEFAULT 0"),
        ("reasoning_brief", "TEXT DEFAULT ''"),
        ("ai_version", "VARCHAR(20) DEFAULT '1.0'"),
    ]

    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE audit_conclusion ADD COLUMN {col_name} {col_type}"))
                logger.info(f"audit_conclusion 表已添加字段: {col_name}")
            except Exception:
                pass


def _migrate_qc_feedback_columns():
    """为旧数据库的 qc_feedback 表添加新字段。"""
    import logging
    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    new_columns = [
        ("is_viewed", "BOOLEAN DEFAULT 0"),
        ("viewed_at", "DATETIME"),
        ("view_count", "INTEGER DEFAULT 0"),
        ("rectification_clicked", "BOOLEAN DEFAULT 0"),
        ("rectification_clicked_at", "DATETIME"),
        ("suppress_ai_push", "BOOLEAN DEFAULT 0"),
    ]

    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE qc_feedback ADD COLUMN {col_name} {col_type}"))
                logger.info(f"qc_feedback 表已添加字段: {col_name}")
            except Exception:
                pass


def _ensure_debug_admin():
    """确保本地调试管理员账号存在（仅在首次创建时设置密码，不重置已有密码）。"""
    import logging
    import os
    from app.models import Role, User
    from app.auth import hash_password

    logger = logging.getLogger(__name__)
    admin_username = os.getenv("DEBUG_ADMIN_USERNAME", "admin")
    admin_password = os.getenv("DEBUG_ADMIN_PASSWORD", "Admin123456")
    admin_full_name = os.getenv("DEBUG_ADMIN_FULL_NAME", "系统管理员")
    admin_email = os.getenv("DEBUG_ADMIN_EMAIL", "admin@local.test")

    db = SessionLocal()
    try:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if not admin_role:
            admin_role = Role(name="admin", description="系统管理员")
            db.add(admin_role)
            db.flush()
            logger.info("已自动创建 admin 角色")

        admin_user = db.query(User).filter(User.username == admin_username).first()
        if not admin_user:
            admin_user = User(
                username=admin_username,
                password_hash=hash_password(admin_password),
                full_name=admin_full_name,
                email=admin_email,
                role_id=admin_role.id,
                is_active=True,
            )
            db.add(admin_user)
            logger.info(
                "已自动创建本地调试管理员账号: %s，请登录后立即修改密码",
                admin_username,
            )
        else:
            # 仅修复角色和激活状态，不重置密码
            if not admin_user.role_id:
                admin_user.role_id = admin_role.id
            if not admin_user.is_active:
                admin_user.is_active = True
            logger.debug("管理员账号 %s 已存在，跳过密码重置", admin_username)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_stats() -> dict:
    """
    获取数据库统计信息

    Returns:
        包含数据库大小、表统计等信息的字典
    """
    import os
    from sqlalchemy import text

    stats = {}

    # 数据库文件大小
    if os.path.exists(DB_PATH):
        size_bytes = os.path.getsize(DB_PATH)
        stats['db_size_bytes'] = size_bytes
        stats['db_size_mb'] = round(size_bytes / (1024 * 1024), 2)

    # 表记录数统计
    with engine.connect() as conn:
        for table_name in ['push_log', 'scheduler_history', 'notify_log']:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            stats[f'{table_name}_count'] = result.scalar() or 0

    return stats
