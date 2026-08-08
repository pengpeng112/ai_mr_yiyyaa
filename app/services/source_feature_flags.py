"""
012 P2 草案：数据源切换 feature flag（默认旧路径，禁止自动切换）。

flag（012 §9 P2）：
- progress_source: v_bcjl（默认，旧 Oracle 数据中心病程）| vastbase_v1（Vastbase 标准病程）
- nursing_source: legacy（默认，旧 YDHL 视图路径）| oracle_v1（窄查询 V1）

约束：
- 缺省一律回退旧生产来源；非法值 fail-closed 抛错（配置校验层拦截）；
- 本模块仅解析/校验 flag，不含任何切换执行码；切换接线需另行书面批准。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROGRESS_SOURCE_V_BCJL = "v_bcjl"
PROGRESS_SOURCE_VASTBASE_V1 = "vastbase_v1"
VALID_PROGRESS_SOURCES = frozenset({PROGRESS_SOURCE_V_BCJL, PROGRESS_SOURCE_VASTBASE_V1})

NURSING_SOURCE_LEGACY = "legacy"
NURSING_SOURCE_ORACLE_V1 = "oracle_v1"
VALID_NURSING_SOURCES = frozenset({NURSING_SOURCE_LEGACY, NURSING_SOURCE_ORACLE_V1})


@dataclass(frozen=True)
class SourceFlags:
    """解析后的数据源开关；默认全部旧路径。"""

    progress_source: str = PROGRESS_SOURCE_V_BCJL
    nursing_source: str = NURSING_SOURCE_LEGACY


def _resolve_flag(raw_value: object, valid: frozenset[str], default: str, flag_name: str) -> str:
    if raw_value is None or str(raw_value).strip() == "":
        return default
    value = str(raw_value).strip()
    if value not in valid:
        raise ValueError(f"非法 {flag_name}: {value}（合法值: {sorted(valid)}）")
    return value


def resolve_source_flags(config: dict | None) -> SourceFlags:
    """从配置解析数据源开关。

    配置位置：audit_type.payload.source_flags（dict），键为
    progress_source / nursing_source。缺省返回全旧路径。
    """
    flags_cfg = dict((config or {}).get("source_flags") or {})
    return SourceFlags(
        progress_source=_resolve_flag(
            flags_cfg.get("progress_source"),
            VALID_PROGRESS_SOURCES,
            PROGRESS_SOURCE_V_BCJL,
            "progress_source",
        ),
        nursing_source=_resolve_flag(
            flags_cfg.get("nursing_source"),
            VALID_NURSING_SOURCES,
            NURSING_SOURCE_LEGACY,
            "nursing_source",
        ),
    )


def is_new_source_enabled(flags: SourceFlags) -> bool:
    """是否有任一源指向新路径（仅用于观测/审计日志，不驱动切换）。"""
    return (
        flags.progress_source != PROGRESS_SOURCE_V_BCJL
        or flags.nursing_source != NURSING_SOURCE_LEGACY
    )
