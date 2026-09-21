# -*- coding: utf-8 -*-
"""046 T3 多手术事件关联测试（F12 修复：多手术不共享一份文书）。"""

from datetime import datetime

from prearchive.collectors import SmCollector
from prearchive.context import SRC_JHEMR_BLWS, SRC_SM_ITF, DocumentEntry, SurgeryInfo
from prearchive.engine import RuleEngine, _pair_docs_to_events

from helpers import doc, dt, make_ctx, missing_doc_rule, surgery, time_limit_rule


# ---------------------------------------------------------------- 配对原语


def test_pairing_greedy_after_event_preferred():
    slots = [(0, dt("2026-08-24 15:00:00")), (1, dt("2026-08-26 10:00:00"))]
    result = _pair_docs_to_events([dt("2026-08-24 14:00:00"),
                                   dt("2026-08-26 09:00:00")], slots)
    assert result == [0, 1]   # 各事件取各自之后的最早文书


def test_pairing_two_events_one_doc_second_gets_none():
    """046 §7：同就诊两次手术仅一份文书 → 每事件独立评估，第二事件缺文书。"""
    slots = [(0, dt("2026-08-24 15:00:00"))]
    result = _pair_docs_to_events([dt("2026-08-24 14:00:00"),
                                   dt("2026-08-26 09:00:00")], slots)
    assert result == [0, None]   # 一份文书不能覆盖两台手术


def test_pairing_no_time_docs_assignable():
    slots = [(0, None), (1, None)]
    result = _pair_docs_to_events([dt("2026-08-24 14:00:00")], slots)
    assert result == [0]         # 时间未知的文书可被分配（存在性可判）


# ---------------------------------------------------------------- missing_doc 多手术


def _surgery_doc_rule():
    return missing_doc_rule(
        rule_id="R-MISS-ANES", expect=["麻醉单"],
        match={"sources": ["sm_itf"], "by": "report_name_fuzzy",
               "vocab": {"麻醉单": ["麻醉单"]},
               "exclude_vocab": [], "template_field": "progress_template_name"},
        min_hours_after_event=0, require_source_ready=False)


def test_missing_doc_two_surgeries_one_anesthesia_record():
    """两台手术仅一份麻醉单 → 第二台缺（两个事件实例独立评估）。"""
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-24 14:00:00")),
                     surgery(time=dt("2026-08-26 09:00:00"))]
    ctx.documents = [doc(SRC_SM_ITF, "麻醉单", event_time=dt("2026-08-24 15:00:00"))]
    output = RuleEngine([_surgery_doc_rule()]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["details"]["event_instance_id"] == "surgery-2"
    evals = {e["event_instance_id"]: e for e in output.evaluations}
    assert evals["surgery-1"]["status"] == "pass"
    assert evals["surgery-2"]["status"] == "fail"


def test_missing_doc_two_surgeries_two_records_pass():
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-24 14:00:00")),
                     surgery(time=dt("2026-08-26 09:00:00"))]
    ctx.documents = [
        doc(SRC_SM_ITF, "麻醉单", event_time=dt("2026-08-24 15:00:00")),
        doc(SRC_SM_ITF, "麻醉单", event_time=dt("2026-08-26 11:00:00")),
    ]
    output = RuleEngine([_surgery_doc_rule()]).evaluate(ctx)
    assert output.problems == []
    assert len(output.evaluations) == 2
    assert all(e["status"] == "pass" for e in output.evaluations)


def test_missing_doc_duplicate_data_entries_do_not_double_count():
    """重复数据（同文书两条目）不产生双份覆盖：仍按事件数分配。"""
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-24 14:00:00"))]
    ctx.documents = [
        doc(SRC_SM_ITF, "麻醉单", event_time=dt("2026-08-24 15:00:00")),
        doc(SRC_SM_ITF, "麻醉单", event_time=dt("2026-08-24 15:30:00")),  # 重复
    ]
    output = RuleEngine([_surgery_doc_rule()]).evaluate(ctx)
    assert output.problems == []
    assert len(output.evaluations) == 1    # 一台手术一个实例（重复条目不新增实例）


# ---------------------------------------------------------------- time_limit 多手术


def _surgery_time_rule(**kw):
    params = dict(
        rule_id="R-TIME-SURG", doc_name="手术记录", event="surgery",
        threshold_hours=24,
        match={"sources": ["jhemr_blws"], "by": "report_name_fuzzy",
               "vocab": {"手术记录": ["手术记录"]},
               "exclude_vocab": ["知情同意"], "template_field": "progress_template_name"})
    params.update(kw)
    return time_limit_rule(**params)


def test_time_limit_two_surgeries_independent_deadlines():
    """两台手术：一台按期一台超期 → 仅超期事件 fail（临界互不干扰）。"""
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-22 10:00:00")),
                     surgery(time=dt("2026-08-25 10:00:00"))]
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "手术记录", event_time=dt("2026-08-22 20:00:00")),  # 10h ✓
        doc(SRC_JHEMR_BLWS, "手术记录", event_time=dt("2026-08-27 09:00:00")),  # 47h ✗
    ]
    output = RuleEngine([_surgery_time_rule()]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["details"]["event_instance_id"] == "surgery-2"
    assert output.problems[0]["details"]["elapsed_hours"] == 47.0
    evals = {e["event_instance_id"]: e["status"] for e in output.evaluations}
    assert evals == {"surgery-1": "pass", "surgery-2": "fail"}


def test_time_limit_boundary_equal_and_just_after():
    """临界：恰=24h pass（含边界）；24h+1s fail。"""
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-22 10:00:00"))]
    ctx.documents = [doc(SRC_JHEMR_BLWS, "手术记录",
                         event_time=dt("2026-08-23 10:00:00"))]
    output = RuleEngine([_surgery_time_rule()]).evaluate(ctx)
    assert output.problems == []
    ctx.documents = [doc(SRC_JHEMR_BLWS, "手术记录",
                         event_time=dt("2026-08-23 10:00:01"))]
    output = RuleEngine([_surgery_time_rule()]).evaluate(ctx)
    assert len(output.problems) == 1


def test_time_limit_one_doc_two_surgeries_second_missing():
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-22 10:00:00")),
                     surgery(time=dt("2026-08-25 10:00:00"))]
    ctx.documents = [doc(SRC_JHEMR_BLWS, "手术记录",
                         event_time=dt("2026-08-22 20:00:00"))]
    output = RuleEngine([_surgery_time_rule()]).evaluate(ctx)
    evals = {e["event_instance_id"]: e for e in output.evaluations}
    assert evals["surgery-1"]["status"] == "pass"
    assert evals["surgery-2"]["status"] == "fail"
    assert evals["surgery-2"]["reason_code"] == "doc_not_found"


# ---------------------------------------------------------------- 手麻聚类（SM 条目≠手术事件）


class _FakeSmGateway:
    def __init__(self, rows):
        self._rows = rows

    def fetch_itf_entries(self, patient_id, visit_id):
        return self._rows


def test_sm_collector_clusters_entries_into_one_surgery():
    """一台手术的多条手麻文书（麻醉/护理/核查，时间相近）= 一个手术事件。"""
    rows = [
        {"REPORTNAME": "麻醉单", "FCKDATE": "2026-08-24 14:30:00",
         "FUPDATE": "2026-08-24 15:00:00", "FLOADDATE": "2026-08-24 15:01:00"},
        {"REPORTNAME": "手术护理单", "FCKDATE": "2026-08-24 15:00:00",
         "FUPDATE": "2026-08-24 16:00:00", "FLOADDATE": "2026-08-24 16:01:00"},
        {"REPORTNAME": "手术清点记录4", "FCKDATE": "2026-08-24 16:00:00",
         "FUPDATE": "2026-08-24 16:30:00", "FLOADDATE": "2026-08-24 16:31:00"},
    ]
    collector = SmCollector(_FakeSmGateway(rows))
    _entries, surgeries = collector.collect("P1", "1")
    assert len(surgeries) == 1, "同台手术的多条手麻文书必须聚为一个事件"
    assert surgeries[0].surgery_time == dt("2026-08-24 14:30:00")   # 最早 FCKDATE


def test_sm_collector_separates_distant_surgeries():
    rows = [
        {"REPORTNAME": "麻醉单", "FCKDATE": "2026-08-24 14:30:00",
         "FUPDATE": "2026-08-24 15:00:00", "FLOADDATE": "2026-08-24 15:01:00"},
        {"REPORTNAME": "麻醉单", "FCKDATE": "2026-08-26 09:00:00",
         "FUPDATE": "2026-08-26 10:00:00", "FLOADDATE": "2026-08-26 10:01:00"},
    ]
    collector = SmCollector(_FakeSmGateway(rows))
    _entries, surgeries = collector.collect("P1", "1")
    assert len(surgeries) == 2, "间隔>6h 的手麻簇=两台手术"
    assert surgeries[1].surgery_time == dt("2026-08-26 09:00:00")


def test_sm_collector_untimed_entries_kept_as_unknown_events():
    rows = [
        {"REPORTNAME": "麻醉单", "FCKDATE": None,
         "FUPDATE": "2026-08-24 15:00:00", "FLOADDATE": "2026-08-24 15:01:00"},
    ]
    collector = SmCollector(_FakeSmGateway(rows))
    _entries, surgeries = collector.collect("P1", "1")
    assert len(surgeries) == 1 and surgeries[0].surgery_time is None
