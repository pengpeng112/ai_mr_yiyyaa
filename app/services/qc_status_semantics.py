"""质控状态分层语义（003 工作包 A / §3.1 冻结口径）。

不改写历史 PushLog.status；仅派生展示与汇总字段。
"""

from __future__ import annotations

from typing import Any


def is_transport_success(status: Any) -> bool:
    return str(status or "").strip() == "success"


def is_qc_usable(status: Any, parse_status: Any, contract_valid: Any = None) -> bool:
    """qc_usable = transport success AND parse success AND contract valid。

    P1-4: contract_valid 为 False 时不可用；为 None 时兼容历史数据（视为通过）。
    """
    if not is_transport_success(status):
        return False
    if str(parse_status or "").strip() != "success":
        return False
    if contract_valid is False:
        return False
    return True


def derive_qc_display_status(status: Any, parse_status: Any, contract_valid: Any = None) -> str:
    """列表派生态：transport_ok / parse_failed / parse_fallback / qc_usable / contract_invalid / 原 status。"""
    st = str(status or "").strip()
    ps = str(parse_status or "").strip()
    if st != "success":
        return st or "unknown"
    if ps == "success":
        if contract_valid is False:
            return "contract_invalid"
        return "qc_usable"
    if ps == "fallback":
        return "parse_fallback"
    if ps == "failed":
        return "parse_failed"
    if ps in ("", "skipped"):
        return "transport_ok"
    return "transport_ok"


def qc_display_label(display_status: str) -> str:
    labels = {
        "qc_usable": "质控可用",
        "contract_invalid": "契约校验失败",
        "parse_failed": "传输成功/解析失败",
        "parse_fallback": "传输成功/解析回退",
        "transport_ok": "传输成功",
        "success": "传输成功",
        "failed": "失败",
        "skipped": "已跳过",
        "pending": "处理中",
        "unknown": "未知",
    }
    return labels.get(str(display_status or "").strip(), str(display_status or ""))


def enrich_log_status_fields(status: Any, parse_status: Any, contract_valid: Any = None) -> dict[str, Any]:
    display = derive_qc_display_status(status, parse_status, contract_valid)
    return {
        "parse_status": str(parse_status or "").strip(),
        "transport_success": is_transport_success(status),
        "qc_usable": is_qc_usable(status, parse_status, contract_valid),
        "contract_valid": contract_valid,
        "qc_display_status": display,
        "qc_display_label": qc_display_label(display),
    }
