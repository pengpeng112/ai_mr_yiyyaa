# -*- coding: utf-8 -*-
"""Noop 医保插件（默认）：评估恒为 disabled。"""

from __future__ import annotations

from typing import List

from ..result_contract import InsuranceAssessment
from . import InsuranceContext


class NoopInsurancePlugin:
    code = "noop"

    def validate_configuration(self) -> List[dict]:
        return []

    def evaluate(self, context: InsuranceContext) -> InsuranceAssessment:
        return InsuranceAssessment(
            status="disabled",
            plugin_code=self.code,
            diagnostics=[{"code": "noop", "message": "insurance qc disabled by default"}],
        )
