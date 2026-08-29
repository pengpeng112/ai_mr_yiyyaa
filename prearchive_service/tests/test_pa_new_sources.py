# -*- coding: utf-8 -*-
"""T8-2 新七源 T_ITF 采集器单测。

- config 七源校验过（含 PACS mysql 类型白名单）；
- 可实测源（PACS/ES+US）适配：真实列名/类型差异（PACS varchar 时间、PDFNAME int 忽略）；
- R9：可实测源条目经 PatientContextBuilder 进入 documents 且 source_watermarks 覆盖；
- BLOCKED 两源（病理/心电）骨架实质断言（fixture 行经 adapt_itf_rows 产出
  DocumentEntry，非恒 skip）；
- 接线面六处（常量/名称键/水位/builder/run_service/fixture demo）存在性。
"""
from datetime import datetime

from prearchive.collectors import (
    ItfSourceCollector,
    JhemrCollector,
    HisCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
    adapt_itf_rows,
)
from prearchive.config import DEFAULTS, validate_config
from prearchive.context import (
    NEW_SOURCE_LABELS,
    SRC_BL_ITF,
    SRC_DCN_REPORT,
    SRC_ES_ITF,
    SRC_PACS_ITF,
    SRC_QGJ_ITF,
    SRC_XD_ITF,
    SRC_XT_ITF,
    KNOWN_SOURCE_LABELS,
    WATERMARK_KEYS,
)
from prearchive.fixture_sources import build_demo_fixtures


def test_config_seven_new_sources_all_disabled():
    cfg = validate_config(DEFAULTS)
    for name in ("pacs", "es", "bl", "xt", "xd", "dcn", "qgj"):
        assert name in cfg["sources"]
        assert cfg["sources"][name]["enabled"] is False
    assert cfg["sources"]["pacs"]["type"] == "mysql"     # mysql 入校验白名单


def test_all_seven_labels_in_known_sources():
    for label in NEW_SOURCE_LABELS:
        assert label in KNOWN_SOURCE_LABELS
    assert SRC_XD_ITF in KNOWN_SOURCE_LABELS             # R7：勿漏心电
    for label in NEW_SOURCE_LABELS:
        assert label in WATERMARK_KEYS                   # 水位键覆盖


def test_pacs_adapts_real_column_shapes():
    rows = [
        {"FID": "P1", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "胸部CT平扫报告", "PDFNAME": 100231,
         "FCKDATE": "2026-08-21 11:00:00",   # varchar（连接器实测）
         "FUPDATE": "2026-08-26 11:00:00", "FLOADDATE": "2026-08-26 11:01:00"},
    ]
    entries = adapt_itf_rows(rows, SRC_PACS_ITF)
    assert len(entries) == 1
    assert entries[0].report_name == "胸部CT平扫报告"      # 文本列作名称
    assert entries[0].event_time == datetime(2026, 8, 21, 11, 0)  # varchar 容错解析
    assert "PDFNAME" not in str(entries[0].report_name)    # int 列不进名称


def test_es_us_merged_under_single_label():
    rows = [
        {"FID": "E1", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "胃镜检查报告", "VIEW_TAG": "ES",
         "FCKDATE": "2026-08-22 09:00:00", "FUPDATE": "2026-08-26 09:30:00"},
        {"FID": "U1", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "腹部超声报告", "VIEW_TAG": "US",
         "FCKDATE": "2026-08-23 09:00:00", "FUPDATE": "2026-08-26 09:30:00"},
    ]
    entries = adapt_itf_rows(rows, SRC_ES_ITF)
    assert len(entries) == 2
    assert all(e.source == SRC_ES_ITF for e in entries)   # 双视图合一源标签
    assert {e.raw.get("view_tag") for e in entries} == {"ES", "US"}  # 条目各自独立（raw 键统一小写）


def test_blocked_sources_adapt_skeleton_rows():
    """BLOCKED 两源（病理/心电）骨架实质断言：fixture 行产出 DocumentEntry 非恒 skip。"""
    bl_rows = [
        {"FID": "B1", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "常规石蜡切片病理报告", "FDESC": "BL",
         "FCKDATE": "2026-08-24 10:00:00", "FUPDATE": "2026-08-26 15:00:00"},
    ]
    xd_rows = [
        {"FID": "X1", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "常规十二导联心电图报告", "FDESC": "XD",
         "FCKDATE": "2026-08-21 08:00:00", "FUPDATE": "2026-08-27 09:00:00"},
    ]
    bl_entries = adapt_itf_rows(bl_rows, SRC_BL_ITF)
    xd_entries = adapt_itf_rows(xd_rows, SRC_XD_ITF)
    assert len(bl_entries) == 1 and bl_entries[0].report_name == "常规石蜡切片病理报告"
    assert len(xd_entries) == 1 and xd_entries[0].report_name == "常规十二导联心电图报告"


def test_builder_e2e_documents_and_watermarks_cover_new_sources():
    """R9：可实测源条目进 documents 且 source_watermarks 覆盖（fixture e2e）。"""
    gateways = build_demo_fixtures()
    extras = {}
    for name, label in (("pacs", SRC_PACS_ITF), ("es", SRC_ES_ITF),
                        ("bl", SRC_BL_ITF), ("xt", SRC_XT_ITF),
                        ("xd", SRC_XD_ITF), ("dcn", SRC_DCN_REPORT),
                        ("qgj", SRC_QGJ_ITF)):
        extras[label] = ItfSourceCollector(gateways[name], label)
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
        extra_itf_collectors=extras,
    )
    from prearchive.context import FinishedVisit
    ctx = builder.build(FinishedVisit(
        patient_id="TEST0001", visit_id="1",
        finished_date_time=datetime(2026, 8, 26, 10, 0, 0)))
    by_source = {}
    for e in ctx.documents:
        by_source[e.source] = by_source.get(e.source, 0) + 1
    assert by_source.get(SRC_PACS_ITF) == 1     # 胸部CT
    assert by_source.get(SRC_ES_ITF) == 1       # 胃镜（超声属 TEST0002）
    assert by_source.get(SRC_BL_ITF) == 1
    assert by_source.get(SRC_XT_ITF) == 1
    for key in ("pacs", "es", "bl", "xt"):
        assert key in ctx.source_watermarks     # 该患者命中的源水位已覆盖
    # 时间基准真实可解析
    assert ctx.source_watermarks["pacs"] == datetime(2026, 8, 26, 11, 0, 0)  # time_basis=update_time 优先


def test_run_service_wiring_table_exists():
    """接线面④：run_service NEW_SOURCE_WIRING 七源齐（R9 防死代码）。"""
    import run_service
    source = open(run_service.__file__, encoding="utf-8").read()
    for token in ("SqlPacsGateway", "SqlEsGateway", "SqlBlGateway", "SqlXtGateway",
                  "SqlXdGateway", "SqlDcnGateway", "SqlQgjGateway"):
        assert token in source
    assert source.count("NEW_SOURCE_WIRING") >= 2


def test_fixture_demo_covers_all_seven():
    gateways = build_demo_fixtures()
    for name in ("pacs", "es", "bl", "xt", "xd", "dcn", "qgj"):
        assert name in gateways
        assert gateways[name].fetch_itf_entries("TEST0001", "1") is not None
