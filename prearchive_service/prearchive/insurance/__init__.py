# -*- coding: utf-8 -*-
"""医保质控插件接口（039 §8）。

纪律：
- 本轮不承诺替代医保局审核系统，不自动拒付；一切输出只是提示；
- 插件异常必须返回 unknown 评估（fail-open），不得影响病历质控结果；
- OpenDRG 适配器只是隔离壳：G5（年度规则包）/G6（许可证）未过前禁止启用，
  不得下载/复制/vendoring 任何第三方源码或规则包。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable

from ..result_contract import InsuranceAssessment


@dataclass
class InsuranceContext:
    """医保评估输入（insurance_mapping 层产出；缺字段必须给 diagnostics）。"""

    patient_id: str = ""
    visit_number: str = ""
    age_years: object = None
    gender: str = ""
    length_of_stay_days: object = None
    principal_diagnosis: str = ""          # 主诊断 ICD 编码
    secondary_diagnoses: List[str] = field(default_factory=list)
    principal_surgery: str = ""            # 主手术/操作 ICD 编码
    secondary_surgeries: List[str] = field(default_factory=list)
    birth_weight_grams: object = None
    discharge_method: str = ""
    total_cost: object = None
    missing_fields: List[str] = field(default_factory=list)


@runtime_checkable
class InsuranceQCPlugin(Protocol):
    code: str

    def validate_configuration(self) -> List[dict]:
        """配置自检：返回 [{level: error|warning, field, message}]。"""
        ...

    def evaluate(self, context: InsuranceContext) -> InsuranceAssessment:
        ...


def unknown_assessment(plugin_code: str, diagnostics: List[dict]) -> InsuranceAssessment:
    return InsuranceAssessment(
        status="unknown",
        plugin_code=plugin_code,
        diagnostics=diagnostics,
    )
