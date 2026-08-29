# -*- coding: utf-8 -*-
"""提醒对象解析：完成医生优先，管床医师兜底（028 D1/A4）。

工号 → 企微 userid 的映射是 P0-6 基线工作（first_finished_doctor_id 与
V_AI_ZKUSER 工号体系是否同源、命中率分布），一期以可注入的映射函数出现，
生产实现待基线数据落地后回填。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .context import PatientContext

# 默认顺序不含 doc_author 档（T2-2：新档仅显式配置 fallback_order 才生效；
# 029 P0-6 证实完成医生字段 177 无数据，doc_author=文书书写医生为可选中间档）
FALLBACK_ORDER = ("first_finished_doctor", "attending_doctor")
KNOWN_RECEIVER_TIERS = ("first_finished_doctor", "doc_author", "attending_doctor")


@dataclass
class Receiver:
    user_id: str          # 企微 userid（映射成功值）
    doctor_id: str        # 工号
    doctor_name: str = ""
    is_fallback: bool = False   # True=走了管床兜底
    via: str = ""                # 命中的候选顺序名


UserIdMapper = Callable[[str], Optional[str]]


def passthrough_userid_mapper(doctor_id: str) -> Optional[str]:
    """缺省映射：工号即 userid（沙箱/演示用；生产替换为 P0-6 基线后的真实映射）。"""
    return doctor_id or None


class DefaultReceiverResolver:
    """按 fallback_order 依次尝试候选工号，映射成功即定。"""

    def __init__(self, userid_mapper: UserIdMapper = passthrough_userid_mapper,
                 fallback_order: tuple = FALLBACK_ORDER):
        self.userid_mapper = userid_mapper
        self.fallback_order = fallback_order or FALLBACK_ORDER

    def _candidates(self, ctx: PatientContext) -> list:
        pairs = {
            "first_finished_doctor": (ctx.first_finished_doctor_id,
                                      ctx.first_finished_doctor_name),
            "doc_author": (ctx.last_doc_author_id,
                           ctx.last_doc_author_name),
            "attending_doctor": (ctx.attending_doctor_id,
                                 ctx.attending_doctor_name),
        }
        result = []
        for key in self.fallback_order:
            doctor_id, doctor_name = pairs.get(key, ("", ""))
            if doctor_id:
                result.append((key, doctor_id, doctor_name))
        return result

    def resolve(self, ctx: PatientContext) -> Optional[Receiver]:
        candidates = self._candidates(ctx)
        primary = self.fallback_order[0] if self.fallback_order else ""
        for via, doctor_id, doctor_name in candidates:
            user_id = self.userid_mapper(doctor_id)
            if user_id:
                return Receiver(
                    user_id=str(user_id),
                    doctor_id=doctor_id,
                    doctor_name=doctor_name,
                    is_fallback=(via != primary),   # 命中的不是首选渠道=兜底
                    via=via,
                )
        return None
