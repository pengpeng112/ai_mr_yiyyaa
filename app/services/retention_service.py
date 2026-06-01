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
from app.models import PushLog, AuditDimensionResult, AuditConclusion, NotifyLog, SchedulerHistory, ExportAuditLog

logger = logging.getLogger(__name__)


class RetentionConfig:
    """数据留存配置"""

    def __init__(self, cfg: Optional[dict] = None):
        raw = cfg or {}
        self.enabled = bool(raw.get("enabled", True))
        self.l1_days = int(raw.get("l1_log_meta_days", 90))
        self.l2_days = int(raw.get("l2_audit_summary_days", 365))
        self.l3_days = int(raw.get("l3_sensitive_content_days", 30))
        self.batch_size = int(raw.get("cleanup_batch_size", 500))


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
        app_db_type = get_app_db_type()
        push_table = PushLog.__tablename__

        try:
            # 分批更新，避免一次性更新过多记录
            batch_size = self.config.batch_size
            while True:
                # Oracle 不支持 LIMIT，使用 ROWNUM
                if app_db_type == "oracle":
                    subquery = f"""
                        SELECT id FROM {push_table}
                        WHERE push_time < :cutoff
                          AND mr_text != '[已清理]'
                          AND ROWNUM <= :batch_size
                    """
                else:
                    subquery = f"""
                        SELECT id FROM {push_table}
                        WHERE push_time < :cutoff
                          AND mr_text != '[已清理]'
                        LIMIT :batch_size
                    """

                result = self.db.execute(
                    text(f"""
                        UPDATE {push_table}
                        SET mr_text = '[已清理]',
                            request_json = '[已清理]',
                            response_json = '[已清理]',
                            parse_error = '[已清理]'
                        WHERE id IN ({subquery})
                    """),
                    {"cutoff": cutoff, "batch_size": batch_size},
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

        return {"masked": masked_total, "cutoff": cutoff.isoformat()}


def run_retention_cleanup(db: Session, config_dict: Optional[dict] = None) -> dict:
    """便捷函数：执行一次数据留存清理"""
    cfg = RetentionConfig(config_dict)
    service = RetentionService(db, cfg)
    return service.run_cleanup()
