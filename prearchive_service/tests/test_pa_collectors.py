# -*- coding: utf-8 -*-
"""采集器单测：fixture 网关、行归一化、四源名称列适配（LIS=FDESCNUM 等）。"""

from datetime import datetime

from prearchive.collectors import (
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
    adapt_itf_rows,
    normalize_rows_lower,
    compute_source_watermarks,
    source_is_ready,
)
from prearchive.context import (
    SRC_HIS_ITF,
    SRC_LIS_ITF,
    SRC_SM_ITF,
)
from prearchive.fixture_sources import (
    FixtureHisGateway,
    FixtureJhemrGateway,
    FixtureLisGateway,
    FixtureSmGateway,
    build_demo_fixtures,
)

from helpers import dt


# ---------------------------------------------------------------------------
# 行归一化（Vastbase 大写列名坑）
# ---------------------------------------------------------------------------
def test_normalize_rows_lower():
    rows = [{"PATIENTID": "P1", "FINISHED_DATE_TIME": "2026-08-26 10:00:00"}]
    out = normalize_rows_lower(rows)
    assert out[0]["patientid"] == "P1"
    assert out[0]["finished_date_time"].startswith("2026-08-26")


def test_normalize_rows_lower_with_column_map():
    rows = [{"PATIENT_ID": "P1", "DEPT_CODE": "D1"}]
    out = normalize_rows_lower(rows, {"patient_id": "patient_id", "dept_code": "dept_code"})
    assert out[0]["patient_id"] == "P1"


# ---------------------------------------------------------------------------
# T_ITF 适配：源差异（F3 v2）
# ---------------------------------------------------------------------------
def test_his_reportname_numeric_code_preserved():
    rows = [{"FID": "1", "PATIENTID": "P1", "FBIHID": "1", "REPORTNAME": 1,
             "FCKDATE": "2026-08-20 09:00:00", "FUPDATE": "2026-08-26 10:00:00",
             "FLOADDATE": "2026-08-26 10:01:00"}]
    entries = adapt_itf_rows(rows, SRC_HIS_ITF)
    assert len(entries) == 1
    assert entries[0].report_name == "1"      # F4：数字编码原样保留，字典待 P0-3①
    assert entries[0].update_time == dt("2026-08-26 10:00:00")


def test_sm_reportname_is_name_column():
    """P0-3② 实测：手麻 T_ITF_SM 名称列=REPORTNAME（无 FITEMNAME；FDESC 为 10 字符编码）。"""
    rows = [{"FID": "2", "PATIENTID": "P1", "FBIHID": "1",
             "REPORTNAME": "安全核查单", "FDESC": "HC",
             "FCKDATE": None, "FUPDATE": None, "FLOADDATE": None}]
    entries = adapt_itf_rows(rows, SRC_SM_ITF)
    assert entries[0].report_name == "安全核查单"


def test_lis_fdescnum_category_used_and_fdesc_ignored():
    """LIS FDESCNUM=检验类别（P0-3② 实测 15 类）；FITEMNAME=项目名兜底；无 FDESC 列。"""
    rows = [{"FID": "3", "PATIENTID": "P1", "FBIHID": "1",
             "FDESCNUM": "临检血液", "FITEMNAME": "血液分析(紫管)",
             "FCKDATE": None, "FUPDATE": None, "FLOADDATE": None}]
    entries = adapt_itf_rows(rows, SRC_LIS_ITF)
    assert len(entries) == 1
    assert entries[0].report_name == "临检血液"

    # FDESCNUM 空时回退 FITEMNAME（项目名）
    rows2 = [{"FID": "4", "PATIENTID": "P1", "FBIHID": "1",
              "FDESCNUM": "", "FITEMNAME": "凝血四项",
              "FCKDATE": None, "FUPDATE": None, "FLOADDATE": None}]
    assert adapt_itf_rows(rows2, SRC_LIS_ITF)[0].report_name == "凝血四项"


def test_itf_rows_without_name_skipped():
    rows = [{"FID": "4", "PATIENTID": "P1", "FBIHID": "1", "FDESCNUM": "  "}]
    assert adapt_itf_rows(rows, SRC_LIS_ITF) == []


# ---------------------------------------------------------------------------
# fixture 网关 + 采集器
# ---------------------------------------------------------------------------
def test_fixture_jhemr_finished_filtering_and_parse():
    gateways = build_demo_fixtures()
    collector = JhemrCollector(gateways["jhemr"])

    visits = collector.fetch_finished_visits(None, 100)
    assert len(visits) == 3
    assert all(isinstance(v.finished_date_time, datetime) for v in visits)
    assert [v.patient_id for v in visits] == ["TEST0001", "TEST0002", "TEST0003"]

    # since 过滤：只取 2026-08-27 之后的
    later = collector.fetch_finished_visits(dt("2026-08-27 00:00:00"), 100)
    assert {v.patient_id for v in later} == {"TEST0002", "TEST0003"}

    # limit 生效
    assert len(collector.fetch_finished_visits(None, 2)) == 2


def test_jhemr_collector_load_part_context():
    gateways = build_demo_fixtures()
    collector = JhemrCollector(gateways["jhemr"])
    visit = collector.fetch_finished_visits(None, 1)[0]
    ctx = collector.load_part(visit.patient_id, visit.visit_id, visit)
    assert ctx.dept_code == "D001"
    assert ctx.first_finished_doctor_id == "TESTDOC01"
    assert ctx.admit_time == dt("2026-08-20 08:30:00")
    assert ctx.finished_date_time == visit.finished_date_time
    templates = [d.template_name for d in ctx.documents]
    assert "入院记录" in templates and "手术知情同意书" in templates
    assert all(d.source == "jhemr_blws" for d in ctx.documents)


def test_his_collector_firstpage_none_means_unavailable():
    gateway = FixtureHisGateway(
        itf_entries=[{"FID": "H", "PATIENTID": "P9", "FBIHID": "1", "REPORTNAME": "1",
                      "FCKDATE": None, "FUPDATE": None, "FLOADDATE": None}],
        firstpages={"P9|1": None},
    )
    entries, firstpage, surgeries = HisCollector(gateway).collect("P9", "1")
    assert entries[0].report_name == "1"
    assert firstpage.available is False
    assert surgeries == []


def test_sm_collector_surgery_evidence():
    gateway = FixtureSmGateway([
        {"FID": "S", "PATIENTID": "P9", "FBIHID": "1", "REPORTNAME": "麻醉单",
         "FDESC": "MZ", "FCKDATE": "2026-08-23 14:00:00",
         "FUPDATE": None, "FLOADDATE": None},
    ])
    entries, surgeries = SmCollector(gateway).collect("P9", "1")
    assert surgeries and surgeries[0].surgery_time == dt("2026-08-23 14:00:00")
    assert surgeries[0].source == "sm_itf_entry"


def test_lis_collector_collect_uses_fdescnum():
    gateway = FixtureLisGateway([
        {"FID": "L", "PATIENTID": "P9", "FBIHID": "1", "FDESCNUM": "体液",
         "FITEMNAME": "尿液分析", "FCKDATE": None, "FUPDATE": None, "FLOADDATE": None},
    ])
    entries = LisCollector(gateway).collect("P9", "1")
    assert [e.report_name for e in entries] == ["体液"]


# ---------------------------------------------------------------------------
# 聚合与水位
# ---------------------------------------------------------------------------
def test_context_builder_fail_open_on_source_error():
    """单源抛异常不阻断整检：记录 collect_errors，其余源照常。"""

    class BrokenSm(FixtureSmGateway):
        def fetch_itf_entries(self, patient_id, visit_id):
            raise RuntimeError("sm down")

    gateways = build_demo_fixtures()
    broken = BrokenSm([])
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(broken),
        lis=LisCollector(gateways["lis"]),
    )
    visit = JhemrCollector(gateways["jhemr"]).fetch_finished_visits(None, 1)[0]
    ctx = builder.build(visit)
    assert "sm" in ctx.collect_errors
    assert any(e.source == SRC_HIS_ITF for e in ctx.documents)      # HIS 正常
    assert any(e.source == SRC_LIS_ITF for e in ctx.documents)      # LIS 正常
    assert not any(e.source == SRC_SM_ITF for e in ctx.documents)   # SM 失败留空


def test_source_watermarks_and_readiness():
    gateways = build_demo_fixtures()
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    visits = {v.patient_id: v
              for v in JhemrCollector(gateways["jhemr"]).fetch_finished_visits(None, 10)}

    ctx1 = builder.build(visits["TEST0001"])
    # 张某：SM fupdate=10:40 ≥ finished 10:00 → 就绪
    assert ctx1.source_watermarks["sm"] == dt("2026-08-26 10:40:00")
    assert source_is_ready(ctx1, "sm_itf") is True

    # 手工构造未就绪：SM 水位早于完成时间 → 不判缺（require_source_ready 负例基础）
    ctx2 = builder.build(visits["TEST0001"])
    ctx2.source_watermarks["sm"] = dt("2026-08-26 09:00:00")
    assert source_is_ready(ctx2, "sm_itf") is False

    # 水位缺失（源无任何条目）→ 未就绪
    ctx3 = builder.build(visits["TEST0001"])
    ctx3.source_watermarks.pop("lis")
    assert source_is_ready(ctx3, "lis_itf") is False
