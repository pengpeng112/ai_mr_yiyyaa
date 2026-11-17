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
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.timeliness.engine.deadline import to_datetime

logger = logging.getLogger(__name__)

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
    """按 target_json 判一份文书是否为目标文书（不含 t0 时间条件与完成判定）。

    2026-11-14 防呆：mr_class / title_contains_any / title_contains_all /
    monitor_code 四个条件全部为空时直接返回 False（禁止空 target_json 通配
    任意文书——否则会诊类空目标规则会把任何签名文书误判为"已完成"）。
    2026-11-14 七规则轮新增：``title_excludes_any``（标题含任一排除词即否，
    如术后日常查房/交班转科出院/有创）。
    """
    mr_classes = [_normalize_text(item) for item in target.get("mr_class") or ()]
    topic = file_topic(file)
    any_keywords = [_normalize_text(k) for k in target.get("title_contains_any") or () if _normalize_text(k)]
    all_keywords = [_normalize_text(k) for k in target.get("title_contains_all") or () if _normalize_text(k)]
    exclude_keywords = [_normalize_text(k) for k in target.get("title_excludes_any") or () if _normalize_text(k)]
    expected_monitor = target.get("monitor_code")

    if not mr_classes and not any_keywords and not all_keywords and not expected_monitor:
        return False

    if exclude_keywords and any(k in topic for k in exclude_keywords):
        return False
    if mr_classes and _normalize_text(file.get("mr_class")) not in mr_classes:
        return False
    if any_keywords and not any(k in topic for k in any_keywords):
        return False
    if all_keywords and not all(k in topic for k in all_keywords):
        return False

    if expected_monitor:
        codes = {str(item).strip() for item in expected_monitor} if isinstance(expected_monitor, (list, tuple, set)) else {str(expected_monitor).strip()}
        if _normalize_text(file.get("monitor_code")) not in codes:
            return False
    return True


# ---- 2026-11-14 七规则轮：审签身份约束（任务书 §2.C） ----

# 职称兜底关键词（staff_title_map 未命中时按标题/文书主题判主治及以上）。
_TITLE_FALLBACK_KEYWORDS = ("主治", "副主任", "主任")


def _lookup_title(staff_titles: Mapping[str, str] | None, *keys: Any) -> str:
    """在职称映射中按键顺序查（先工号后姓名兜底）；未命中返回空串。"""
    for key in keys:
        text = _normalize_text(key)
        if text and staff_titles:
            found = staff_titles.get(text)
            if found:
                return _normalize_text(found)
    return ""


def _title_is_attending_plus(title: str, allowed: Sequence[str]) -> bool:
    return bool(title) and title in set(allowed)


def _passes_surgeon_sign(file: Mapping[str, Any], operator_id: str) -> bool:
    """require_surgeon_sign：有效术者审签判定（2026-11-14 补丁 2 收紧）。

    surgeon_id 非空时满足任一即通过（严防主刀仅建空草稿、一助改写自签漏网）：
    - last_modify_user_id == surgeon_id（主刀最后审签/本人写并签）；或
    - last_modify_user_id 为空且 creator_id == surgeon_id（无后续他人改写，
      主刀本人创建并首签）；或
    - topic_doctor_id == surgeon_id 且 last_modify_user_id == surgeon_id。

    operator_id 为空时由调用方回退普通 FIRST_SIGN（不误判），本函数不会被调用。
    """
    surgeon = _normalize_text(operator_id)
    if not surgeon:
        return True
    last_modify = _normalize_text(file.get("last_modify_user_id"))
    creator = _normalize_text(file.get("creator_id"))
    topic_doctor = _normalize_text(file.get("topic_doctor_id"))
    if last_modify == surgeon:
        return True
    if not last_modify and creator == surgeon:
        return True
    return topic_doctor == surgeon and last_modify == surgeon


def _ghostwrite_adjusted_completed(
    file: Mapping[str, Any], completed: datetime
) -> datetime:
    """代写场景的完成时间修正（2026-11-14 补丁 2）。

    下级（creator ≠ 审签人）代写草稿并先签了 first_mr_sign_date_time、上级/
    主刀后补审签（last_modify_user_id == 审签人）时：last_modify_date_time
    可解析且 > 首签时间则取 last_modify_date_time——杜绝把下级初签时间当成
    上级审签完成时间。
    """
    last_modify_at = to_datetime(file.get("last_modify_date_time"))
    if last_modify_at is not None and completed is not None and last_modify_at > completed:
        return last_modify_at
    return completed


def _passes_signer_titles(
    file: Mapping[str, Any],
    allowed_titles: Sequence[str],
    staff_titles: Mapping[str, str] | None,
) -> tuple[bool, bool]:
    """require_signer_titles：主治及以上审签判定（任务书 §2.C b/c 两分支）。

    返回 (passed, ghostwritten)：
    - b) topic_doctor_id 非空（下级代写上级查房）：topic_doctor_id 职称属主治及以上
       （或标题职称词兜底），**且** last_modify_user_id == topic_doctor_id（上级
       本人已完成审签，住院医写完自签未审不算）；
    - c) topic_doctor_id 为空（上级亲自创建）：creator_id 或 last_modify_user_id
       职称属主治及以上（排除如 XX住院医师查房记录）；
    - ghostwritten=按 b 分支通过且 creator_id 非空且 != topic_doctor_id（住院医
       代写、上级审签）——调用方据此把完成时间修正为 last_modify_date_time。
    """
    allowed = set(allowed_titles)
    topic_doctor_id = _normalize_text(file.get("topic_doctor_id"))
    topic_doctor_name = _normalize_text(file.get("topic_doctor_name"))
    topic = file_topic(file)

    if topic_doctor_id:
        title = _lookup_title(staff_titles, topic_doctor_id, topic_doctor_name)
        if not _title_is_attending_plus(title, allowed):
            # 兜底：职称映射未命中时按标题职称词判（42 个通用查房模板场景）。
            if not any(k in topic for k in _TITLE_FALLBACK_KEYWORDS):
                return False, False
        # 上级本人必须完成审签：最后修改人=文书医师。
        if _normalize_text(file.get("last_modify_user_id")) != topic_doctor_id:
            return False, False
        creator = _normalize_text(file.get("creator_id"))
        return True, bool(creator and creator != topic_doctor_id)

    creator_id = _normalize_text(file.get("creator_id"))
    creator_name = _normalize_text(file.get("creator_name"))
    last_modify = _normalize_text(file.get("last_modify_user_id"))
    last_modify_name = _normalize_text(file.get("last_modify_user_name"))
    for emp, name in ((creator_id, creator_name), (last_modify, last_modify_name)):
        title = _lookup_title(staff_titles, emp, name)
        if _title_is_attending_plus(title, allowed):
            return True, False
    return False, False


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
    operator_id: Any = None,
    staff_titles: Mapping[str, str] | None = None,
) -> CompletionResult | None:
    """在候选文书中找最早满足完成条件的目标文书；无则 None。

    - 只考虑在档（delete_flag）且匹配 target_json 的文书；
    - 完成时间为空（未签名/未创建）不构成完成；
    - require_time_ge_t0=True 时要求完成时间 >= t0（文书早于 t0 不算）；
    - 多份满足时取完成时间最早的一份。

    2026-11-14 七规则轮新增审签身份约束（target_json 声明式，向后兼容）：
    - ``require_surgeon_sign``（OP_REC）：文书 {creator_id, topic_doctor_id,
      last_modify_user_id} 须命中主刀工号 operator_id；operator_id 为空时
      回退普通 FIRST_SIGN 不误判；
    - ``require_signer_titles``（ATTENDING_FIRST_ROUND）：主治及以上审签判定
      （下级代写需上级本人 last_modify==topic_doctor 且职称达标；上级亲自
      创建需 creator/last_modify 职称达标），职称取 staff_titles 映射
      （工号→职称，兼姓名兜底），未命中按标题职称词兜底。
    """
    target_dict = load_target(target)
    if completion_basis not in COMPLETION_BASES:
        raise TargetConfigError(f"未知 completion_basis: {completion_basis!r}（允许 {', '.join(COMPLETION_BASES)}）")
    trigger_time = to_datetime(t0)
    if require_time_ge_t0 and trigger_time is None:
        raise ValueError("require_time_ge_t0=True 时 t0 不能为空")

    require_surgeon = bool(target_dict.get("require_surgeon_sign"))
    surgeon_id = _normalize_text(operator_id)
    allowed_titles = [
        _normalize_text(item) for item in target_dict.get("require_signer_titles") or () if _normalize_text(item)
    ]
    require_titles = bool(allowed_titles)

    best: CompletionResult | None = None
    for file in files or ():
        if not isinstance(file, Mapping) or not is_active_file(file):
            continue
        if not file_matches_target(file, target_dict):
            continue
        try:
            completed = completion_time(file, completion_basis)
        except ValueError as exc:
            # 2026-11-14 活库实证：文书时间同样存在五位数年份脏数据——单份文书
            # 时间无法解析时跳过该文书（视为未完成），不中断整批评估。
            logger.warning("文书完成时间无法解析，跳过该文书: %s", exc)
            continue
        if completed is None:
            continue
        if require_time_ge_t0 and completed < trigger_time:
            continue
        if require_surgeon and surgeon_id:
            if not _passes_surgeon_sign(file, surgeon_id):
                continue
            # 2026-11-14 补丁 2：一助/住院医代写（creator≠主刀）且靠主刀
            # last_modify 审签通过时，完成时间取 last_modify_date_time（更晚者）。
            creator = _normalize_text(file.get("creator_id"))
            last_modify = _normalize_text(file.get("last_modify_user_id"))
            if creator and creator != surgeon_id and last_modify == surgeon_id:
                completed = _ghostwrite_adjusted_completed(file, completed)
        if require_titles:
            passed, ghostwritten = _passes_signer_titles(file, allowed_titles, staff_titles)
            if not passed:
                continue
            # 补丁 2 分支 b 同步：住院医代写+上级审签 → 完成时间取审签时间。
            if ghostwritten:
                completed = _ghostwrite_adjusted_completed(file, completed)
        if best is None or completed < best.completed_at:
            best = CompletionResult(file=dict(file), file_unique_id=_optional_id(file.get("file_unique_id")), completed_at=completed)
    return best


def _optional_id(value: Any) -> str | None:
    text = _normalize_text(value)
    return text or None
