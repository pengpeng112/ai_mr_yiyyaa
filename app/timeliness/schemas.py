"""病历时效质控 API 请求/响应模型（T5）。

- 版本保存/试算复用同一组"版本改动字段"（与 rules_seed.VERSION_FIELDS 对齐，
  *_json 字段接受 dict/list 或 JSON 字符串）；
- 响应多为 ORM 行直出 dict，此处只声明请求体与轻量响应包装。
"""
from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field

# 与 rules_seed.VERSION_FIELDS 一致的版本改动字段（全部可选=部分修改）。
JsonLike = Union[dict, list, str, None]


class RuleVersionChanges(BaseModel):
    """规则版本改动（保存新版本 / dry-run 试算共用）。"""

    trigger_type: Optional[str] = None
    trigger_filter_json: JsonLike = None
    target_json: JsonLike = None
    completion_basis: Optional[str] = None
    limit_minutes: Optional[int] = None
    workday_only: Optional[bool] = None
    warn_before_minutes: Optional[int] = None
    action_mode: Optional[str] = None
    channels_json: JsonLike = None
    dept_scope_json: JsonLike = None
    jhemr_monitor_code: Optional[str] = None
    penalty_amount: Optional[int] = None
    note: Optional[str] = None

    def changes_dict(self) -> dict[str, Any]:
        """显式传入的字段（含显式置 None 清空可空字段）；未传字段不参与覆盖。"""
        return self.model_dump(exclude_unset=True)


class RuleVersionCreateRequest(RuleVersionChanges):
    """POST /rules/{code}/versions：保存新版本（不覆盖旧版本）。"""

    created_by: Optional[str] = Field(default=None, description="操作人（缺省取当前用户）")


class RuleToggleRequest(BaseModel):
    """POST /rules/{code}/toggle：启停规则。"""

    enabled: bool


class RuleDryRunRequest(RuleVersionChanges):
    """POST /rules/{code}/dry-run：用待保存版本对当前数据试算（绝不写库）。"""


class MessageResponse(BaseModel):
    message: str
    success: bool = True
    data: Optional[dict[str, Any]] = None
