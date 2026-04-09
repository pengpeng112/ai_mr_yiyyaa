"""
推送执行器 —— 消除推送逻辑重复，统一处理批量推送
增强功能：结构化审计结果存储
"""
import logging
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from app.models import PushLog, AuditDimensionResult, AuditConclusion, QCFeedback
from app.dify_pusher import push_to_dify
from app.notifier import send_notification
from app.services.payload_builder import build_dify_payload, build_dify_mr_text
from app.services.record_identity import get_record_source_key

logger = logging.getLogger(__name__)


def _normalize_query_date_for_log(value: str) -> str:
    """标准化落库 query_date，兼容范围格式，避免超出 VARCHAR2(10)。"""
    text = str(value or "").strip()
    if not text:
        return ""

    # 范围格式：2026-01-01~2026-04-01 -> 取结束日期用于索引查询
    if "~" in text:
        parts = [p.strip() for p in text.split("~") if p.strip()]
        if parts:
            tail = parts[-1]
            if len(tail) >= 10:
                normalized = tail[:10]
                logger.debug("[push_log] normalize range query_date for db: raw=%s normalized=%s", text, normalized)
                return normalized

    # 普通格式或其他格式兜底截断
    normalized = text[:10]
    if normalized != text:
        logger.debug("[push_log] truncate query_date for db: raw=%s normalized=%s", text, normalized)
    return normalized


@dataclass
class PushResult:
    """推送结果数据类"""
    success: int = 0
    failed: int = 0
    total: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class PushConfig:
    """推送配置数据类"""
    trigger_type: str = "manual"  # auto | manual | retry
    query_date: str = ""
    interval_ms: int = 500
    max_retry: int = 3
    notify_enabled: bool = True


class PushExecutor:
    """
    推送执行器 —— 统一处理批量推送逻辑
    消除在 scheduler.py 和 push.py 中的重复代码
    """

    def __init__(self, dify_config: Dict[str, Any], notify_config: Dict[str, Any] = None,
                 field_mapping: Dict[str, str] = None):
        """
        初始化推送执行器

        Args:
            dify_config: Dify配置字典
            notify_config: 通知配置字典
            field_mapping: Oracle 字段映射配置
        """
        self.dify_config = dify_config
        self.notify_config = notify_config or {}
        self.field_mapping = field_mapping or {
            "patient_id": "患者ID",
            "visit_number": "次数",
            "patient_name": "患者姓名",
            "dept": "所在科室名称",
            "admission_no": "住院号",
        }

    def execute(
        self,
        db,
        grouped_records: Dict[str, List[Dict[str, Any]]],
        push_config: PushConfig
    ) -> PushResult:
        """
        执行批量推送

        Args:
            db: 数据库会话
            grouped_records: 按患者ID分组的记录字典
            push_config: 推送配置

        Returns:
            推送结果对象
        """
        start_time = time.time()
        result = PushResult(total=len(grouped_records))

        try:
            for patient_id, patient_records in grouped_records.items():
                try:
                    with db.begin_nested():
                        single_result = self._push_single_record(
                            db, patient_id, patient_records, push_config
                        )
                    result.results.append(single_result)

                    status = str(single_result.get("status", "failed"))
                    if status == "success":
                        result.success += 1
                    elif status == "skipped":
                        pass
                    else:
                        result.failed += 1

                    # 间隔控制，避免请求过快
                    time.sleep(push_config.interval_ms / 1000)

                except Exception as e:
                    logger.error(f"推送患者 {patient_id} 时发生异常: {e}", exc_info=True)
                    result.failed += 1
                    result.results.append({
                        "patient_id": patient_id,
                        "status": "error",
                        "error": str(e)
                    })

            # 提交数据库事务（与后续逻辑严格分离）
            try:
                db.commit()
            except Exception as commit_error:
                logger.error("批量推送数据库提交失败: %s", commit_error, exc_info=True)
                db.rollback()
                raise
            logger.info(f"批量推送完成: 总数={result.total}, 成功={result.success}, 失败={result.failed}")

        except Exception as e:
            logger.error(f"批量推送过程中发生严重错误: {e}", exc_info=True)
            db.rollback()
            raise

        result.duration_seconds = time.time() - start_time
        return result

    def _push_single_record(
        self,
        db,
        patient_id: str,
        patient_records: List[Dict[str, Any]],
        push_config: PushConfig
    ) -> Dict[str, Any]:
        """
        推送单条患者记录

        Args:
            db: 数据库会话
            patient_id: 患者ID（可能是 "患者ID_次数" 格式）
            patient_records: 患者记录列表
            push_config: 推送配置

        Returns:
            单条推送结果字典
        """
        # 构建结构化推送 payload
        payload = build_dify_payload(patient_records, self.field_mapping, push_config.query_date)
        mr_text = build_dify_mr_text(patient_records, self.field_mapping, push_config.query_date)

        # 提取真实患者ID（去掉 _次数 后缀）
        real_patient_id = patient_id.split("_")[0] if "_" in patient_id else patient_id
        if not patient_records:
            raise ValueError(f"patient_records is empty: patient_id={patient_id}")
        first_record = patient_records[0]
        visit_number = str(first_record.get(self.field_mapping.get("visit_number", "次数"), "") or "")

        skip_reason, skip_message = self._get_skip_reason(db, real_patient_id, visit_number)
        if skip_reason:
            # 跳过推送不落库，仅返回执行结果
            return {
                "patient_id": real_patient_id,
                "status": "skipped",
                "inconsistency": False,
                "severity": "",
                "workflow_run_id": "",
                "elapsed_ms": 0,
                "error": skip_message,
                "skip_reason": skip_reason,
            }

        # 推送到Dify：主输入变量必须是字符串；结构化 payload 仅用于本地留存与结果覆盖
        dify_input = mr_text or json.dumps(payload, ensure_ascii=False)
        dify_result = push_to_dify(dify_input, self.dify_config, real_patient_id)
        self._enforce_authoritative_patient_fields(
            dify_result=dify_result,
            payload=payload,
            patient_records=patient_records,
            query_date=push_config.query_date,
            patient_id=real_patient_id,
        )

        # 创建推送日志及结构化审计数据
        log = self._create_push_log(
            patient_id, patient_records, dify_result,
            payload, mr_text, push_config
        )
        db.add(log)
        db.flush()  # 获取 log.id

        # 存储结构化审计结果
        self._save_audit_results(db, log.id, dify_result)

        # 发送通知（如果检测到不一致）
        if dify_result.get("inconsistency") and push_config.notify_enabled:
            try:
                send_notification(real_patient_id, dify_result, self.notify_config)
            except Exception as e:
                logger.error(f"发送患者 {real_patient_id} 的通知失败: {e}", exc_info=True)

        return {
            "patient_id": real_patient_id,
            "status": dify_result.get("status", "failed"),
            "inconsistency": dify_result.get("inconsistency", False),
            "severity": dify_result.get("severity", ""),
            "workflow_run_id": dify_result.get("workflow_run_id", ""),
            "elapsed_ms": dify_result.get("elapsed_ms", 0),
        }

    def _enforce_authoritative_patient_fields(
        self,
        dify_result: Dict[str, Any],
        payload: Dict[str, Any],
        patient_records: List[Dict[str, Any]],
        query_date: str,
        patient_id: str,
    ) -> None:
        """使用上游结构化数据覆盖 parsed_output 的患者基础信息，避免依赖 LLM 生成。"""
        parsed = dify_result.get("parsed_output")
        if not isinstance(parsed, dict):
            return

        patient_info = payload.get("patient_info", {}) if isinstance(payload, dict) else {}
        first_record = patient_records[0] if patient_records else {}
        fm = self.field_mapping

        authoritative_patient_id = str(patient_info.get("patient_id") or patient_id or "")
        authoritative_visit_number = str(patient_info.get("visit_number") or first_record.get(fm.get("visit_number", "次数"), "") or "")
        authoritative_patient_name = str(patient_info.get("patient_name") or first_record.get(fm.get("patient_name", "患者姓名"), "") or "")
        authoritative_dept = str(patient_info.get("department") or first_record.get(fm.get("dept", "所在科室名称"), "") or "")
        authoritative_audit_date = str(payload.get("audit_date") or query_date or "")

        parsed["patient_id"] = authoritative_patient_id
        parsed["visit_number"] = authoritative_visit_number
        parsed["patient_name"] = authoritative_patient_name
        parsed["dept"] = authoritative_dept
        parsed["audit_date"] = authoritative_audit_date

    def _get_skip_reason(self, db, patient_id: str, visit_number: str) -> tuple[str, str]:
        unreviewed = (
            db.query(PushLog.id)
            .filter(PushLog.patient_id == patient_id)
            .filter(PushLog.pushed_flag == 1)
            .filter(PushLog.reviewed_flag == 0)
            .filter(PushLog.manual_override == 0)
        )
        if visit_number:
            unreviewed = unreviewed.filter(PushLog.visit_number == visit_number)
        if unreviewed.first() is not None:
            return "unreviewed_pending", "该患者已推送但尚未人工复核，已按规则跳过"

        query = (
            db.query(QCFeedback)
            .join(PushLog, QCFeedback.push_log_id == PushLog.id)
            .filter(QCFeedback.suppress_ai_push == True)
            .filter(QCFeedback.status == "rectified")
            .filter(PushLog.patient_id == patient_id)
        )
        if visit_number:
            query = query.filter(PushLog.visit_number == visit_number)
        if query.with_entities(QCFeedback.id).first() is not None:
            return "rectified_suppressed", "该患者已完成整改，已停止后续 AI 推送"
        return "", ""

    def _should_skip_patient(self, db, patient_id: str, visit_number: str) -> bool:
        reason, _ = self._get_skip_reason(db, patient_id, visit_number)
        return bool(reason)

    def _create_skipped_push_log(
        self,
        patient_id: str,
        patient_records: List[Dict[str, Any]],
        push_config: PushConfig,
        skip_reason: str,
        skip_message: str,
    ) -> PushLog:
        first_record = patient_records[0]
        fm = self.field_mapping
        real_patient_id = patient_id.split("_")[0] if "_" in patient_id else patient_id
        source_record_key = get_record_source_key(first_record)
        return PushLog(
            push_time=datetime.now(),
            trigger_type=push_config.trigger_type,
            query_date=_normalize_query_date_for_log(push_config.query_date),
            patient_id=real_patient_id,
            patient_name=first_record.get(fm.get("patient_name", "患者姓名"), ""),
            admission_no=str(first_record.get(fm.get("admission_no", "住院号"), "")),
            visit_number=str(first_record.get(fm.get("visit_number", "次数"), "")),
            source_record_key=source_record_key,
            dept=first_record.get(fm.get("dept", "所在科室名称"), ""),
            status="skipped",
            pushed_flag=1,
            reviewed_flag=0,
            manual_override=0,
            skip_reason=skip_reason,
            error_msg=skip_message,
            elapsed_ms=0,
            mr_text="",
            request_json="",
            response_json="",
            parse_status="skipped",
            parse_error="",
            risk_score=0,
            ai_version="1.0",
        )

    def _create_push_log(
        self,
        patient_id: str,
        patient_records: List[Dict[str, Any]],
        dify_result: Dict[str, Any],
        payload: Dict[str, Any],
        mr_text: str,
        push_config: PushConfig
    ) -> PushLog:
        """
        创建推送日志记录

        Args:
            patient_id: 患者ID
            patient_records: 患者记录列表
            dify_result: Dify推送结果
            payload: 推送的结构化 JSON
            push_config: 推送配置

        Returns:
            PushLog对象
        """
        first_record = patient_records[0]
        fm = self.field_mapping

        # 提取真实患者ID
        real_patient_id = patient_id.split("_")[0] if "_" in patient_id else patient_id
        source_record_key = get_record_source_key(first_record)

        parsed_output = dify_result.get("parsed_output", {}) or {}
        if parsed_output.get("parse_success"):
            parse_status = "success"
        elif parsed_output.get("fallback_inference"):
            parse_status = "fallback"
        else:
            parse_status = "failed"

        return PushLog(
            push_time=datetime.now(),
            trigger_type=push_config.trigger_type,
            query_date=_normalize_query_date_for_log(push_config.query_date),
            patient_id=real_patient_id,
            patient_name=first_record.get(fm.get("patient_name", "患者姓名"), ""),
            admission_no=str(first_record.get(fm.get("admission_no", "住院号"), "")),
            visit_number=str(first_record.get(fm.get("visit_number", "次数"), "")),
            source_record_key=source_record_key,
            dept=first_record.get(fm.get("dept", "所在科室名称"), ""),
            workflow_run_id=dify_result.get("workflow_run_id", ""),
            task_id=dify_result.get("task_id", ""),
            status=dify_result.get("status", "failed"),
            pushed_flag=1 if dify_result.get("status") == "success" else 0,
            reviewed_flag=0,
            manual_override=0,
            skip_reason="",
            ai_result=json.dumps(dify_result.get("result", {}), ensure_ascii=False),
            inconsistency=1 if dify_result.get("inconsistency") else 0,
            severity=dify_result.get("severity", ""),
            error_msg=dify_result.get("error", ""),
            elapsed_ms=dify_result.get("elapsed_ms", 0),
            mr_text=mr_text,
            request_json=json.dumps(payload, ensure_ascii=False),
            response_json=json.dumps(dify_result.get("result", {}), ensure_ascii=False),
            parse_status=parse_status,
            parse_error=dify_result.get("parse_error", ""),
            risk_score=dify_result.get("risk_score", 0),
            ai_version=parsed_output.get("version", "1.0"),
            alert_level=parsed_output.get("alert_level", ""),
        )

    def _save_audit_results(self, db, push_log_id: int, dify_result: Dict[str, Any]):
        """
        将结构化审计结果存入数据库

        Args:
            db: 数据库会话
            push_log_id: PushLog 的 ID
            dify_result: Dify 推送结果（包含 parsed_output）
        """
        parsed = dify_result.get("parsed_output", {})
        if not parsed:
            return

        parse_success = parsed.get("parse_success", False)
        fallback_inference = parsed.get("fallback_inference", False)
        should_save_summary = parse_success or fallback_inference or parsed.get("inconsistency")
        if not should_save_summary:
            return

        # 保存各维度结果
        for dim in parsed.get("dimensions", []) if parse_success else []:
            db.add(AuditDimensionResult(
                push_log_id=push_log_id,
                dimension_code=dim.get("dimension_code", ""),
                dimension=dim.get("dimension", ""),
                status=dim.get("status", "❓"),
                severity=dim.get("severity", ""),
                confidence=dim.get("confidence", 0),
                medical_content=dim.get("medical_content", ""),
                nursing_content=dim.get("nursing_content", ""),
                explanation=dim.get("explanation", ""),
                issue_summary=dim.get("issue_summary", ""),
                recommendation=dim.get("recommendation", ""),
                medical_evidence_json=json.dumps(dim.get("medical_evidence", []), ensure_ascii=False),
                nursing_evidence_json=json.dumps(dim.get("nursing_evidence", []), ensure_ascii=False),
                alert_level=dim.get("alert_level", ""),
                closure_hours=dim.get("closure_hours", 0),
                push_strategy=dim.get("push_strategy", ""),
                outcome_bucket=dim.get("outcome_bucket", ""),
            ))

        # 保存总体结论；fallback 模式下至少保留一条总结，避免通知与落库不一致
        focus_items = parsed.get("focus_items", [])
        overall_conclusion = parsed.get("overall_conclusion", "")
        reasoning_brief = parsed.get("reasoning_brief", "")
        if fallback_inference and not overall_conclusion:
            overall_conclusion = "Dify 输出解析失败，已按关键词回退判断处理。"
        if fallback_inference and not reasoning_brief:
            reasoning_brief = overall_conclusion

        db.add(AuditConclusion(
            push_log_id=push_log_id,
            has_inconsistency=1 if parsed.get("inconsistency") else 0,
            severity=parsed.get("severity", ""),
            risk_score=parsed.get("risk_score", 0),
            overall_conclusion=overall_conclusion,
            focus_items=json.dumps(focus_items, ensure_ascii=False) if focus_items else "[]",
            audit_date=parsed.get("audit_date", ""),
            reasoning_brief=reasoning_brief,
            ai_version=parsed.get("version", "1.0"),
            alert_level=parsed.get("alert_level", ""),
            closure_hours=parsed.get("closure_hours", 0),
            push_strategy=parsed.get("push_strategy", ""),
            outcome_bucket=parsed.get("outcome_bucket", ""),
            overall_qc_summary=parsed.get("overall_qc_summary", ""),
        ))

    def _clear_audit_results(self, db, push_log_id: int):
        """清除旧的结构化审计结果（重推前调用）"""
        db.query(AuditDimensionResult).filter(
            AuditDimensionResult.push_log_id == push_log_id
        ).delete()
        db.query(AuditConclusion).filter(
            AuditConclusion.push_log_id == push_log_id
        ).delete()

    def execute_retry(
        self,
        db,
        log_ids: List[int],
        max_retry: int = 3
    ) -> List[Dict[str, Any]]:
        """
        批量重推失败的记录

        Args:
            db: 数据库会话
            log_ids: 需要重推的日志ID列表
            max_retry: 最大重试次数

        Returns:
            重推结果列表
        """
        results = []

        for log_id in log_ids:
            try:
                with db.begin_nested():
                    log = db.query(PushLog).filter(PushLog.id == log_id).first()

                    if not log:
                        results.append({"log_id": log_id, "status": "not_found"})
                        continue

                    if log.retry_count >= max_retry:
                        results.append({"log_id": log_id, "status": "max_retry_exceeded"})
                        continue

                    skip_reason, skip_message = self._get_skip_reason(db, log.patient_id, log.visit_number or "")
                    if skip_reason:
                        results.append({
                            "log_id": log_id,
                            "status": "skipped",
                            "skip_reason": skip_reason,
                            "retry_count": log.retry_count,
                        })
                        continue

                    request_json = log.request_json or ""
                    if not request_json and not log.mr_text:
                        results.append({"log_id": log_id, "status": "no_request_payload"})
                        continue

                    if request_json:
                        try:
                            payload = json.loads(request_json)
                        except json.JSONDecodeError:
                            logger.warning("重推日志 %s 的 request_json 解析失败，回退使用 mr_text", log_id)
                            payload = log.mr_text
                    else:
                        payload = log.mr_text

                    # 推送到Dify
                    dify_input = log.mr_text or (
                        json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload or "")
                    )
                    dify_result = push_to_dify(dify_input, self.dify_config, log.patient_id)

                    # 更新日志
                    log.status = dify_result.get("status", "failed")
                    log.workflow_run_id = dify_result.get("workflow_run_id", "")
                    log.task_id = dify_result.get("task_id", "")
                    log.ai_result = json.dumps(dify_result.get("result", {}), ensure_ascii=False)
                    log.response_json = json.dumps(dify_result.get("result", {}), ensure_ascii=False)
                    log.inconsistency = 1 if dify_result.get("inconsistency") else 0
                    log.severity = dify_result.get("severity", "")
                    log.error_msg = dify_result.get("error", "")
                    log.elapsed_ms = dify_result.get("elapsed_ms", 0)
                    parsed_output = dify_result.get("parsed_output", {}) or {}
                    if parsed_output.get("parse_success"):
                        log.parse_status = "success"
                    elif parsed_output.get("fallback_inference"):
                        log.parse_status = "fallback"
                    else:
                        log.parse_status = "failed"
                    log.parse_error = dify_result.get("parse_error", "")
                    log.risk_score = dify_result.get("risk_score", 0)
                    log.ai_version = parsed_output.get("version", "1.0")
                    log.alert_level = parsed_output.get("alert_level", "")
                    log.retry_count += 1
                    log.push_time = datetime.now()
                    log.trigger_type = "retry"

                    # 清除旧的审计结果，保存新的
                    self._clear_audit_results(db, log_id)
                    self._save_audit_results(db, log_id, dify_result)

                    # 发送通知（如果检测到不一致）
                    if dify_result.get("inconsistency"):
                        try:
                            send_notification(log.patient_id, dify_result, self.notify_config)
                        except Exception as e:
                            logger.error(f"发送重推通知失败: {e}", exc_info=True)

                    results.append({
                        "log_id": log_id,
                        "status": dify_result.get("status"),
                        "retry_count": log.retry_count
                    })

                    time.sleep(self.dify_config.get("interval_ms", 500) / 1000)

            except Exception as e:
                logger.error(f"重推日志 ID {log_id} 失败: {e}", exc_info=True)
                results.append({
                    "log_id": log_id,
                    "status": "error",
                    "error": str(e)
                })

        try:
            db.commit()
        except Exception as e:
            logger.error(f"重推批量提交失败，执行回滚: {e}", exc_info=True)
            db.rollback()
            raise
        return results
