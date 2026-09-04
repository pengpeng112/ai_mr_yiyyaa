# -*- coding: utf-8 -*-
"""OpenDRG 隔离适配器壳（039 §8.2）。

红线：
- G5（本院统筹区年度规则包）/G6（仓库 LICENSE 与规则数据授权核验）未完成前，
  本插件恒返回 unknown + 阻断 diagnostics——不加载规则包、不触网、不执行外部进程；
- 未 vendoring 任何 OpenDRG 源码；启用需 license_verified=true 且 ruleset 元数据
  （region/year/version/sha256）齐备，缺一即 blocked；
- 真实分组失败也只返回 unknown，绝不影响病历质控结果。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Optional

from ..result_contract import InsuranceAssessment
from . import InsuranceContext


class OpenDRGAdapter:
    code = "opendrg"

    def __init__(self, settings: dict | None = None):
        settings = dict(settings or {})
        self.enabled = bool(settings.get("enabled", False))
        self.license_verified = bool(settings.get("license_verified", False))
        self.ruleset_path = str(settings.get("ruleset_path") or "")
        self.adapter_mode = str(settings.get("adapter_mode") or "subprocess")

    # ---- 门禁 ----

    def validate_configuration(self) -> List[dict]:
        problems: List[dict] = []
        if not self.enabled:
            problems.append({"level": "warning", "field": "enabled",
                             "message": "opendrg adapter disabled (default)"})
            return problems
        if not self.license_verified:
            problems.append({"level": "error", "field": "license_verified",
                             "message": "G6 blocked: OpenDRG license/data authorization "
                                        "not verified; vendoring forbidden"})
        meta = self._load_ruleset_meta()
        if meta is None:
            problems.append({"level": "error", "field": "ruleset_path",
                             "message": "ruleset meta (region/year/version/sha256) "
                                        "missing or unreadable (G5)"})
        else:
            missing = [k for k in ("region", "year", "version") if not meta.get(k)]
            if missing:
                problems.append({"level": "error", "field": "ruleset_meta",
                                 "message": f"ruleset meta missing keys: {missing}"})
            if not self._verify_ruleset_sha256(meta):
                problems.append({"level": "error", "field": "ruleset_sha256",
                                 "message": "ruleset sha256 mismatch; refuse to load"})
        return problems

    def _load_ruleset_meta(self) -> Optional[dict]:
        if not self.ruleset_path:
            return None
        meta_path = Path(self.ruleset_path)
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _verify_ruleset_sha256(self, meta: dict) -> bool:
        expected = str(meta.get("sha256") or "")
        data_file = meta.get("data_file")
        if not expected or not data_file:
            return False
        path = Path(self.ruleset_path).parent / str(data_file)
        if not path.exists():
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest == expected

    # ---- 评估 ----

    def evaluate(self, context: InsuranceContext) -> InsuranceAssessment:
        if not self.enabled:
            return InsuranceAssessment(
                status="disabled", plugin_code=self.code,
                diagnostics=[{"code": "opendrg_disabled",
                              "message": "adapter disabled by default (G5/G6)"}])
        problems = self.validate_configuration()
        blocking = [p for p in problems if p.get("level") == "error"]
        if blocking:
            return InsuranceAssessment(
                status="unknown", plugin_code=self.code,
                diagnostics=[{"code": "opendrg_blocked", "message": p["message"]}
                             for p in blocking])
        # 门禁通过后才可能有真实分组；当前阶段无可用本地规则包，保持 unknown
        # （真实接入在 B 阶段经人工批准后实现，禁止在阶段 A 伪造分组结果）。
        return InsuranceAssessment(
            status="unknown", plugin_code=self.code,
            diagnostics=[{"code": "opendrg_no_local_ruleset",
                          "message": "no authorized local ruleset staged yet"}])


def build_insurance_plugin(config: dict):
    """按配置构造插件（fail-open：任何异常回退 Noop）。"""
    from .noop import NoopInsurancePlugin

    section = (config or {}).get("insurance_qc") or {}
    if not bool(section.get("enabled")):
        return NoopInsurancePlugin()
    plugin = str(section.get("plugin") or "noop")
    try:
        if plugin == "deterministic":
            from .deterministic import DeterministicCodingPlugin
            return DeterministicCodingPlugin(section.get("deterministic"))
        if plugin == "opendrg":
            from .opendrg_adapter import OpenDRGAdapter
            return OpenDRGAdapter(section.get("opendrg"))
        return NoopInsurancePlugin()
    except Exception:
        return NoopInsurancePlugin()
