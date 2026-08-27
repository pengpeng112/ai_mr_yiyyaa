# -*- coding: utf-8 -*-
"""测试共用构造器：快速搭建 PatientContext / DocumentEntry / 规则。"""

from __future__ import annotations

from datetime import datetime

from prearchive.context import (
    DocumentEntry,
    FirstPageData,
    PatientContext,
    SurgeryInfo,
)
from prearchive.rules import RuleSpec


def dt(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def doc(source: str, name: str, event_time=None, update_time=None,
        template_name: str = "") -> DocumentEntry:
    return DocumentEntry(
        source=source,
        report_name=name,
        event_time=event_time,
        update_time=update_time,
        template_name=template_name or name,
    )


def surgery(name: str = "阑尾切除术", time=None, source: str = "sm_itf_entry") -> SurgeryInfo:
    return SurgeryInfo(surgery_name=name, surgery_time=time, source=source)


def make_ctx(**overrides) -> PatientContext:
    """基础上下文：普外科患者、已完成、水位就绪；字段按需覆盖。"""
    finished = overrides.pop("finished_date_time", dt("2026-08-26 10:00:00"))
    defaults = dict(
        patient_id="TEST0100",
        visit_id="1",
        patient_name=" fixture患者 ",
        dept_code="D001",
        dept_name="普外科",
        admit_time=dt("2026-08-20 08:00:00"),
        finished_date_time=finished,
        first_finished_doctor_id="TESTDOC01",
        first_finished_doctor_name="测试医生甲",
        attending_doctor_id="TESTDOC02",
        attending_doctor_name="测试医生乙",
        check_time=dt("2026-08-28 09:00:00"),
    )
    defaults.update(overrides)
    ctx = PatientContext(**defaults)
    if "source_watermarks" not in overrides:
        ctx.source_watermarks = {
            "jhemr": finished,
            "his": finished,
            "sm": finished,
            "lis": finished,
        }
    return ctx


def missing_doc_rule(**overrides) -> RuleSpec:
    params = dict(
        rule_id="R-TEST-MISS",
        rule_type="missing_doc",
        name="测试缺文书规则",
        message="缺测试文书",
        severity="medium",
        deduct_ref=1.0,
        version="2026.08.27-test",
        expect=["手术安全核查表"],
        trigger={"patient_has": "surgery",
                 "evidence": {"surgery_evidence": "sm_itf_entry"}},
        match={"sources": ["sm_itf", "jhemr_blws"], "by": "report_name_fuzzy",
               "vocab": {"手术安全核查表": ["手术安全核查", "核查表"]},
               "exclude_vocab": ["知情同意", "查房记录"],
               "template_field": "progress_template_name"},
    )
    params.update(overrides)
    return RuleSpec(**params)


def time_limit_rule(**overrides) -> RuleSpec:
    params = dict(
        rule_id="R-TEST-TIME",
        rule_type="time_limit",
        name="测试时限规则",
        message="测试文书超时",
        severity="low",
        deduct_ref=0.5,
        version="2026.08.27-test",
        doc_name="入院记录",
        event="admission",
        threshold_hours=24,
        match={"sources": ["jhemr_blws"], "by": "report_name_fuzzy",
               "vocab": {"入院记录": ["入院记录"]},
               "exclude_vocab": [], "template_field": "progress_template_name"},
    )
    params.update(overrides)
    return RuleSpec(**params)


def empty_field_rule(**overrides) -> RuleSpec:
    params = dict(
        rule_id="R-TEST-EMPTY",
        rule_type="empty_field",
        name="测试空项规则",
        message="测试字段未填",
        severity="medium",
        deduct_ref=1.0,
        version="2026.08.27-test",
        fields=["allergy_drug"],
    )
    params.update(overrides)
    return RuleSpec(**params)


def duplicate_rule(**overrides) -> RuleSpec:
    params = dict(
        rule_id="R-TEST-DUP",
        rule_type="duplicate",
        name="测试重复规则",
        message="测试列表重复",
        severity="low",
        deduct_ref=0.5,
        version="2026.08.27-test",
        list_field="diagnoses",
    )
    params.update(overrides)
    return RuleSpec(**params)


def firstpage(available=True, **fields) -> FirstPageData:
    return FirstPageData(available=available, **fields)


def notice_for(output, rule_id: str):
    return [n for n in output.notices if n.get("rule_id") == rule_id]
