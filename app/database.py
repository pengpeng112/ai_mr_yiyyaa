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
        # pool_pre_ping：检出前探测，避免监听恢复后继续拿到死连接
        # pool_recycle：定期回收，降低陈旧连接概率
        # pool_reset_on_return：归还时 rollback，减少脏会话
        return create_engine(
            _build_oracle_url(),
            echo=False,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=900,
            pool_timeout=10,
            pool_reset_on_return="rollback",
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


def is_transient_app_db_error(exc: BaseException) -> bool:
    """应用库瞬时错误（含 ORA-12541 等），供探测与重试判定。"""
    text = f"{type(exc).__name__} {exc}".lower()
    markers = (
        "ora-12541",
        "ora-12514",
        "ora-12516",
        "ora-12519",
        "ora-12528",
        "ora-12537",
        "ora-12547",
        "ora-12609",
        "ora-03113",
        "ora-03114",
        "ora-03135",
        "ora-00028",
        "ora-01012",
        "dpi-1010",
        "dpi-1080",
        "tns: receive timeout",
        "tns:no listener",
        "connection reset",
        "broken pipe",
        "not connected",
        "server closed the connection",
        "connection was closed",
    )
    return any(m in text for m in markers)


def dispose_app_db_pool(reason: str = "") -> None:
    """丢弃应用库连接池中的全部连接，下次使用时重建。不影响路由注册与业务逻辑。"""
    import logging
    logger = logging.getLogger(__name__)
    try:
        engine.dispose()
        logger.warning("应用库连接池已 dispose%s", f": {reason}" if reason else "")
    except Exception:
        logger.exception("应用库连接池 dispose 失败")

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

    # 015/C1：当前结果身份唯一（历史行可多条；与 push_execution 幂等键语义不同）
    _ensure_push_log_current_identity_unique_index()

    _verify_required_schema()

    _ensure_default_rbac_permissions()


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
        {"name": "manage_push", "description": "手动推送与重推", "module": "push"},
        {"name": "manage_historical_rerun", "description": "历史质控重新核查", "module": "push"},
    ]
    role_permissions_map = {
        "admin": [item["name"] for item in permissions_data],
        "dept_manager": ["view_scheduler", "manage_scheduler", "view_reports"],
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
            "audit_type_code", "audit_run_mode", "superseded_by", "superseded_at",
            "contract_valid", "contract_errors",
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
            "audit_type_code", "audit_run_mode", "error_code", "error_msg",
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
        "push_execution": {
            "idempotency_key", "audit_run_mode", "source_record_key", "audit_type_code",
            "source_version", "status", "owner_token", "lease_until", "push_log_id",
            "reviewed_flag", "created_at", "updated_at",
        },
        "push_attempt": {
            "execution_id", "attempt_no", "status", "target_name", "elapsed_ms",
            "error_message", "started_at", "finished_at",
        },
        "historical_rerun_batch": {
            "status", "actor", "reason", "date_from", "date_to", "date_dimension",
            "audit_type_codes_json", "dept_filter_json", "existing_result_policy",
            "alert_policy", "candidate_hash", "config_snapshot_hash",
            "candidate_count", "processed", "success_count", "failed_count",
            "skipped_count", "superseded_count", "created_at",
            "consumer_owner", "consumer_lease_until", "consumer_heartbeat_at",
        },
        "historical_rerun_item": {
            "batch_id", "business_identity_hash", "source_record_key", "audit_type_code",
            "audit_run_mode", "patient_id", "visit_number", "query_date", "status",
            "previous_current_push_log_id", "new_push_log_id", "execution_id",
            "reason_code", "attempt_count", "created_at", "updated_at",
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


def _count_push_log_multi_current_groups() -> int:
    """统计「同一身份多条 success 当前」分组数；>0 时不得创建当前唯一索引。

    仅统计 status=success：skipped/failed 可与 success 并存（跳过日志也写 source_record_key）。
    """
    table = "MED_PUSH_LOG" if engine.dialect.name == "oracle" else "push_log"
    sql = f"""
    SELECT COUNT(*) FROM (
      SELECT source_record_key, audit_type_code, audit_run_mode
      FROM {table}
      WHERE superseded_by IS NULL
        AND source_record_key IS NOT NULL
        AND status = 'success'
      GROUP BY source_record_key, audit_type_code, audit_run_mode
      HAVING COUNT(*) > 1
    ) dup_groups
    """
    with engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar() or 0)


def _push_log_current_identity_index_ddl(table: str, dialect: str) -> str:
    """success 当前唯一：允许多条 skipped/failed 当前，禁止两条 success 当前。"""
    if dialect == "oracle":
        return f"""
            CREATE UNIQUE INDEX uq_push_log_current_identity ON {table} (
              CASE WHEN superseded_by IS NULL
                        AND source_record_key IS NOT NULL
                        AND status = 'success'
                   THEN source_record_key END,
              CASE WHEN superseded_by IS NULL
                        AND source_record_key IS NOT NULL
                        AND status = 'success'
                   THEN NVL(audit_type_code, CHR(0)) END,
              CASE WHEN superseded_by IS NULL
                        AND source_record_key IS NOT NULL
                        AND status = 'success'
                   THEN NVL(audit_run_mode, 'daily_increment') END
            )
        """
    return f"""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_push_log_current_identity
            ON {table}(source_record_key, audit_type_code, audit_run_mode)
            WHERE superseded_by IS NULL
              AND source_record_key IS NOT NULL
              AND source_record_key != ''
              AND status = 'success'
        """


def _ensure_push_log_current_identity_unique_index() -> None:
    """015/C1：为 PushLog success 当前结果增加部分/函数唯一索引。

    - 不删除历史行；仅保证 (source_record_key, audit_type_code, audit_run_mode)
      在 status=success 且 superseded_by IS NULL 时至多一条。
    - skipped/failed 不受此唯一约束（避免跳过日志与成功结果冲突）。
    - 与 MED_PUSH_EXECUTION 的 uq_push_execution_key_mode（幂等 claim）语义不同，可并存。
    - 若索引定义过时（旧版约束所有 status），删除后按 success 口径重建。
    """
    import logging

    logger = logging.getLogger(__name__)
    dialect = engine.dialect.name
    index_name = "uq_push_log_current_identity"
    table = "MED_PUSH_LOG" if dialect == "oracle" else "push_log"

    def _index_exists(conn) -> bool:
        if dialect == "oracle":
            n = conn.execute(
                text("SELECT COUNT(*) FROM user_indexes WHERE index_name = :n"),
                {"n": index_name.upper()},
            ).scalar()
            return int(n or 0) > 0
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": index_name},
        ).fetchall()
        return bool(rows)

    def _index_is_success_scoped(conn) -> bool:
        """粗检：DDL/定义中是否含 status=success（旧索引无此条件）。"""
        try:
            if dialect == "oracle":
                # user_ind_expressions 存函数索引表达式
                rows = conn.execute(
                    text(
                        """
                        SELECT column_expression FROM user_ind_expressions
                        WHERE index_name = :n
                        """
                    ),
                    {"n": index_name.upper()},
                ).fetchall()
                blob = " ".join(str(r[0] or "") for r in rows).lower()
                return "status" in blob and "success" in blob
            row = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:n"),
                {"n": index_name},
            ).fetchone()
            sql = str(row[0] or "").lower() if row else ""
            return "status" in sql and "success" in sql
        except Exception:
            return False

    try:
        with engine.connect() as conn:
            exists = _index_exists(conn)
            if exists and _index_is_success_scoped(conn):
                logger.debug("索引已存在且为 success 口径，跳过: %s", index_name)
                return
    except Exception as exc:
        logger.warning("检查 PushLog 当前唯一索引失败，跳过创建: %s", exc)
        return

    try:
        dup_groups = _count_push_log_multi_current_groups()
    except Exception as exc:
        logger.warning("统计 PushLog 多当前分组失败，跳过唯一索引: %s", exc)
        return
    if dup_groups > 0:
        logger.error(
            "PushLog 仍有 %s 组 success 多当前重复，跳过创建 %s；请先执行 "
            "scripts/remediate_pushlog_multi_current.py --apply",
            dup_groups,
            index_name,
        )
        return

    try:
        with engine.begin() as conn:
            if _index_exists(conn):
                # 旧版索引（约束所有 status）需重建为 success 口径
                if dialect == "oracle":
                    conn.execute(text(f"DROP INDEX {index_name}"))
                else:
                    conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
                logger.info("已删除过时 PushLog 当前唯一索引，准备按 success 口径重建: %s", index_name)
            conn.execute(text(_push_log_current_identity_index_ddl(table, dialect)))
        logger.info("已创建 PushLog success 当前唯一索引: %s", index_name)
    except Exception as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "ora-00955" in msg or "name is already used" in msg:
            logger.info("PushLog 当前唯一索引已存在: %s", index_name)
            return
        logger.error("创建 PushLog 当前唯一索引失败: %s", exc, exc_info=True)


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
        ("audit_run_mode", "VARCHAR(32) DEFAULT 'daily_increment'"),
        ("superseded_by", "INTEGER"),
        ("superseded_at", "DATETIME"),
        ("contract_valid", "INTEGER"),
        ("contract_errors", "TEXT DEFAULT ''"),
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
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_push_supersede_lookup ON push_log(patient_id, visit_number, audit_type_code, audit_run_mode, status)"))

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

    new_columns_sh = [
        ("audit_type_code", "VARCHAR(64) DEFAULT ''"),
        ("audit_run_mode", "VARCHAR(32) DEFAULT 'daily_increment'"),
        ("error_code", "VARCHAR(48) DEFAULT ''"),
        ("error_msg", "TEXT DEFAULT ''"),
    ]
    errors = []
    with engine.connect() as conn:
        for col_name, col_type in new_columns_sh:
            try:
                conn.execute(text(f"ALTER TABLE scheduler_history ADD COLUMN {col_name} {col_type}"))
                logger.info("scheduler_history 表已添加字段: %s", col_name)
            except Exception as exc:
                if _is_sqlite_duplicate_column_error(exc):
                    logger.debug("scheduler_history.%s 字段已存在，跳过", col_name)
                    continue
                logger.error("scheduler_history.%s 字段迁移失败: %s", col_name, exc, exc_info=True)
                errors.append(f"scheduler_history.{col_name}: {exc}")
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduler_history_audit_type ON scheduler_history(audit_type_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduler_history_run_mode ON scheduler_history(audit_run_mode)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduler_history_error_code ON scheduler_history(error_code)"))

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
            ("AUDIT_RUN_MODE", "VARCHAR2(32) DEFAULT 'daily_increment'"),
            ("SUPERSEDED_BY", "NUMBER(10)"),
            ("SUPERSEDED_AT", "TIMESTAMP NULL"),
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
            ("AUDIT_RUN_MODE", "VARCHAR2(32) DEFAULT 'daily_increment'"),
            ("ERROR_CODE", "VARCHAR2(48) DEFAULT ''"),
            ("ERROR_MSG", "CLOB"),
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
        ("MED_HISTORICAL_RERUN_BATCH", [
            ("CONSUMER_OWNER", "VARCHAR2(64) DEFAULT ''"),
            ("CONSUMER_LEASE_UNTIL", "TIMESTAMP NULL"),
            ("CONSUMER_HEARTBEAT_AT", "TIMESTAMP NULL"),
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
            if table_name == "MED_SCHEDULER_HISTORY":
                for index_sql, index_name in [
                    ("CREATE INDEX IDX_SCHED_HIST_RUN_MODE ON MED_SCHEDULER_HISTORY(AUDIT_RUN_MODE)", "IDX_SCHED_HIST_RUN_MODE"),
                    ("CREATE INDEX IDX_SCHED_HIST_ERR_CODE ON MED_SCHEDULER_HISTORY(ERROR_CODE)", "IDX_SCHED_HIST_ERR_CODE"),
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
    """测试应用数据库连通性；瞬时失败时 dispose 后重试一次。"""
    sql = "SELECT 1 FROM DUAL" if engine.dialect.name == "oracle" else "SELECT 1"
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
        return {"status": "up", "db_type": engine.dialect.name}
    except Exception as exc:
        if is_transient_app_db_error(exc):
            dispose_app_db_pool(reason=f"health_retry_after {type(exc).__name__}")
            try:
                with engine.connect() as conn:
                    conn.execute(text(sql))
                return {
                    "status": "up",
                    "db_type": engine.dialect.name,
                    "recovered": True,
                    "message": "recovered after pool dispose",
                }
            except Exception as retry_exc:
                return {
                    "status": "down",
                    "db_type": engine.dialect.name,
                    "message": str(retry_exc)[:300],
                    "transient": True,
                }
        return {"status": "down", "db_type": engine.dialect.name, "message": str(exc)[:300]}
