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
from app.services.payload_composer import compose
from app.services.audit_result_mapper import map_conclusion_row, map_dimension_row
from app.services.data_source_loader import PatientBundle
from app.services.push_types import PushResult, PushConfig, safe_json_dumps as _safe_json_dumps, normalize_query_date_for_log as _normalize_query_date_for_log

logger = logging.getLogger(__name__)

from app.services.record_identity import get_bundle_source_key

from app.services.push_skip_policy import (
    get_empty_lab_exam_skip_reason as _get_empty_lab_exam_skip_reason_impl,
    get_skip_reason as _get_skip_reason_impl,
    should_skip_patient as _should_skip_patient_impl,
    apply_audit_type_scope as _apply_audit_type_scope_impl,
)
from app.services.push_log_writer import (
    create_skipped_push_log as _create_skipped_push_log_impl,
    create_push_log as _create_push_log_impl,
)
from app.services.audit_result_writer import (
    save_audit_results as _save_audit_results_impl,
    clear_audit_results as _clear_audit_results_impl,
)

MR_TYPE_BY_AUDIT_CODE = {
    "progress_vs_nursing": "医嘱与病程及护理核查",
    "lab_exam_vs_progress_nursing": "检验检查与病历护理核查",
    "frontpage_surgery_diagnosis_vs_first_progress": "首页手术与首次病程",
    "orders_vs_progress": "医嘱与病程及护理核查",
}

MR_TYPE_BY_BUILDER = {
    "legacy_progress_nursing": "医嘱与病程及护理核查",
    "lab_exam_progress_nursing": "检验检查与病历护理核查",
    "lab_exam_structured_progress_nursing": "检验检查与病历护理核查",
    "frontpage_surgery_first_progress": "首页手术与首次病程",
    "orders_progress_stub": "医嘱与病程及护理核查",
}


def _audit_type_get(audit_type: Any, key: str, default: Any = None) -> Any:
    if not audit_type:
        return default
    if hasattr(audit_type, key):
        return getattr(audit_type, key)
    if isinstance(audit_type, dict):
        return audit_type.get(key, default)
    return default


def resolve_mr_type(audit_type: Any) -> str:
    """根据审计类型推导 Dify 下拉参数 mr_type 的值。"""
    if not audit_type:
        return ""

    dify_cfg = _audit_type_get(audit_type, "dify", {}) or {}
    if hasattr(dify_cfg, "model_dump"):
        dify_cfg = dify_cfg.model_dump()
    extra_inputs = dict(dify_cfg.get("extra_inputs", {}) or {}) if isinstance(dify_cfg, dict) else {}
    configured = str(extra_inputs.get("mr_type") or "").strip()
    if configured:
        return configured

    payload_cfg = _audit_type_get(audit_type, "payload", {}) or {}
    builder = str(payload_cfg.get("builder") or "").strip() if isinstance(payload_cfg, dict) else ""
    if builder in MR_TYPE_BY_BUILDER:
        return MR_TYPE_BY_BUILDER[builder]

    code = str(_audit_type_get(audit_type, "code", "") or "").strip()
    if code in MR_TYPE_BY_AUDIT_CODE:
        return MR_TYPE_BY_AUDIT_CODE[code]

    name = str(_audit_type_get(audit_type, "name", "") or "").strip()
    if "检验" in name and "检查" in name:
        return "检验检查与病历护理核查"
    if "首页" in name and "首次病程" in name:
        return "首页手术与首次病程"
    if "医嘱" in name:
        return "医嘱与病程及护理核查"
    return ""


def _configured_audit_type_mr_type(audit_type: Any) -> str:
    """返回审计类型配置中显式维护的 mr_type。"""
    if not audit_type:
        return ""
    dify_cfg = _audit_type_get(audit_type, "dify", {}) or {}
    if hasattr(dify_cfg, "model_dump"):
        dify_cfg = dify_cfg.model_dump()
    extra_inputs = dict(dify_cfg.get("extra_inputs", {}) or {}) if isinstance(dify_cfg, dict) else {}
    return str(extra_inputs.get("mr_type") or "").strip()


def with_audit_type_mr_type(dify_cfg: Dict[str, Any] | None, audit_type: Any) -> Dict[str, Any]:
    """向 Dify extra_inputs 注入 mr_type；已有配置优先，避免覆盖人工配置。"""
    cfg = dict(dify_cfg or {})
    configured_mr_type = _configured_audit_type_mr_type(audit_type)
    mr_type = configured_mr_type or resolve_mr_type(audit_type)
    if not mr_type:
        return cfg
    extra_inputs = dict(cfg.get("extra_inputs", {}) or {}) if isinstance(cfg.get("extra_inputs", {}), dict) else {}
    if configured_mr_type or not str(extra_inputs.get("mr_type") or "").strip():
        extra_inputs["mr_type"] = mr_type
    cfg["extra_inputs"] = extra_inputs
    return cfg


# PushResult, PushConfig 已迁移到 push_types.py，此处保留兼容别名
from app.services.push_types import PushResult, PushConfig  # noqa: E402, F811


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
                        result.skipped += 1
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

            # 主事务提交后，发送待推送的前置机告警
            try:
                from app.services.relay_alert_service import RelayAlertService as _RAS
                from app.config import load_config as _lcfg
                _relay_svc = _RAS(db, _lcfg())
                _relay_result = _relay_svc.dispatch_pending()
                if _relay_result.get("sent") or _relay_result.get("failed"):
                    logger.info("relay_alert dispatch: %s", _relay_result)
            except Exception as _relay_exc:
                logger.error("relay_alert dispatch failed: %s", _relay_exc, exc_info=True)

            logger.info(f"批量推送完成: 总数={result.total}, 成功={result.success}, 失败={result.failed}, 跳过={result.skipped}")

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
        patient_records: List[Dict[str, Any]] | PatientBundle,
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
        bundle, payload, mr_text, real_patient_id, visit_number, bundle_records = self._build_payload_and_mr_text(
            patient_id,
            patient_records,
            push_config,
        )

        # 获取 source_record_key 用于精确匹配
        audit_type = push_config.audit_type
        source_record_key = get_bundle_source_key(bundle, audit_type, push_config.audit_run_mode) if audit_type else ""

        skip_reason, skip_message = self._get_skip_reason(
            db,
            real_patient_id,
            visit_number,
            push_config.audit_type_code,
            source_record_key,
            push_config.audit_run_mode,
        )
        if skip_reason:
            db.add(
                self._create_skipped_push_log(
                    patient_id=patient_id,
                    patient_records=patient_records,
                    push_config=push_config,
                    skip_reason=skip_reason,
                    skip_message=skip_message,
                )
            )
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

        lab_exam_skip = self._get_empty_lab_exam_skip_reason(payload)
        if lab_exam_skip:
            db.add(
                self._create_skipped_push_log(
                    patient_id=patient_id,
                    patient_records=patient_records,
                    push_config=push_config,
                    skip_reason="empty_lab_exam",
                    skip_message=lab_exam_skip,
                )
            )
            return {
                "patient_id": real_patient_id,
                "status": "skipped",
                "inconsistency": False,
                "severity": "",
                "workflow_run_id": "",
                "elapsed_ms": 0,
                "error": lab_exam_skip,
                "skip_reason": "empty_lab_exam",
            }

        # 推送到Dify：主输入变量必须是字符串；结构化 payload 仅用于本地留存与结果覆盖
        dify_input = mr_text or _safe_json_dumps(payload)
        audit_type = push_config.audit_type
        response_cfg = (audit_type.response or {}) if audit_type else {}
        parse_strategy = str(response_cfg.get("parse_strategy") or "hybrid")
        dify_override = self._build_dify_override(audit_type)
        dify_result = push_to_dify(
            dify_input,
            self.dify_config,
            real_patient_id,
            dify_config_override=dify_override,
            response_paths=response_cfg,
            parse_strategy=parse_strategy,
        )
        self._enforce_authoritative_patient_fields(
            dify_result=dify_result,
            payload=payload,
            patient_records=bundle_records,
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
        if parse_strategy in {"hybrid", "dimensions_only"}:
            self._save_audit_results(db, log.id, dify_result, str(push_config.audit_type_code or ""))

        # 高危问题推送到前置机（只 enqueue，dispatch 在主事务提交后执行）
        try:
            from app.services.relay_alert_service import RelayAlertService
            from app.config import load_config as _load_cfg
            _relay_svc = RelayAlertService(db, _load_cfg())
            _relay_svc.enqueue_high_severity_alerts(log.id)
        except Exception as _relay_exc:
            logger.error("relay_alert enqueue failed: patient_id=%s err=%s", real_patient_id, _relay_exc, exc_info=True)

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

    @staticmethod
    def _get_empty_lab_exam_skip_reason(payload: Dict[str, Any]) -> str:
        return _get_empty_lab_exam_skip_reason_impl(payload)

    def _build_dify_override(self, audit_type) -> Dict[str, Any] | None:
        if not audit_type:
            return None
        if hasattr(audit_type, "dify"):
            dify_cfg = audit_type.dify.model_dump() if hasattr(audit_type.dify, "model_dump") else dict(audit_type.dify or {})
        else:
            dify_cfg = dict(audit_type.get("dify", {}) or {})
        api_key = str(dify_cfg.get("api_key") or "").strip()
        if not api_key and str(dify_cfg.get("api_key_enc") or "").strip():
            try:
                from app.config import decrypt_value

                api_key = decrypt_value(str(dify_cfg.get("api_key_enc") or ""))
            except Exception:
                api_key = ""
        dify_cfg["api_key"] = api_key or self.dify_config.get("api_key", "")
        return with_audit_type_mr_type(dify_cfg, audit_type)

    def _ensure_bundle(
        self,
        patient_id: str,
        patient_records: List[Dict[str, Any]] | PatientBundle,
        push_config: PushConfig,
    ) -> PatientBundle:
        if isinstance(patient_records, PatientBundle):
            return patient_records

        if not patient_records:
            raise ValueError(f"patient_records is empty: patient_id={patient_id}")
        first_record = patient_records[0]
        group_values = {
            "patient_id": str(first_record.get(self.field_mapping.get("patient_id", "患者ID"), "") or ""),
            "visit_number": str(first_record.get(self.field_mapping.get("visit_number", "次数"), "") or ""),
        }
        return PatientBundle(
            bundle_id=str(patient_id),
            group_values=group_values,
            sources={"primary": patient_records},
            source_field_mappings={"primary": dict(self.field_mapping or {})},
            primary_source="primary",
            query_date=push_config.query_date,
        )

    def _extract_bundle_records(self, bundle: PatientBundle) -> List[Dict[str, Any]]:
        return bundle.sources.get(bundle.primary_source) or next(iter(bundle.sources.values()), [])

    def _build_payload_and_mr_text(
        self,
        patient_id: str,
        patient_records: List[Dict[str, Any]] | PatientBundle,
        push_config: PushConfig,
    ) -> tuple[PatientBundle, Dict[str, Any], str, str, str, List[Dict[str, Any]]]:
        bundle = self._ensure_bundle(patient_id, patient_records, push_config)
        bundle_records = self._extract_bundle_records(bundle)
        if not bundle_records:
            raise ValueError(f"patient_records is empty: patient_id={patient_id}")

        audit_type = push_config.audit_type
        if audit_type:
            payload, mr_text = compose(audit_type, bundle, push_config.query_date)
        else:
            payload = build_dify_payload(bundle_records, self.field_mapping, push_config.query_date)
            mr_text = build_dify_mr_text(bundle_records, self.field_mapping, push_config.query_date)

        fallback_patient_id = patient_id.split("_")[0] if "_" in patient_id else patient_id
        real_patient_id = str(bundle.group_values.get("patient_id") or fallback_patient_id or "")
        visit_number = str(bundle.group_values.get("visit_number") or bundle_records[0].get(self.field_mapping.get("visit_number", "次数"), "") or "")
        return bundle, payload, mr_text, real_patient_id, visit_number, bundle_records

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
        authoritative_dept = str(patient_info.get("department") or patient_info.get("dept") or first_record.get(fm.get("dept", "所在科室名称"), "") or "")
        authoritative_audit_date = str(payload.get("audit_date") or query_date or "")

        parsed["patient_id"] = authoritative_patient_id
        parsed["visit_number"] = authoritative_visit_number
        parsed["patient_name"] = authoritative_patient_name
        parsed["dept"] = authoritative_dept
        parsed["audit_date"] = authoritative_audit_date

    def _apply_audit_type_scope(self, query, audit_type_code: str):
        return _apply_audit_type_scope_impl(query, audit_type_code)

    def _get_skip_reason(
        self,
        db,
        patient_id: str,
        visit_number: str,
        audit_type_code: str = "progress_vs_nursing",
        source_record_key: str = "",
        audit_run_mode: str = "daily_increment",
    ) -> tuple[str, str]:
        return _get_skip_reason_impl(db, patient_id, visit_number, audit_type_code, source_record_key, audit_run_mode)

    def _should_skip_patient(
        self,
        db,
        patient_id: str,
        visit_number: str,
        audit_type_code: str = "progress_vs_nursing",
        source_record_key: str = "",
        audit_run_mode: str = "daily_increment",
    ) -> bool:
        return _should_skip_patient_impl(db, patient_id, visit_number, audit_type_code, source_record_key, audit_run_mode)

    def _create_skipped_push_log(
        self,
        patient_id: str,
        patient_records: List[Dict[str, Any]] | PatientBundle,
        push_config: PushConfig,
        skip_reason: str,
        skip_message: str,
    ) -> PushLog:
        bundle = self._ensure_bundle(patient_id, patient_records, push_config)
        bundle_records = self._extract_bundle_records(bundle)
        return _create_skipped_push_log_impl(
            bundle=bundle,
            bundle_records=bundle_records,
            field_mapping=self.field_mapping,
            push_config=push_config,
            skip_reason=skip_reason,
            skip_message=skip_message,
            patient_id=patient_id,
        )

    def _create_push_log(
        self,
        patient_id: str,
        patient_records: List[Dict[str, Any]] | PatientBundle,
        dify_result: Dict[str, Any],
        payload: Dict[str, Any],
        mr_text: str,
        push_config: PushConfig
    ) -> PushLog:
        bundle = self._ensure_bundle(patient_id, patient_records, push_config)
        bundle_records = self._extract_bundle_records(bundle)
        return _create_push_log_impl(
            bundle=bundle,
            bundle_records=bundle_records,
            field_mapping=self.field_mapping,
            dify_result=dify_result,
            payload=payload,
            mr_text=mr_text,
            push_config=push_config,
            patient_id=patient_id,
        )

    def _save_audit_results(self, db, push_log_id: int, dify_result: Dict[str, Any], audit_type_code: str = ""):
        _save_audit_results_impl(db, push_log_id, dify_result, audit_type_code)

    def _clear_audit_results(self, db, push_log_id: int):
        _clear_audit_results_impl(db, push_log_id)

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
        registry = AuditTypeRegistry()

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

                    skip_reason, skip_message = self._get_skip_reason(
                        db,
                        log.patient_id,
                        log.visit_number or "",
                        getattr(log, "audit_type_code", "") or "progress_vs_nursing",
                        getattr(log, "source_record_key", "") or "",
                    )
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
                    audit_type = registry.get_or_default(getattr(log, "audit_type_code", "") or "")
                    response_cfg = audit_type.response or {}
                    parse_strategy = str(response_cfg.get("parse_strategy") or "hybrid")
                    dify_result = push_to_dify(
                        dify_input,
                        self.dify_config,
                        log.patient_id,
                        dify_config_override=self._build_dify_override(audit_type),
                        response_paths=response_cfg,
                        parse_strategy=parse_strategy,
                    )

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
                    log.audit_type_code = audit_type.code

                    # 清除旧的审计结果，保存新的
                    self._clear_audit_results(db, log_id)
                    if parse_strategy in {"hybrid", "dimensions_only"}:
                        self._save_audit_results(db, log_id, dify_result, str(audit_type.code or ""))

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
