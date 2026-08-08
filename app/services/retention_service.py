"""
数据留存清理服务 —— 按分级策略自动清理过期敏感数据
L1: 日志/元数据，保留 90 天
L2: 审计结果/摘要，保留 365 天
L3: 原始病历文本(mr_text/request_json/response_json)，保留 30 天后脱敏或删除
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_app_db_type
from app.models import PushLog, AuditDimensionResult, AuditConclusion, NotifyLog, SchedulerHistory, ExportAuditLog, QCRecordAlertLog, QCAlertFeedback, QCFeedback

logger = logging.getLogger(__name__)

# L3 脱敏占位符（与库内历史写入保持一致）
_MASK_TEXT = "[已清理]"
_MASK_JSON_OBJ = "{}"
_MASK_JSON_ARR = "[]"


def _is_oracle_db() -> bool:
    return get_app_db_type() == "oracle"


def _sql_not_equal_text(column: str, value: str, *, oracle: bool) -> str:
    """生成「列为空或尚未脱敏」条件。

    Oracle CLOB 不能与 VARCHAR2 直接用 !=（ORA-00932），须经 DBMS_LOB.SUBSTR 比较。
    """
    if not oracle:
        # SQLite / 非 CLOB：普通比较即可
        lit = value.replace("'", "''")
        return f"({column} IS NULL OR {column} != '{lit}')"
    # 只比前缀：脱敏后整列即为占位符；病历原文前 N 字几乎不可能等于占位符
    n = max(len(value), 1)
    lit = value.replace("'", "''")
    return (
        f"({column} IS NULL OR "
        f"NVL(DBMS_LOB.SUBSTR({column}, {n}, 1), CHR(0)) <> '{lit}')"
    )


class RetentionConfig:
    """数据留存配置"""

    def __init__(self, cfg: Optional[dict] = None):
        raw = cfg or {}
        self.enabled = bool(raw.get("enabled", True))
        self.l1_days = int(raw.get("l1_log_meta_days", 90))
        self.l2_days = int(raw.get("l2_audit_summary_days", 365))
        self.l3_days = int(raw.get("l3_sensitive_content_days", 30))
        batch_size = max(int(raw.get("cleanup_batch_size", 500)), 1)
        self.batch_size = batch_size


class RetentionService:
    """数据留存清理服务"""

    def __init__(self, db: Session, config: Optional[RetentionConfig] = None):
        self.db = db
        self.config = config or RetentionConfig()
        self.audit_logger = logging.getLogger("audit.retention")

    def run_cleanup(self) -> dict:
        """执行全量清理，返回各层级清理统计"""
        if not self.config.enabled:
            logger.info("数据留存清理已禁用，跳过")
            return {"enabled": False, "l1": {}, "l2": {}, "l3": {}}

        logger.info("开始数据留存清理: l1=%sd, l2=%sd, l3=%sd", self.config.l1_days, self.config.l2_days, self.config.l3_days)

        l1_result = self._cleanup_l1()
        l2_result = self._cleanup_l2()
        l3_result = self._cleanup_l3()

        summary = {
            "enabled": True,
            "run_at": datetime.now().isoformat(),
            "l1": l1_result,
            "l2": l2_result,
            "l3": l3_result,
        }

        self.audit_logger.info("[AUDIT] 数据留存清理完成: %s", json.dumps(summary, ensure_ascii=False, default=str))
        logger.info("数据留存清理完成: l1_deleted=%s, l2_deleted=%s, l3_masked=%s", l1_result.get("deleted", 0), l2_result.get("deleted", 0), l3_result.get("masked", 0))
        return summary

    def _cleanup_l1(self) -> dict:
        """L1: 清理超过保留期的日志/元数据（notify_log, scheduler_history, export_audit_log）"""
        cutoff = datetime.now() - timedelta(days=self.config.l1_days)
        deleted_total = 0
        app_db_type = get_app_db_type()

        # NotifyLog
        table_name = NotifyLog.__tablename__
        try:
            result = self.db.execute(
                text(f"DELETE FROM {table_name} WHERE notify_time < :cutoff"),
                {"cutoff": cutoff},
            )
            deleted = result.rowcount or 0
            deleted_total += deleted
            if deleted:
                logger.info("L1 清理: %s 删除 %s 条 (<%s)", table_name, deleted, cutoff.date())
        except Exception as exc:
            if "ORA-00942" in str(exc):
                logger.warning("L1 清理跳过不存在表: %s", table_name)
            else:
                logger.error("L1 清理 %s 失败: %s", table_name, exc, exc_info=True)
            self.db.rollback()

        # SchedulerHistory
        table_name = SchedulerHistory.__tablename__
        try:
            result = self.db.execute(
                text(f"DELETE FROM {table_name} WHERE run_time < :cutoff"),
                {"cutoff": cutoff},
            )
            deleted = result.rowcount or 0
            deleted_total += deleted
            if deleted:
                logger.info("L1 清理: %s 删除 %s 条 (<%s)", table_name, deleted, cutoff.date())
        except Exception as exc:
            if "ORA-00942" in str(exc):
                logger.warning("L1 清理跳过不存在表: %s", table_name)
            else:
                logger.error("L1 清理 %s 失败: %s", table_name, exc, exc_info=True)
            self.db.rollback()

        # ExportAuditLog
        table_name = ExportAuditLog.__tablename__
        try:
            result = self.db.execute(
                text(f"DELETE FROM {table_name} WHERE export_time < :cutoff"),
                {"cutoff": cutoff},
            )
            deleted = result.rowcount or 0
            deleted_total += deleted
            if deleted:
                logger.info("L1 清理: %s 删除 %s 条 (<%s)", table_name, deleted, cutoff.date())
        except Exception as exc:
            if "ORA-00942" in str(exc):
                logger.warning("L1 清理跳过不存在表: %s", table_name)
            else:
                logger.error("L1 清理 %s 失败: %s", table_name, exc, exc_info=True)
            self.db.rollback()

        self.db.commit()
        return {"deleted": deleted_total, "cutoff": cutoff.isoformat()}

    def _cleanup_l2(self) -> dict:
        """L2: 清理超过保留期的审计维度结果和结论（保留 push_log 元数据但删除详细维度）"""
        cutoff = datetime.now() - timedelta(days=self.config.l2_days)
        deleted_total = 0

        push_table = PushLog.__tablename__
        dim_table = AuditDimensionResult.__tablename__
        conclusion_table = AuditConclusion.__tablename__

        # AuditDimensionResult
        try:
            result = self.db.execute(
                text(f"""
                    DELETE FROM {dim_table}
                    WHERE push_log_id IN (
                        SELECT id FROM {push_table} WHERE push_time < :cutoff
                    )
                """),
                {"cutoff": cutoff},
            )
            deleted = result.rowcount or 0
            deleted_total += deleted
            if deleted:
                logger.info("L2 清理: %s 删除 %s 条 (push_time<%s)", dim_table, deleted, cutoff.date())
        except Exception as exc:
            if "ORA-00942" in str(exc):
                logger.warning("L2 清理跳过不存在表: %s", dim_table)
            else:
                logger.error("L2 清理 %s 失败: %s", dim_table, exc, exc_info=True)
            self.db.rollback()

        # AuditConclusion
        try:
            result = self.db.execute(
                text(f"""
                    DELETE FROM {conclusion_table}
                    WHERE push_log_id IN (
                        SELECT id FROM {push_table} WHERE push_time < :cutoff
                    )
                """),
                {"cutoff": cutoff},
            )
            deleted = result.rowcount or 0
            deleted_total += deleted
            if deleted:
                logger.info("L2 清理: %s 删除 %s 条 (push_time<%s)", conclusion_table, deleted, cutoff.date())
        except Exception as exc:
            if "ORA-00942" in str(exc):
                logger.warning("L2 清理跳过不存在表: %s", conclusion_table)
            else:
                logger.error("L2 清理 %s 失败: %s", conclusion_table, exc, exc_info=True)
            self.db.rollback()

        self.db.commit()
        return {"deleted": deleted_total, "cutoff": cutoff.isoformat()}

    def _cleanup_l3(self) -> dict:
        """L3: 对超过保留期的 push_log 敏感字段进行脱敏/清空（mr_text, request_json, response_json）"""
        cutoff = datetime.now() - timedelta(days=self.config.l3_days)
        masked_total = 0
        dimension_masked = 0
        alert_masked = 0
        feedback_masked = 0
        qc_feedback_masked = 0
        oracle = _is_oracle_db()
        push_table = PushLog.__tablename__
        mask = _MASK_TEXT
        not_masked_mr = _sql_not_equal_text("mr_text", mask, oracle=oracle)

        # 1) PushLog 分批脱敏（独立事务边界，失败不阻断后续关联表）
        try:
            batch_size = self.config.batch_size
            while True:
                if oracle:
                    subquery = f"""
                        SELECT id FROM {push_table}
                        WHERE push_time < :cutoff
                          AND {not_masked_mr}
                          AND ROWNUM <= :batch_size
                    """
                else:
                    subquery = f"""
                        SELECT id FROM {push_table}
                        WHERE push_time < :cutoff
                          AND {not_masked_mr}
                        LIMIT :batch_size
                    """

                result = self.db.execute(
                    text(f"""
                        UPDATE {push_table}
                        SET mr_text = :mask,
                            request_json = :mask,
                            response_json = :mask,
                            parse_error = :mask
                        WHERE id IN ({subquery})
                    """),
                    {"cutoff": cutoff, "batch_size": batch_size, "mask": mask},
                )
                masked = result.rowcount or 0
                masked_total += masked
                self.db.commit()
                if masked < batch_size:
                    break

            if masked_total:
                logger.info("L3 清理: %s 脱敏 %s 条 (push_time<%s)", push_table, masked_total, cutoff.date())
        except Exception as exc:
            if "ORA-00942" in str(exc):
                logger.warning("L3 清理跳过不存在表: %s", push_table)
            else:
                logger.error("L3 清理 %s 失败: %s", push_table, exc, exc_info=True)
            self.db.rollback()

        # 2) 关联表：按表独立 try，避免一张表 CLOB 语法拖垮全部
        dim_table = AuditDimensionResult.__tablename__
        try:
            dim_pred = " OR ".join(
                [
                    _sql_not_equal_text("medical_content", mask, oracle=oracle),
                    _sql_not_equal_text("nursing_content", mask, oracle=oracle),
                    _sql_not_equal_text("medical_evidence_json", _MASK_JSON_ARR, oracle=oracle),
                    _sql_not_equal_text("nursing_evidence_json", _MASK_JSON_ARR, oracle=oracle),
                    _sql_not_equal_text("extra_json", _MASK_JSON_OBJ, oracle=oracle),
                ]
            )
            dim_result = self.db.execute(
                text(f"""
                UPDATE {dim_table}
                SET medical_content=:mask, nursing_content=:mask,
                    medical_evidence_json=:arr, nursing_evidence_json=:arr,
                    extra_json=:obj
                WHERE push_log_id IN (SELECT id FROM {push_table} WHERE push_time < :cutoff)
                  AND ({dim_pred})
            """),
                {"cutoff": cutoff, "mask": mask, "arr": _MASK_JSON_ARR, "obj": _MASK_JSON_OBJ},
            )
            dimension_masked = dim_result.rowcount or 0
            self.db.commit()
        except Exception as exc:
            logger.error("L3 清理维度表失败: %s", exc, exc_info=True)
            self.db.rollback()

        alert_table = QCRecordAlertLog.__tablename__
        try:
            alert_pred = " OR ".join(
                [
                    _sql_not_equal_text("payload_json", _MASK_JSON_OBJ, oracle=oracle),
                    _sql_not_equal_text("last_error", mask, oracle=oracle),
                ]
            )
            alert_result = self.db.execute(
                text(f"""
                UPDATE {alert_table}
                SET payload_json=:obj, last_error=:mask
                WHERE push_log_id IN (SELECT id FROM {push_table} WHERE push_time < :cutoff)
                  AND ({alert_pred})
            """),
                {"cutoff": cutoff, "mask": mask, "obj": _MASK_JSON_OBJ},
            )
            alert_masked = alert_result.rowcount or 0
            self.db.commit()
        except Exception as exc:
            logger.error("L3 清理告警表失败: %s", exc, exc_info=True)
            self.db.rollback()

        feedback_table = QCAlertFeedback.__tablename__
        try:
            fb_pred = " OR ".join(
                [
                    _sql_not_equal_text("reason", mask, oracle=oracle),
                    _sql_not_equal_text("rectification_text", mask, oracle=oracle),
                ]
            )
            feedback_result = self.db.execute(
                text(f"""
                UPDATE {feedback_table}
                SET reason=:mask, rectification_text=:mask
                WHERE push_log_id IN (SELECT id FROM {push_table} WHERE push_time < :cutoff)
                  AND ({fb_pred})
            """),
                {"cutoff": cutoff, "mask": mask},
            )
            feedback_masked = feedback_result.rowcount or 0
            self.db.commit()
        except Exception as exc:
            logger.error("L3 清理告警反馈表失败: %s", exc, exc_info=True)
            self.db.rollback()

        qc_feedback_table = QCFeedback.__tablename__
        try:
            qf_pred = " OR ".join(
                [
                    _sql_not_equal_text("feedback_text", mask, oracle=oracle),
                    _sql_not_equal_text("rectification_text", mask, oracle=oracle),
                ]
            )
            qc_feedback_result = self.db.execute(
                text(f"""
                UPDATE {qc_feedback_table}
                SET feedback_text=:mask, rectification_text=:mask
                WHERE push_log_id IN (SELECT id FROM {push_table} WHERE push_time < :cutoff)
                  AND ({qf_pred})
            """),
                {"cutoff": cutoff, "mask": mask},
            )
            qc_feedback_masked = qc_feedback_result.rowcount or 0
            self.db.commit()
        except Exception as exc:
            logger.error("L3 清理质控反馈表失败: %s", exc, exc_info=True)
            self.db.rollback()

        return {
            "masked": masked_total,
            "dimension_masked": dimension_masked,
            "alert_masked": alert_masked,
            "feedback_masked": feedback_masked,
            "qc_feedback_masked": qc_feedback_masked,
            "cutoff": cutoff.isoformat(),
        }


def run_retention_cleanup(db: Session, config_dict: Optional[dict] = None) -> dict:
    """便捷函数：执行一次数据留存清理"""
    cfg = RetentionConfig(config_dict)
    service = RetentionService(db, cfg)
    return service.run_cleanup()
