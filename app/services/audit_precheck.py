"""审计类型预检与汇总服务。"""
from __future__ import annotations

import logging
from typing import Any

from app.services.data_source_loader import PatientBundle

logger = logging.getLogger(__name__)

SKIP_REASON_LABELS = {
    "empty_lab_exam": "检验检查数据为空",
    "empty_progress_nursing": "病程护理记录为空",
    "empty_both_sides": "检验检查和病程护理均为空",
    "empty_primary": "主数据源为空",
    "empty_frontpage": "首页/手术数据为空",
}


def _get_builder(audit_type) -> str:
    """提取 builder 名称。"""
    payload = audit_type.payload if hasattr(audit_type, "payload") else {}
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    return str((payload or {}).get("builder") or "").strip()


def _check_lab_exam_bundle(bundle: PatientBundle) -> str:
    """lab_exam_progress_nursing / lab_exam_structured_progress_nursing 的跳过判断。"""
    sources = getattr(bundle, "sources", {}) or {}
    has_lab_or_exam = bool(sources.get("lab")) or bool(sources.get("exam"))
    has_progress_or_nursing = bool(sources.get("progress")) or bool(sources.get("nursing"))
    if not has_lab_or_exam and not has_progress_or_nursing:
        return "empty_both_sides"
    if not has_lab_or_exam:
        return "empty_lab_exam"
    if not has_progress_or_nursing:
        return "empty_progress_nursing"
    return ""


def _check_legacy_bundle(bundle: PatientBundle) -> str:
    """legacy_progress_nursing 的跳过判断：检查 primary_source/primary/progress/nursing。"""
    sources = getattr(bundle, "sources", {}) or {}
    primary_source = getattr(bundle, "primary_source", "primary")
    has_primary_source = bool(sources.get(primary_source))
    has_primary = bool(sources.get("primary"))
    has_progress = bool(sources.get("progress"))
    has_nursing = bool(sources.get("nursing"))
    if not has_primary_source and not has_primary and not has_progress and not has_nursing:
        return "empty_primary"
    return ""


def _check_frontpage_bundle(bundle: PatientBundle) -> str:
    """frontpage_surgery_first_progress 的跳过判断：检查 frontpage/first_progress。"""
    sources = getattr(bundle, "sources", {}) or {}
    has_frontpage = bool(sources.get("frontpage"))
    has_first_progress = bool(sources.get("first_progress"))
    if not has_frontpage and not has_first_progress:
        return "empty_frontpage"
    return ""


def summarize_bundles(
    audit_type,
    bundles: list[PatientBundle],
    source_row_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """汇总多源 bundle 的可推送性。

    Args:
        audit_type: 审计类型配置
        bundles: 已加载的 PatientBundle 列表
        source_row_counts: 各数据源原始查询行数（可选）

    Returns:
        包含 bundle_count、pushable_count、skip_count、skip_reason_counts、
        side_counts、sample_bundles、bundle_skip_reasons 的汇总字典
    """
    builder = _get_builder(audit_type)
    bundle_count = len(bundles)
    pushable_count = 0
    skip_count = 0
    skip_reason_counts: dict[str, int] = {}
    side_counts: dict[str, int] = {}
    sample_bundles: list[dict[str, Any]] = []
    bundle_skip_reasons: dict[str, str] = {}

    for bundle in bundles:
        source_counts = {
            key: len(value) if isinstance(value, list) else (1 if value else 0)
            for key, value in (getattr(bundle, "sources", {}) or {}).items()
        }

        # 根据 builder 类型选择不同的跳过判断逻辑
        if builder in {"lab_exam_progress_nursing", "lab_exam_structured_progress_nursing"}:
            skip_reason = _check_lab_exam_bundle(bundle)
            has_lab_or_exam = bool(source_counts.get("lab")) or bool(source_counts.get("exam"))
            has_progress_or_nursing = bool(source_counts.get("progress")) or bool(source_counts.get("nursing"))
            side_counts["lab_or_exam_present"] = side_counts.get("lab_or_exam_present", 0) + (1 if has_lab_or_exam else 0)
            side_counts["progress_or_nursing_present"] = side_counts.get("progress_or_nursing_present", 0) + (1 if has_progress_or_nursing else 0)
            side_counts["both_sides_present"] = side_counts.get("both_sides_present", 0) + (1 if has_lab_or_exam and has_progress_or_nursing else 0)
        elif builder == "legacy_progress_nursing":
            skip_reason = _check_legacy_bundle(bundle)
        elif builder == "frontpage_surgery_first_progress":
            skip_reason = _check_frontpage_bundle(bundle)
        else:
            # 未知 builder：只做基础统计，不轻易标记跳过
            skip_reason = ""

        bundle_skip_reasons[getattr(bundle, "bundle_id", "")] = skip_reason

        if skip_reason:
            skip_count += 1
            skip_reason_counts[skip_reason] = skip_reason_counts.get(skip_reason, 0) + 1
        else:
            pushable_count += 1

        if len(sample_bundles) < 5:
            sample_bundles.append({
                "bundle_id": getattr(bundle, "bundle_id", ""),
                "patient_id": bundle.group_values.get("patient_id", ""),
                "visit_number": bundle.group_values.get("visit_number", ""),
                "source_counts": source_counts,
                "pushable": not bool(skip_reason),
                "skip_reason": skip_reason,
                "skip_reason_label": SKIP_REASON_LABELS.get(skip_reason, ""),
            })

    return {
        "source_row_counts": source_row_counts or {},
        "bundle_count": bundle_count,
        "pushable_count": pushable_count,
        "skip_count": skip_count,
        "skip_reason_counts": skip_reason_counts,
        "side_counts": side_counts,
        "sample_bundles": sample_bundles,
        "bundle_skip_reasons": bundle_skip_reasons,
    }
