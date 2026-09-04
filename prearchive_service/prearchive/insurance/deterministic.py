# -*- coding: utf-8 -*-
"""确定性编码提示插件（039 §8.1）：只做有明确数据依据的配置化提示。

提示项（全部默认开启、全部只提示不扣分不阻断）：
- 主诊断缺失 / ICD 编码格式；
- 手术病例主手术缺失（有次要手术但无主手术）；
- 重复编码（诊断/手术列表内重复）；
- 缺失字段只产生 unknown diagnostics，不猜测。
"""

from __future__ import annotations

import re
from typing import List

from ..result_contract import InsuranceAssessment
from . import InsuranceContext

_DEFAULT_SETTINGS = {
    "require_principal_diagnosis": True,
    "require_principal_surgery_for_surgery_cases": True,
    "icd_pattern": r"^[A-Z]\d{2}(\.\d{1,3})?$",
}


class DeterministicCodingPlugin:
    code = "deterministic"

    def __init__(self, settings: dict | None = None):
        merged = dict(_DEFAULT_SETTINGS)
        merged.update(settings or {})
        self.settings = merged
        self._icd = None
        try:
            self._icd = re.compile(str(self.settings["icd_pattern"]))
        except re.error:
            self._icd = None   # 非法正则留给 validate_configuration 报错，不炸构造

    def validate_configuration(self) -> List[dict]:
        problems: List[dict] = []
        try:
            re.compile(str(self.settings["icd_pattern"]))
        except re.error as exc:
            problems.append({"level": "error", "field": "icd_pattern",
                             "message": f"invalid regex: {exc}"})
        return problems

    def evaluate(self, context: InsuranceContext) -> InsuranceAssessment:
        diagnostics: List[dict] = []
        for missing in context.missing_fields:
            diagnostics.append({"code": "missing_field", "field": missing,
                                "message": f"field {missing} not provided; cannot judge"})
        warn = 0

        if self.settings.get("require_principal_diagnosis", True):
            if not context.principal_diagnosis:
                diagnostics.append({"code": "principal_diagnosis_missing",
                                    "severity": "medium",
                                    "message": "主诊断编码缺失"})
                warn += 1
            elif self._icd is not None and not self._icd.match(context.principal_diagnosis):
                diagnostics.append({"code": "principal_diagnosis_format",
                                    "severity": "low",
                                    "message": f"主诊断编码格式异常: "
                                               f"{context.principal_diagnosis}"})
                warn += 1

        if self.settings.get("require_principal_surgery_for_surgery_cases", True):
            if not context.principal_surgery and context.secondary_surgeries:
                diagnostics.append({"code": "principal_surgery_missing",
                                    "severity": "medium",
                                    "message": "存在次要手术但主手术编码缺失"})
                warn += 1

        for field_name, codes in (("secondary_diagnoses", context.secondary_diagnoses),
                                  ("secondary_surgeries", context.secondary_surgeries)):
            dup = sorted({c for c in codes if codes.count(c) > 1})
            if dup:
                diagnostics.append({"code": "duplicate_codes", "field": field_name,
                                    "severity": "low",
                                    "message": f"重复编码: {','.join(dup)}"})
                warn += 1

        status = "warn" if warn else "pass"
        if context.missing_fields and not warn:
            status = "unknown"
        return InsuranceAssessment(
            status=status,
            plugin_code=self.code,
            ruleset_region="",
            ruleset_year="",
            diagnostics=diagnostics,
        )
