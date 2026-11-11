"""文书匹配与完成判定（病历时效质控 T3）。

匹配条件（按 target_json）：
- delete_flag=0（或 '0'/空）——已删除文书不参与；
- mr_class 在列表内；
- 可选标题关键词：title_contains_any 任一包含 / title_contains_all 全部包含；
- 可选 monitor_code 匹配（危急值类按监控码锁定文书时使用）；
- 可选“文书时间 >= t0”：手术/危急值/会诊类要求完成发生在触发之后
  （“文书时间”取完成口径时间：FIRST_SIGN→签名时间，CREATE→创建时间）。

完成时间铁律（实证 R1 / 勘误 E12、E13）：
- FIRST_SIGN 取 first_mr_sign_date_time；CREATE 取 create_date_time；
- 该字段为空即未完成——草稿 file_flag='T' 且未签名必须判未完成；
- 严禁用 file_flag=='1' 判断完成（已签名文书的 file_flag 实测有 0/1/2/3）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.timeliness.engine.deadline import to_datetime

COMPLETION_BASIS_FIRST_SIGN = "FIRST_SIGN"
COMPLETION_BASIS_CREATE = "CREATE"
COMPLETION_BASES = (COMPLETION_BASIS_FIRST_SIGN, COMPLETION_BASIS_CREATE)


class TargetConfigError(ValueError):
    """target_json 结构非法。"""


def load_target(target: Any) -> dict:
    """target_json 规整为 dict（接受 dict 或 JSON 字符串）。"""
    if target is None:
        return {}
    if isinstance(target, str):
        text = target.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise TargetConfigError(f"target_json 不是合法 JSON: {text[:120]!r}") from exc
        if not isinstance(parsed, dict):
            raise TargetConfigError("target_json 须为 JSON 对象")
        return parsed
    if isinstance(target, Mapping):
        return dict(target)
    raise TargetConfigError(f"target_json 须为 dict 或 JSON 字符串: {type(target)!r}")


def is_active_file(file: Mapping[str, Any]) -> bool:
    """delete_flag=0（或 '0'/空/None）视为在档；'1'/1 等非零值视为已删除。"""
    flag = file.get("delete_flag")
    if flag is None:
        return True
    if isinstance(flag, bool):
        return not flag
    if isinstance(flag, (int, float)):
        return int(flag) == 0
    return str(flag).strip() in ("", "0")


def _normalize_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def file_topic(file: Mapping[str, Any]) -> str:
    """文书标题：优先 topic，退回 topic_title_name。"""
    return _normalize_text(file.get("topic")) or _normalize_text(file.get("topic_title_name"))


def file_matches_target(file: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    """按 target_json 判一份文书是否为目标文书（不含 t0 时间条件与完成判定）。"""
    mr_classes = [_normalize_text(item) for item in target.get("mr_class") or ()]
    if mr_classes and _normalize_text(file.get("mr_class")) not in mr_classes:
        return False

    topic = file_topic(file)
    any_keywords = [_normalize_text(k) for k in target.get("title_contains_any") or () if _normalize_text(k)]
    if any_keywords and not any(k in topic for k in any_keywords):
        return False
    all_keywords = [_normalize_text(k) for k in target.get("title_contains_all") or () if _normalize_text(k)]
    if all_keywords and not all(k in topic for k in all_keywords):
        return False

    expected_monitor = target.get("monitor_code")
    if expected_monitor:
        codes = {str(item).strip() for item in expected_monitor} if isinstance(expected_monitor, (list, tuple, set)) else {str(expected_monitor).strip()}
        if _normalize_text(file.get("monitor_code")) not in codes:
            return False
    return True


def completion_time(file: Mapping[str, Any], completion_basis: str) -> datetime | None:
    """完成口径时间：FIRST_SIGN→first_mr_sign_date_time；CREATE→create_date_time。

    为空即未完成（E12/R1：草稿未签名必须判未完成；不使用 file_flag，E13）。
    """
    if completion_basis == COMPLETION_BASIS_CREATE:
        return to_datetime(file.get("create_date_time"))
    if completion_basis == COMPLETION_BASIS_FIRST_SIGN:
        return to_datetime(file.get("first_mr_sign_date_time"))
    raise TargetConfigError(f"未知 completion_basis: {completion_basis!r}（允许 {', '.join(COMPLETION_BASES)}）")


@dataclass(frozen=True)
class CompletionResult:
    """匹配到的完成文书：最早满足完成条件的一份。"""

    file: dict
    file_unique_id: str | None
    completed_at: datetime


def find_completion(
    files: Sequence[Mapping[str, Any]],
    *,
    target: Any,
    completion_basis: str = COMPLETION_BASIS_FIRST_SIGN,
    t0: Any = None,
    require_time_ge_t0: bool = False,
) -> CompletionResult | None:
    """在候选文书中找最早满足完成条件的目标文书；无则 None。

    - 只考虑在档（delete_flag）且匹配 target_json 的文书；
    - 完成时间为空（未签名/未创建）不构成完成；
    - require_time_ge_t0=True 时要求完成时间 >= t0（文书早于 t0 不算）；
    - 多份满足时取完成时间最早的一份。
    """
    target_dict = load_target(target)
    if completion_basis not in COMPLETION_BASES:
        raise TargetConfigError(f"未知 completion_basis: {completion_basis!r}（允许 {', '.join(COMPLETION_BASES)}）")
    trigger_time = to_datetime(t0)
    if require_time_ge_t0 and trigger_time is None:
        raise ValueError("require_time_ge_t0=True 时 t0 不能为空")

    best: CompletionResult | None = None
    for file in files or ():
        if not isinstance(file, Mapping) or not is_active_file(file):
            continue
        if not file_matches_target(file, target_dict):
            continue
        completed = completion_time(file, completion_basis)
        if completed is None:
            continue
        if require_time_ge_t0 and completed < trigger_time:
            continue
        if best is None or completed < best.completed_at:
            best = CompletionResult(file=dict(file), file_unique_id=_optional_id(file.get("file_unique_id")), completed_at=completed)
    return best


def _optional_id(value: Any) -> str | None:
    text = _normalize_text(value)
    return text or None
