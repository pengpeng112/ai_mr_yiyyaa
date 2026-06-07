"""
SQLAlchemy 数据库模块
支持 SQLite / Oracle 双模式。
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool, NullPool

from app.config import (
    APP_DB_TYPE,
    APP_ORACLE_HOST,
    APP_ORACLE_PASSWORD,
    APP_ORACLE_PORT,
    APP_ORACLE_SERVICE_NAME,
    APP_ORACLE_USERNAME,
    DATA_DIR,
    DB_PATH,
)

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def get_app_db_type() -> str:
    """获取应用数据库类型。"""
    return APP_DB_TYPE


def _build_sqlite_url() -> str:
    return f"sqlite:///{DB_PATH}"


def _build_oracle_url() -> URL:
    if not all([APP_ORACLE_HOST, APP_ORACLE_SERVICE_NAME, APP_ORACLE_USERNAME, APP_ORACLE_PASSWORD]):
        raise ValueError("APP_DB_TYPE=oracle 时，必须配置 APP_ORACLE_HOST/APP_ORACLE_SERVICE_NAME/APP_ORACLE_USERNAME/APP_ORACLE_PASSWORD")
    return URL.create(
        "oracle+cx_oracle",
        username=APP_ORACLE_USERNAME,
        password=APP_ORACLE_PASSWORD,
        host=APP_ORACLE_HOST,
        port=APP_ORACLE_PORT,
        query={"service_name": APP_ORACLE_SERVICE_NAME},
    )


def create_engine_for_config():
    """按配置创建数据库引擎。"""
    if get_app_db_type() == "oracle":
        return create_engine(
            _build_oracle_url(),
            echo=False,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_timeout=10,
            echo_pool=False,
        )

    return create_engine(
        _build_sqlite_url(),
        connect_args={"check_same_thread": False},
        echo=False,
        poolclass=NullPool,
        pool_pre_ping=True,
        echo_pool=False,
    )


engine = create_engine_for_config()

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

    if engine.dialect.name == "sqlite":
        # PushLog 表迁移：为旧数据库添加新字段
        _migrate_push_log_columns()

        # SQLite 性能优化设置
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL;"))
            conn.execute(text("PRAGMA synchronous=NORMAL;"))
            conn.execute(text("PRAGMA cache_size=-10240;"))
            conn.execute(text("PRAGMA temp_store=MEMORY;"))
            conn.execute(text("PRAGMA optimize;"))
    elif engine.dialect.name == "oracle":
        # Oracle 模式下也需要兼容迁移
        _migrate_oracle_alert_columns()
        _ensure_oracle_sequences()

    _verify_required_schema()

    _ensure_default_rbac_permissions()
    _ensure_debug_admin()


def _ensure_default_rbac_permissions():
    """幂等补齐内置权限，避免升级后新权限缺失导致正常角色无法操作。"""
    from app.models import Permission, Role, RolePermission

    permissions_data = [
        {"name": "view_dashboard", "description": "查看仪表板", "module": "dashboard"},
        {"name": "view_reports", "description": "查看质控报告", "module": "qc_reports"},
        {"name": "export_reports", "description": "导出质控报告", "module": "qc_reports"},
        {"name": "view_feedback", "description": "查看反馈", "module": "feedback"},
        {"name": "create_feedback", "description": "创建反馈", "module": "feedback"},
        {"name": "edit_feedback", "description": "编辑反馈", "module": "feedback"},
        {"name": "approve_feedback", "description": "审批反馈", "module": "feedback"},
        {"name": "manage_users", "description": "管理用户", "module": "admin"},
        {"name": "manage_roles", "description": "管理角色", "module": "admin"},
        {"name": "manage_config", "description": "管理系统配置", "module": "admin"},
        {"name": "view_scheduler", "description": "查看调度器", "module": "scheduler"},
        {"name": "manage_scheduler", "description": "管理调度器", "module": "scheduler"},
    ]
    role_permissions_map = {
        "admin": [item["name"] for item in permissions_data],
        "dept_manager": ["view_scheduler", "manage_scheduler"],
    }

    db = SessionLocal()
    try:
        permissions = {}
        for item in permissions_data:
            perm = db.query(Permission).filter(Permission.name == item["name"]).first()
            if not perm:
                perm = Permission(**item)
                db.add(perm)
                db.flush()
            permissions[item["name"]] = perm

        for role_name, perm_names in role_permissions_map.items():
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                role = Role(name=role_name, description="系统管理员" if role_name == "admin" else role_name)
                db.add(role)
                db.flush()
            for perm_name in perm_names:
                perm = permissions.get(perm_name)
                if not perm:
                    continue
                exists = db.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                ).first()
                if not exists:
                    db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_oracle_sequences():
    """确保 Oracle 主键 sequence 存在，兼容旧表已存在但 sequence 缺失的情况。"""
    import logging
    from sqlalchemy import Sequence

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "oracle":
        return

    with engine.begin() as conn:
        inspector = inspect(conn)
        for table in Base.metadata.sorted_tables:
            pk_columns = [column for column in table.columns if column.primary_key]
            if len(pk_columns) != 1:
                continue

            pk_column = pk_columns[0]
            sequence = pk_column.default if isinstance(pk_column.default, Sequence) else None
            if not sequence:
                continue

            sequence_name = sequence.name.upper()
            table_name = table.name
            pk_name = pk_column.name

            try:
                pk_constraint = inspector.get_pk_constraint(table_name) or {}
                constrained = pk_constraint.get("constrained_columns") or []
                if constrained:
                    actual_pk_name = str(constrained[0]).upper()
                else:
                    table_columns = inspector.get_columns(table_name)
                    actual_pk_name = next(
                        (str(column.get("name", "")).upper() for column in table_columns if str(column.get("name", "")).lower() == pk_name.lower()),
                        pk_name.upper(),
                    )
            except Exception:
                actual_pk_name = pk_name.upper()

            exists = conn.execute(
                text("SELECT COUNT(*) FROM user_sequences WHERE sequence_name = :name"),
                {"name": sequence_name},
            ).scalar()
            if exists:
                continue

            try:
                max_id = conn.execute(text(f'SELECT NVL(MAX("{actual_pk_name}"), 0) FROM "{table_name}"')).scalar() or 0
                start_with = int(max_id) + 1
            except Exception as exc:
                logger.warning(
                    "Oracle sequence 起始值计算失败，回退 START WITH 1: table=%s, pk=%s, err=%s",
                    table_name,
                    actual_pk_name,
                    exc,
                )
                start_with = 1
            conn.execute(text(f'CREATE SEQUENCE "{sequence_name}" START WITH {start_with} INCREMENT BY 1 NOCACHE'))
            logger.info("Oracle sequence 已创建: %s (start with %s)", sequence_name, start_with)


def _verify_required_schema():
    """校验关键业务表字段是否已存在，避免迁移静默失败。"""
    import logging

    logger = logging.getLogger(__name__)
    inspector = inspect(engine)
    required_columns = {
        "push_log": {
            "admission_no", "visit_number", "source_record_key", "mr_text", "request_json", "response_json",
            "parse_status", "parse_error", "risk_score", "ai_version", "alert_level",
            "pushed_flag", "reviewed_flag", "reviewed_at", "reviewed_by", "manual_override", "skip_reason",
            "audit_type_code",
        },
        "audit_dimension_result": {
            "dimension_code", "severity", "confidence", "issue_summary", "recommendation",
            "medical_evidence_json", "nursing_evidence_json", "alert_level", "closure_hours",
            "push_strategy", "outcome_bucket", "extra_json",
        },
        "audit_conclusion": {
            "has_inconsistency", "severity", "risk_score", "reasoning_brief", "ai_version",
            "alert_level", "closure_hours", "push_strategy", "outcome_bucket", "overall_qc_summary",
            "extra_json",
        },
        "qc_feedback": {
            "is_viewed", "viewed_at", "view_count", "rectification_clicked",
            "rectification_clicked_at", "suppress_ai_push",
        },
        "scheduler_history": {
            "audit_type_code",
        },
        "export_audit_log": {
            "user_id", "username", "export_type", "export_format",
            "filter_criteria", "record_count", "ip_address", "user_agent", "status", "error_msg",
        },
        "qc_alert_feedback": {
            "alert_log_id", "push_log_id", "dimension_code", "action", "status",
            "doctor_id", "doctor_name", "dept", "reason", "rectification_text",
        },
        "qc_record_alert_log": {
            "push_log_id", "dimension_code", "patient_id", "visit_number", "dept",
            "severity", "alert_level", "payload_json", "status", "retry_count",
            "last_error", "sent_at", "created_at", "updated_at",
            "viewed_flag", "viewed_at", "last_viewed_at", "view_count",
            "viewer_userid", "viewer_name", "viewer_ip", "viewer_user_agent",
        },
    }

    prefix = "MED_" if engine.dialect.name == "oracle" else ""
    missing_report = []
    for table_name, columns in required_columns.items():
        actual_table_name = f"{prefix}{table_name.upper()}" if prefix else table_name
        try:
            actual_columns = {
                str(column["name"]).lower()
                for column in inspector.get_columns(actual_table_name)
            }
        except Exception as exc:
            missing_report.append(f"{actual_table_name}: 无法读取表结构 ({exc})")
            continue

        missing_columns = sorted(column for column in columns if column.lower() not in actual_columns)
        if missing_columns:
            missing_report.append(f"{actual_table_name}: 缺少字段 {', '.join(missing_columns)}")

    if missing_report:
        detail = " | ".join(missing_report)
        logger.error("数据库 Schema 自检失败: %s", detail)
        raise RuntimeError(f"数据库 Schema 自检失败: {detail}")

    logger.info("数据库 Schema 自检通过")


def _is_sqlite_duplicate_column_error(exc: Exception) -> bool:
    """判断 SQLite ALTER TABLE ADD COLUMN 的字段已存在错误。"""
    return "duplicate column name" in str(exc).lower()


def _migrate_push_log_columns():
    """为旧数据库的 push_log 表添加新字段（兼容迁移）"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "sqlite":
        return
    new_columns = [
        ("admission_no", "VARCHAR(50) DEFAULT ''"),
        ("visit_number", "VARCHAR(20) DEFAULT ''"),
        ("audit_type_code", "VARCHAR(64) DEFAULT ''"),
        ("source_record_key", "VARCHAR(255) DEFAULT ''"),
        ("request_json", "TEXT DEFAULT ''"),
        ("response_json", "TEXT DEFAULT ''"),
        ("parse_status", "VARCHAR(20) DEFAULT ''"),
        ("parse_error", "TEXT DEFAULT ''"),
        ("risk_score", "INTEGER DEFAULT 0"),
        ("ai_version", "VARCHAR(20) DEFAULT '1.0'"),
        ("alert_level", "VARCHAR(10) DEFAULT ''"),
        ("pushed_flag", "INTEGER DEFAULT 0"),
        ("reviewed_flag", "INTEGER DEFAULT 0"),
        ("reviewed_at", "DATETIME"),
        ("reviewed_by", "VARCHAR(50) DEFAULT ''"),
        ("manual_override", "INTEGER DEFAULT 0"),
        ("skip_reason", "VARCHAR(200) DEFAULT ''"),
    ]

    errors = []
    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE push_log ADD COLUMN {col_name} {col_type}"))
                logger.info(f"push_log 表已添加字段: {col_name}")
            except Exception as exc:
                if _is_sqlite_duplicate_column_error(exc):
                    logger.debug("push_log.%s 字段已存在，跳过", col_name)
                    continue
                logger.error("push_log.%s 字段迁移失败: %s", col_name, exc, exc_info=True)
                errors.append(f"push_log.{col_name}: {exc}")

    if errors:
        raise RuntimeError(f"SQLite push_log 字段迁移失败: {' | '.join(errors)}")

    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_push_log_audit_type ON push_log(audit_type_code)"))

    _migrate_audit_dimension_result_columns()
    _migrate_audit_conclusion_columns()
    _migrate_qc_feedback_columns()
    _migrate_scheduler_history_columns()
    _migrate_export_audit_log_columns()
    _migrate_qc_record_alert_log_columns()


def _migrate_export_audit_log_columns():
    """为旧数据库的 export_audit_log 表添加字段（兼容迁移）"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "sqlite":
        return

    new_columns = [
        ("user_id", "INTEGER NOT NULL DEFAULT 0"),
        ("username", "VARCHAR(50) DEFAULT ''"),
        ("export_type", "VARCHAR(20) DEFAULT ''"),
        ("export_format", "VARCHAR(10) DEFAULT ''"),
        ("filter_criteria", "TEXT DEFAULT ''"),
        ("record_count", "INTEGER DEFAULT 0"),
        ("ip_address", "VARCHAR(50) DEFAULT ''"),
        ("user_agent", "TEXT DEFAULT ''"),
        ("status", "VARCHAR(20) DEFAULT 'success'"),
        ("error_msg", "TEXT DEFAULT ''"),
    ]

    # 先创建表（如果不存在）
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS export_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                export_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER NOT NULL DEFAULT 0,
                username VARCHAR(50) DEFAULT '',
                export_type VARCHAR(20) DEFAULT '',
                export_format VARCHAR(10) DEFAULT '',
                filter_criteria TEXT DEFAULT '',
                record_count INTEGER DEFAULT 0,
                ip_address VARCHAR(50) DEFAULT '',
                user_agent TEXT DEFAULT '',
                status VARCHAR(20) DEFAULT 'success',
                error_msg TEXT DEFAULT ''
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_export_audit_user_time ON export_audit_log(user_id, export_time)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_export_audit_type_time ON export_audit_log(export_type, export_time)"))

    errors = []
    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE export_audit_log ADD COLUMN {col_name} {col_type}"))
                logger.info("export_audit_log 表已添加字段: %s", col_name)
            except Exception as exc:
                if _is_sqlite_duplicate_column_error(exc):
                    logger.debug("export_audit_log.%s 字段已存在，跳过", col_name)
                    continue
                logger.error("export_audit_log.%s 字段迁移失败: %s", col_name, exc, exc_info=True)
                errors.append(f"export_audit_log.{col_name}: {exc}")

    if errors:
        raise RuntimeError(f"SQLite export_audit_log 字段迁移失败: {' | '.join(errors)}")


def _migrate_scheduler_history_columns():
    """为旧数据库的 scheduler_history 表添加审计类型字段。"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "sqlite":
        return

    errors = []
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE scheduler_history ADD COLUMN audit_type_code VARCHAR(64) DEFAULT ''"))
            logger.info("scheduler_history 表已添加字段: audit_type_code")
        except Exception as exc:
            if _is_sqlite_duplicate_column_error(exc):
                logger.debug("scheduler_history.audit_type_code 字段已存在，跳过")
            else:
                logger.error("scheduler_history.audit_type_code 字段迁移失败: %s", exc, exc_info=True)
                errors.append(f"scheduler_history.audit_type_code: {exc}")
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduler_history_audit_type ON scheduler_history(audit_type_code)"))

    if errors:
        raise RuntimeError(f"SQLite scheduler_history 字段迁移失败: {' | '.join(errors)}")


def _migrate_audit_dimension_result_columns():
    """为旧数据库的 audit_dimension_result 表添加新字段。"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "sqlite":
        return
    new_columns = [
        ("dimension_code", "VARCHAR(64) DEFAULT ''"),
        ("severity", "VARCHAR(20) DEFAULT ''"),
        ("confidence", "REAL DEFAULT 0"),
        ("issue_summary", "TEXT DEFAULT ''"),
        ("recommendation", "TEXT DEFAULT ''"),
        ("medical_evidence_json", "TEXT DEFAULT '[]'"),
        ("nursing_evidence_json", "TEXT DEFAULT '[]'"),
        ("alert_level", "VARCHAR(10) DEFAULT ''"),
        ("closure_hours", "INTEGER DEFAULT 0"),
        ("push_strategy", "VARCHAR(20) DEFAULT ''"),
        ("outcome_bucket", "VARCHAR(20) DEFAULT ''"),
        ("extra_json", "TEXT DEFAULT '{}'"),
    ]

    errors = []
    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE audit_dimension_result ADD COLUMN {col_name} {col_type}"))
                logger.info(f"audit_dimension_result 表已添加字段: {col_name}")
            except Exception as exc:
                if _is_sqlite_duplicate_column_error(exc):
                    logger.debug("audit_dimension_result.%s 字段已存在，跳过", col_name)
                    continue
                logger.error("audit_dimension_result.%s 字段迁移失败: %s", col_name, exc, exc_info=True)
                errors.append(f"audit_dimension_result.{col_name}: {exc}")

    if errors:
        raise RuntimeError(f"SQLite audit_dimension_result 字段迁移失败: {' | '.join(errors)}")


def _migrate_audit_conclusion_columns():
    """为旧数据库的 audit_conclusion 表添加新字段。"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "sqlite":
        return
    new_columns = [
        ("has_inconsistency", "INTEGER DEFAULT 0"),
        ("severity", "VARCHAR(20) DEFAULT ''"),
        ("risk_score", "INTEGER DEFAULT 0"),
        ("reasoning_brief", "TEXT DEFAULT ''"),
        ("ai_version", "VARCHAR(20) DEFAULT '1.0'"),
        ("alert_level", "VARCHAR(10) DEFAULT ''"),
        ("closure_hours", "INTEGER DEFAULT 0"),
        ("push_strategy", "VARCHAR(20) DEFAULT ''"),
        ("outcome_bucket", "VARCHAR(20) DEFAULT ''"),
        ("overall_qc_summary", "TEXT DEFAULT ''"),
        ("extra_json", "TEXT DEFAULT '{}'"),
    ]

    errors = []
    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE audit_conclusion ADD COLUMN {col_name} {col_type}"))
                logger.info(f"audit_conclusion 表已添加字段: {col_name}")
            except Exception as exc:
                if _is_sqlite_duplicate_column_error(exc):
                    logger.debug("audit_conclusion.%s 字段已存在，跳过", col_name)
                    continue
                logger.error("audit_conclusion.%s 字段迁移失败: %s", col_name, exc, exc_info=True)
                errors.append(f"audit_conclusion.{col_name}: {exc}")

    if errors:
        raise RuntimeError(f"SQLite audit_conclusion 字段迁移失败: {' | '.join(errors)}")


def _migrate_qc_feedback_columns():
    """为旧数据库的 qc_feedback 表添加新字段。"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "sqlite":
        return
    new_columns = [
        ("is_viewed", "BOOLEAN DEFAULT 0"),
        ("viewed_at", "DATETIME"),
        ("view_count", "INTEGER DEFAULT 0"),
        ("rectification_clicked", "BOOLEAN DEFAULT 0"),
        ("rectification_clicked_at", "DATETIME"),
        ("suppress_ai_push", "BOOLEAN DEFAULT 0"),
    ]

    errors = []
    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE qc_feedback ADD COLUMN {col_name} {col_type}"))
                logger.info(f"qc_feedback 表已添加字段: {col_name}")
            except Exception as exc:
                if _is_sqlite_duplicate_column_error(exc):
                    logger.debug("qc_feedback.%s 字段已存在，跳过", col_name)
                    continue
                logger.error("qc_feedback.%s 字段迁移失败: %s", col_name, exc, exc_info=True)
                errors.append(f"qc_feedback.{col_name}: {exc}")

    if errors:
        raise RuntimeError(f"SQLite qc_feedback 字段迁移失败: {' | '.join(errors)}")


def _migrate_qc_record_alert_log_columns():
    """为旧数据库的 qc_record_alert_log 表添加查看记录字段。"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "sqlite":
        return
    new_columns = [
        ("viewed_flag", "INTEGER DEFAULT 0"),
        ("viewed_at", "DATETIME"),
        ("last_viewed_at", "DATETIME"),
        ("view_count", "INTEGER DEFAULT 0"),
        ("viewer_userid", "VARCHAR(64) DEFAULT ''"),
        ("viewer_name", "VARCHAR(64) DEFAULT ''"),
        ("viewer_ip", "VARCHAR(64) DEFAULT ''"),
        ("viewer_user_agent", "TEXT DEFAULT ''"),
    ]

    errors = []
    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE qc_record_alert_log ADD COLUMN {col_name} {col_type}"))
                logger.info("qc_record_alert_log 表已添加字段: %s", col_name)
            except Exception as exc:
                if _is_sqlite_duplicate_column_error(exc):
                    logger.debug("qc_record_alert_log.%s 字段已存在，跳过", col_name)
                    continue
                logger.error("qc_record_alert_log.%s 字段迁移失败: %s", col_name, exc, exc_info=True)
                errors.append(f"qc_record_alert_log.{col_name}: {exc}")
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_alert_view_flag ON qc_record_alert_log(viewed_flag)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_alert_view_at ON qc_record_alert_log(viewed_at)"))

    if errors:
        raise RuntimeError(f"SQLite qc_record_alert_log 字段迁移失败: {' | '.join(errors)}")


def _migrate_oracle_alert_columns():
    """为 Oracle 模式下的旧表补齐兼容字段（含预警分级字段）。"""
    import logging

    logger = logging.getLogger(__name__)
    if engine.dialect.name != "oracle":
        return

    # Oracle 中表名有 MED_ 前缀
    alert_migrations = [
        ("MED_PUSH_LOG", [
            ("ADMISSION_NO", "VARCHAR2(50) DEFAULT ''"),
            ("VISIT_NUMBER", "VARCHAR2(20) DEFAULT ''"),
            ("AUDIT_TYPE_CODE", "VARCHAR2(64) DEFAULT ''"),
            ("SOURCE_RECORD_KEY", "VARCHAR2(255) DEFAULT ''"),
            ("REQUEST_JSON", "CLOB"),
            ("RESPONSE_JSON", "CLOB"),
            ("PARSE_STATUS", "VARCHAR2(20) DEFAULT ''"),
            ("PARSE_ERROR", "CLOB"),
            ("RISK_SCORE", "NUMBER DEFAULT 0"),
            ("AI_VERSION", "VARCHAR2(20) DEFAULT '1.0'"),
            ("ALERT_LEVEL", "VARCHAR2(10) DEFAULT ''"),
            ("PUSHED_FLAG", "NUMBER DEFAULT 0"),
            ("REVIEWED_FLAG", "NUMBER DEFAULT 0"),
            ("REVIEWED_AT", "TIMESTAMP NULL"),
            ("REVIEWED_BY", "VARCHAR2(50) DEFAULT ''"),
            ("MANUAL_OVERRIDE", "NUMBER DEFAULT 0"),
            ("SKIP_REASON", "VARCHAR2(200) DEFAULT ''"),
        ]),
        ("MED_AUDIT_DIMENSION_RESULT", [
            ("DIMENSION_CODE", "VARCHAR2(64) DEFAULT ''"),
            ("SEVERITY", "VARCHAR2(20) DEFAULT ''"),
            ("CONFIDENCE", "NUMBER DEFAULT 0"),
            ("ISSUE_SUMMARY", "CLOB"),
            ("RECOMMENDATION", "CLOB"),
            ("MEDICAL_EVIDENCE_JSON", "CLOB"),
            ("NURSING_EVIDENCE_JSON", "CLOB"),
            ("ALERT_LEVEL", "VARCHAR2(10) DEFAULT ''"),
            ("CLOSURE_HOURS", "NUMBER DEFAULT 0"),
            ("PUSH_STRATEGY", "VARCHAR2(20) DEFAULT ''"),
            ("OUTCOME_BUCKET", "VARCHAR2(20) DEFAULT ''"),
            ("EXTRA_JSON", "CLOB"),
        ]),
        ("MED_AUDIT_CONCLUSION", [
            ("HAS_INCONSISTENCY", "NUMBER DEFAULT 0"),
            ("SEVERITY", "VARCHAR2(20) DEFAULT ''"),
            ("RISK_SCORE", "NUMBER DEFAULT 0"),
            ("REASONING_BRIEF", "CLOB"),
            ("AI_VERSION", "VARCHAR2(20) DEFAULT '1.0'"),
            ("ALERT_LEVEL", "VARCHAR2(10) DEFAULT ''"),
            ("CLOSURE_HOURS", "NUMBER DEFAULT 0"),
            ("PUSH_STRATEGY", "VARCHAR2(20) DEFAULT ''"),
            ("OUTCOME_BUCKET", "VARCHAR2(20) DEFAULT ''"),
            ("OVERALL_QC_SUMMARY", "CLOB"),
            ("EXTRA_JSON", "CLOB"),
        ]),
        ("MED_QC_FEEDBACK", [
            ("IS_VIEWED", "NUMBER(1) DEFAULT 0"),
            ("VIEWED_AT", "TIMESTAMP NULL"),
            ("VIEW_COUNT", "NUMBER DEFAULT 0"),
            ("RECTIFICATION_CLICKED", "NUMBER(1) DEFAULT 0"),
            ("RECTIFICATION_CLICKED_AT", "TIMESTAMP NULL"),
            ("SUPPRESS_AI_PUSH", "NUMBER(1) DEFAULT 0"),
        ]),
        ("MED_SCHEDULER_HISTORY", [
            ("AUDIT_TYPE_CODE", "VARCHAR2(64) DEFAULT ''"),
        ]),
        ("MED_EXPORT_AUDIT_LOG", [
            ("USER_ID", "NUMBER DEFAULT 0"),
            ("USERNAME", "VARCHAR2(50) DEFAULT ''"),
            ("EXPORT_TYPE", "VARCHAR2(20) DEFAULT ''"),
            ("EXPORT_FORMAT", "VARCHAR2(10) DEFAULT ''"),
            ("FILTER_CRITERIA", "CLOB"),
            ("RECORD_COUNT", "NUMBER DEFAULT 0"),
            ("IP_ADDRESS", "VARCHAR2(50) DEFAULT ''"),
            ("USER_AGENT", "CLOB"),
            ("STATUS", "VARCHAR2(20) DEFAULT 'success'"),
            ("ERROR_MSG", "CLOB"),
        ]),
        ("MED_QC_RECORD_ALERT_LOG", [
            ("VIEWED_FLAG", "NUMBER(1) DEFAULT 0"),
            ("VIEWED_AT", "TIMESTAMP NULL"),
            ("LAST_VIEWED_AT", "TIMESTAMP NULL"),
            ("VIEW_COUNT", "NUMBER DEFAULT 0"),
            ("VIEWER_USERID", "VARCHAR2(64) DEFAULT ''"),
            ("VIEWER_NAME", "VARCHAR2(64) DEFAULT ''"),
            ("VIEWER_IP", "VARCHAR2(64) DEFAULT ''"),
            ("VIEWER_USER_AGENT", "CLOB"),
        ]),
    ]

    errors = []
    with engine.connect() as conn:
        for table_name, columns in alert_migrations:
            # 先确保表存在（export_audit_log 是新表）
            if table_name == "MED_EXPORT_AUDIT_LOG":
                try:
                    conn.execute(text("""
                        CREATE TABLE MED_EXPORT_AUDIT_LOG (
                            ID NUMBER PRIMARY KEY,
                            EXPORT_TIME TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                            USER_ID NUMBER DEFAULT 0,
                            USERNAME VARCHAR2(50) DEFAULT '',
                            EXPORT_TYPE VARCHAR2(20) DEFAULT '',
                            EXPORT_FORMAT VARCHAR2(10) DEFAULT '',
                            FILTER_CRITERIA CLOB,
                            RECORD_COUNT NUMBER DEFAULT 0,
                            IP_ADDRESS VARCHAR2(50) DEFAULT '',
                            USER_AGENT CLOB,
                            STATUS VARCHAR2(20) DEFAULT 'success',
                            ERROR_MSG CLOB
                        )
                    """))
                    logger.info("Oracle 表 MED_EXPORT_AUDIT_LOG 已创建")
                except Exception as exc:
                    if "ORA-00955" in str(exc) or "name is already used" in str(exc).lower():
                        logger.debug("MED_EXPORT_AUDIT_LOG 表已存在，跳过创建")
                    else:
                        logger.error("MED_EXPORT_AUDIT_LOG 表创建失败: %s", exc, exc_info=True)
                        errors.append(f"MED_EXPORT_AUDIT_LOG: {exc}")

                for index_sql, index_name in [
                    ("CREATE INDEX IDX_EXPORT_AUDIT_USER_TIME ON MED_EXPORT_AUDIT_LOG(USER_ID, EXPORT_TIME)", "IDX_EXPORT_AUDIT_USER_TIME"),
                    ("CREATE INDEX IDX_EXPORT_AUDIT_TYPE_TIME ON MED_EXPORT_AUDIT_LOG(EXPORT_TYPE, EXPORT_TIME)", "IDX_EXPORT_AUDIT_TYPE_TIME"),
                ]:
                    try:
                        conn.execute(text(index_sql))
                        logger.info("Oracle 索引 %s 已创建", index_name)
                    except Exception as exc:
                        if "ORA-00955" in str(exc) or "name is already used" in str(exc).lower():
                            logger.debug("MED_EXPORT_AUDIT_LOG 索引 %s 已存在，跳过创建", index_name)
                        else:
                            logger.error("MED_EXPORT_AUDIT_LOG 索引 %s 创建失败: %s", index_name, exc, exc_info=True)
                            errors.append(f"MED_EXPORT_AUDIT_LOG.{index_name}: {exc}")
            for col_name, col_type in columns:
                try:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD {col_name} {col_type}"))
                    logger.info(f"{table_name} 表已添加字段: {col_name}")
                except Exception as exc:
                    err_msg = str(exc)
                    if "ORA-01430" in err_msg or "column being added already exists" in err_msg.lower():
                        logger.debug("%s.%s 字段已存在，跳过", table_name, col_name)
                        continue
                    logger.error("%s.%s 字段迁移失败: %s", table_name, col_name, err_msg, exc_info=True)
                    errors.append(f"{table_name}.{col_name}: {err_msg}")
            # Oracle 索引创建 — alert 查看字段
            if table_name == "MED_QC_RECORD_ALERT_LOG":
                for index_sql, index_name in [
                    ("CREATE INDEX IDX_ALERT_VIEW_FLAG ON MED_QC_RECORD_ALERT_LOG(VIEWED_FLAG)", "IDX_ALERT_VIEW_FLAG"),
                    ("CREATE INDEX IDX_ALERT_VIEW_AT ON MED_QC_RECORD_ALERT_LOG(VIEWED_AT)", "IDX_ALERT_VIEW_AT"),
                ]:
                    try:
                        conn.execute(text(index_sql))
                        logger.info("Oracle 索引 %s 已创建", index_name)
                    except Exception as exc:
                        if "ORA-00955" in str(exc) or "name is already used" in str(exc).lower():
                            logger.debug("索引 %s 已存在", index_name)
                        else:
                            logger.error("索引 %s 创建失败: %s", index_name, exc, exc_info=True)
                            errors.append(f"{table_name}.{index_name}: {exc}")

    if errors:
        detail = " | ".join(errors)
        raise RuntimeError(f"Oracle 字段迁移失败: {detail}")


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
    stats = {}
    stats['db_type'] = engine.dialect.name

    # SQLite 数据库文件大小
    if engine.dialect.name == "sqlite" and os.path.exists(DB_PATH):
        size_bytes = os.path.getsize(DB_PATH)
        stats['db_size_bytes'] = size_bytes
        stats['db_size_mb'] = round(size_bytes / (1024 * 1024), 2)
    elif engine.dialect.name == "oracle":
        stats['db_size_bytes'] = None
        stats['db_size_mb'] = None

    # 表记录数统计
    with engine.connect() as conn:
        table_names = inspect(engine).get_table_names()
        target_tables = [
            name for name in table_names
            if name.lower() in {'push_log', 'scheduler_history', 'notify_log', 'med_push_log', 'med_scheduler_history', 'med_notify_log'}
        ]
        for table_name in target_tables:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            stats[f'{table_name}_count'] = result.scalar() or 0

    return stats


def test_app_db_connection() -> dict:
    """测试应用数据库连通性。"""
    try:
        with engine.connect() as conn:
            sql = "SELECT 1 FROM DUAL" if engine.dialect.name == "oracle" else "SELECT 1"
            conn.execute(text(sql))
        return {"status": "up", "db_type": engine.dialect.name}
    except Exception as exc:
        return {"status": "down", "db_type": engine.dialect.name, "message": str(exc)}
