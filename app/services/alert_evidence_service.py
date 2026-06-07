"""核查对象证据标题提取与摘要生成服务。"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _parse_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value or "").strip()


def _first(lst: list, key: str, default: str = "") -> str:
    for item in lst:
        if isinstance(item, dict) and item.get(key):
            return _as_text(item[key])
    return default


def extract_evidence_titles(
    push_log: Any = None,
    dimension_obj: Any = None,
    conclusion_obj: Any = None,
) -> dict:
    request_json = {}
    if push_log and hasattr(push_log, "request_json"):
        request_json = _parse_json(getattr(push_log, "request_json", "") or "")

    result = {
        "medical_documents": [],
        "nursing_records": [],
        "lab_reports": [],
        "exam_reports": [],
        "progress_records": [],
        "matched_sources": [],
    }

    # ---- 1. structured_input 优先 ----
    si = request_json.get("structured_input", {}) if isinstance(request_json.get("structured_input"), dict) else {}

    if si:
        jyjc = si.get("检验检查") if isinstance(si.get("检验检查"), dict) else {}
        jybb = jyjc.get("检验报告信息") if isinstance(jyjc.get("检验报告信息"), list) else []
        jcrpt = jyjc.get("检查报告") if isinstance(jyjc.get("检查报告"), list) else []
        bc = si.get("病程") if isinstance(si.get("病程"), dict) else {}
        hl = si.get("护理") if isinstance(si.get("护理"), dict) else {}
        bc_records = bc.get("病程记录") if isinstance(bc.get("病程记录"), list) else []
        hl_records = hl.get("护理记录") if isinstance(hl.get("护理记录"), list) else []

        for item in jybb:
            if not isinstance(item, dict):
                continue
            item_title = _as_text(item.get("检验项目"))
            sub_items = item.get("报告项目") if isinstance(item.get("报告项目"), list) else []
            if sub_items:
                for si_item in sub_items:
                    if not isinstance(si_item, dict):
                        continue
                    result["lab_reports"].append({
                        "title": item_title,
                        "item": _as_text(si_item.get("报告项目名称")),
                        "time": _as_text(item.get("结果时间")),
                        "test_no": _as_text(item.get("检验单号")),
                        "result": _as_text(si_item.get("检验结果")),
                        "flag": _as_text(si_item.get("异常标记")),
                    })
            else:
                result["lab_reports"].append({
                    "title": item_title,
                    "item": "",
                    "time": _as_text(item.get("结果时间")),
                    "test_no": _as_text(item.get("检验单号")),
                    "result": "",
                    "flag": "",
                })

        for item in jcrpt:
            if not isinstance(item, dict):
                continue
            result["exam_reports"].append({
                "title": _as_text(item.get("检查名称")),
                "class": _as_text(item.get("检查类别")),
                "time": _as_text(item.get("报告时间")),
                "exam_no": _as_text(item.get("检查号")),
                "summary": _as_text(item.get("描述") or item.get("检查名称")),
            })

        for item in bc_records:
            if not isinstance(item, dict):
                continue
            result["progress_records"].append({
                "title": _as_text(item.get("病程名称")),
                "time": _as_text(item.get("病程时间")),
                "matched_source": "",
            })

        for item in hl_records:
            if not isinstance(item, dict):
                continue
            result["nursing_records"].append({
                "title": _as_text(item.get("护理单类型")),
                "time": _as_text(item.get("护理时间")),
                "recorder": "",
            })

    # ---- 2. legacy: medical_documents / nursing_records ----
    medical_docs = request_json.get("medical_documents") if isinstance(request_json.get("medical_documents"), list) else []
    nursing_docs = request_json.get("nursing_records") if isinstance(request_json.get("nursing_records"), list) else []

    for item in medical_docs:
        if not isinstance(item, dict):
            continue
        if not result["medical_documents"]:
            result["medical_documents"].append({
                "title": _as_text(item.get("document_name")),
                "time": _as_text(item.get("document_time")),
                "doctor": _as_text(item.get("signed_doctor") or item.get("creator_name")),
            })

    for item in nursing_docs:
        if not isinstance(item, dict):
            continue
        if not result["nursing_records"]:
            result["nursing_records"].append({
                "title": _as_text(item.get("record_type")),
                "time": _as_text(item.get("record_time")),
                "recorder": _as_text(item.get("recorder")),
            })

    # ---- 3. legacy: lab/exam/progress/nursing context ----
    abnormal_labs = request_json.get("abnormal_labs") if isinstance(request_json.get("abnormal_labs"), dict) else {}
    abnormal_exams = request_json.get("abnormal_exams") if isinstance(request_json.get("abnormal_exams"), dict) else {}
    progress_ctx = request_json.get("progress_context") if isinstance(request_json.get("progress_context"), dict) else {}
    nursing_ctx = request_json.get("nursing_context") if isinstance(request_json.get("nursing_context"), dict) else {}

    lab_items = abnormal_labs.get("items") if isinstance(abnormal_labs.get("items"), list) else []
    exam_reports = abnormal_exams.get("reports") if isinstance(abnormal_exams.get("reports"), list) else []
    progress_records = progress_ctx.get("records") if isinstance(progress_ctx.get("records"), list) else []
    nursing_records = nursing_ctx.get("records") if isinstance(nursing_ctx.get("records"), list) else []

    if not result["lab_reports"]:
        for item in lab_items:
            if not isinstance(item, dict):
                continue
            item_name = _as_text(item.get("report_item_name") or item.get("item_name"))
            result["lab_reports"].append({
                "title": _as_text(item.get("test_name")),
                "item": item_name,
                "time": _as_text(item.get("result_time")),
                "test_no": _as_text(item.get("test_no")),
                "result": (_as_text(item.get("result")) + (_as_text(item.get("units")))) if item.get("result") else "",
                "flag": _as_text(item.get("abnormal_indicator")),
            })

    if not result["exam_reports"]:
        for item in exam_reports:
            if not isinstance(item, dict):
                continue
            result["exam_reports"].append({
                "title": _as_text(item.get("exam_name") or item.get("description")),
                "class": _as_text(item.get("exam_class")),
                "time": _as_text(item.get("report_time") or item.get("exam_time")),
                "exam_no": _as_text(item.get("exam_no")),
                "summary": _as_text(item.get("summary") or item.get("description")),
            })

    if not result["progress_records"]:
        for item in progress_records:
            if not isinstance(item, dict):
                continue
            result["progress_records"].append({
                "title": _as_text(item.get("record_name")),
                "time": _as_text(item.get("event_time")),
                "matched_source": _as_text(item.get("matched_event_source_label")),
            })

    if not result["nursing_records"]:
        for item in nursing_records:
            if not isinstance(item, dict):
                continue
            result["nursing_records"].append({
                "title": _as_text(item.get("record_name")),
                "time": _as_text(item.get("event_time")),
                "recorder": _as_text(item.get("matched_event_source_label") or ""),
            })

    # ---- 4. matched_sources 去重 ----
    seen = set()
    for group in ("medical_documents", "nursing_records", "lab_reports", "exam_reports", "progress_records"):
        for item in result.get(group, []):
            title = item.get("title", "")
            if title and title not in seen:
                seen.add(title)
                result["matched_sources"].append(title)

    return result


def build_evidence_summary(evidence_titles: dict, max_items_per_group: int = 2, max_len: int = 280) -> str:
    if not evidence_titles or not isinstance(evidence_titles, dict):
        return ""

    groups = []
    group_order = [
        ("medical_documents", "病历文书"),
        ("progress_records", "病程记录"),
        ("nursing_records", "护理记录"),
        ("lab_reports", "检验"),
        ("exam_reports", "检查"),
    ]

    for key, label in group_order:
        items = evidence_titles.get(key, [])
        if not isinstance(items, list) or not items:
            continue
        for i, item in enumerate(items):
            if i >= max_items_per_group:
                remaining = len(items) - max_items_per_group
                groups.append(f"{label} 等 {remaining} 项")
                break
            if not isinstance(item, dict):
                continue
            title = _as_text(item.get("title"))
            time_str = _as_text(item.get("time"))
            extra = ""
            if key == "lab_reports":
                extra = _as_text(item.get("item")) or ""
                result_str = _as_text(item.get("result"))
                flag = _as_text(item.get("flag"))
                if result_str:
                    extra = f"{extra}-{result_str}" if extra else result_str
                if flag:
                    extra = f"{extra}{flag}" if extra else flag
            elif key == "exam_reports":
                cls = _as_text(item.get("class"))
                if cls and cls != title:
                    extra = cls
            parts = []
            if title:
                parts.append(f"《{title}》")
            if extra:
                parts[0] = parts[0][:-1] + f"-{extra}》"
            if time_str:
                parts.append(time_str)
            groups.append(" ".join(parts))

    summary = "；".join(groups)
    if len(summary) > max_len:
        summary = summary[:max_len - 3] + "..."
    return summary
