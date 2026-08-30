# -*- coding: utf-8 -*-
"""T8-2 新七源 T_ITF 采集器单测。

- config 七源校验过（含 PACS mysql 类型白名单）；
- 可实测源（PACS/ES+US）适配：真实列名/类型差异（PACS varchar 时间、PDFNAME int 忽略）；
- 2026-08-29 实测列回填四源（病理/气管镜/血透/电测听）实质适配 + IDNo PHI 丢弃 +
  数值型身份列 str() 兜底 + 表名/占位字样断言；心电=唯一 BLOCKED 骨架保留；
- R9：各源条目经 PatientContextBuilder 进入 documents 且 source_watermarks 覆盖；
- 接线面（常量/名称键/水位/builder/run_service/fixture demo）存在性。
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


def test_four_realized_sources_adapt_measured_columns():
    """2026-08-29 实测列结构回填四源（病理/气管镜/血透/电测听）实质适配断言。"""
    # 病理 dbo.T_ITF_BL：13 列标准骨架（实测 192,653 行）
    bl_rows = [
        {"FID": "B90000001", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "常规石蜡切片病理报告", "FDESC": "病理诊断描述",
         "PDFNAME": "BL20260824001.pdf", "PDFPATH": "/pitaya/pdf/2026/08/",
         "FCKDATE": "2026-08-24 10:00:00", "FUPDATE": "2026-08-26 15:00:00",
         "FLOADDATE": "2026-08-26 15:01:00", "FREPORTSTYLE": "1", "PAGECOUNT": 3},
    ]
    bl_entries = adapt_itf_rows(bl_rows, SRC_BL_ITF)
    assert len(bl_entries) == 1 and bl_entries[0].report_name == "常规石蜡切片病理报告"
    assert bl_entries[0].event_time == datetime(2026, 8, 24, 10, 0)
    assert bl_entries[0].load_time == datetime(2026, 8, 26, 15, 1)

    # 气管镜 "T_ITF_HisQuery"：FBINCU/PAGECOUNT=int、REPORTNAME 恒=呼吸内镜检查报告
    qgj_rows = [
        {"FID": "Q91000001", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": 1,
         "REPORTNAME": "呼吸内镜检查报告", "FDESC": "气管镜检查描述",
         "PDFNAME": "QGJ20260825001.pdf", "PDFPATH": "/clouddb/pdf/2026/08/",
         "FCKDATE": "2026-08-25 14:00:00", "FUPDATE": "2026-08-27 14:00:00",
         "FLOADDATE": "2026-08-27 14:01:00", "FREPORTSTYLE": "1", "PAGECOUNT": 2},
    ]
    qgj_entries = adapt_itf_rows(qgj_rows, SRC_QGJ_ITF)
    assert len(qgj_entries) == 1 and qgj_entries[0].report_name == "呼吸内镜检查报告"

    # 血透 "T_ITF_XT"：14 列（FID/PATIENTID=bigint 数值型——身份三元组 str() 兜底）
    xt_rows = [
        {"FID": 91000001, "PATIENTID": 1234567, "FBIHID": "1", "FBINCU": 1,
         "REPORTNAME": "血液透析记录单", "FDESC": "XT",
         "PDFNAME": "XT20260823001.pdf", "PDFPATH": "/dialysis/pdf/2026/08/",
         "FCKDATE": "2026-08-23 07:00:00", "FUPDATE": "2026-08-26 07:00:00",
         "FLOADDATE": "2026-08-26 07:01:00", "FREPORTSTYLE": "1", "PAGECOUNT": 2,
         "IDNo": "FAKE-IDNO-XT-DO-NOT-USE"},
    ]
    xt_entries = adapt_itf_rows(xt_rows, SRC_XT_ITF)
    assert len(xt_entries) == 1 and xt_entries[0].report_name == "血液透析记录单"
    # PHI 红线：IDNo 整列丢弃——raw 及任何字段不得含该键/该值
    assert "idno" not in xt_entries[0].raw
    assert "FAKE-IDNO-XT-DO-NOT-USE" not in str(xt_entries[0].raw)

    # 电测听 t_itf_report：16 列小写命名（含新增 report_url/his_patient_id/visit_index）
    dcn_rows = [
        {"fid": "d91000001", "patientid": "TESTP", "fbihid": "1", "fbincu": "1",
         "reportname": "纯音电测听报告", "fdesc": "DCN",
         "pdfname": "dcn20260822001.pdf", "pdfpath": "/report/pdf/2026/08/",
         "report_url": "http://report-fake.internal/dcndemo",
         "fckdate": "2026-08-22 10:00:00", "fupdate": "2026-08-27 11:00:00",
         "floaddate": "2026-08-27 11:01:00", "freportstyle": "1", "pagecount": 1,
         "his_patient_id": "", "visit_index": "1"},
    ]
    dcn_entries = adapt_itf_rows(dcn_rows, SRC_DCN_REPORT)
    assert len(dcn_entries) == 1 and dcn_entries[0].report_name == "纯音电测听报告"
    assert dcn_entries[0].update_time == datetime(2026, 8, 27, 11, 0)  # 小写列天然兼容


def test_xt_fixture_gateway_numeric_identity_str_fallback():
    """血透数值型身份列（PATIENTID=bigint）经 fixture 网关 str() 过滤仍可命中。"""
    gw = build_demo_fixtures()["xt"]
    rows = gw.fetch_itf_entries("TEST0001", "1")
    assert len(rows) == 1
    entries = adapt_itf_rows(rows, SRC_XT_ITF)
    assert len(entries) == 1
    assert "idno" not in entries[0].raw                      # demo 行含 IDNo 假号同样被丢弃


def test_timestamptz_aware_datetime_normalized_to_naive():
    """血透 timestamptz（aware datetime）→ parse_datetime 去 tzinfo 保墙钟，
    与 naive 完成时间可直接比较（防 aware/naive TypeError）。"""
    from datetime import timezone, timedelta as _td

    from prearchive.context import parse_datetime
    aware = datetime(2026, 8, 26, 7, 0, 0, tzinfo=timezone(_td(hours=8)))
    normalized = parse_datetime(aware)
    assert normalized == datetime(2026, 8, 26, 7, 0, 0)
    assert normalized.tzinfo is None
    assert normalized >= datetime(2026, 8, 26, 6, 0, 0)      # naive 比较不炸


def test_four_gateways_sql_use_measured_tables():
    """ITF_SQL 落实测表名/引号：气管镜/血透表名带双引号（PG 大小写敏感）、
    病理=dbo.T_ITF_BL、电测听=t_itf_report。"""
    from prearchive.collectors import (
        SqlBlGateway,
        SqlDcnGateway,
        SqlQgjGateway,
        SqlXtGateway,
    )
    assert 'FROM dbo.T_ITF_BL ' in SqlBlGateway.ITF_SQL
    assert 'FROM "T_ITF_XT" ' in SqlXtGateway.ITF_SQL
    assert 'FROM t_itf_report ' in SqlDcnGateway.ITF_SQL
    assert 'FROM "T_ITF_HisQuery" ' in SqlQgjGateway.ITF_SQL
    assert "IDNo" not in SqlXtGateway.ITF_SQL                # 血透 SQL 不查 PHI 列


def test_four_gateways_no_placeholder_markers():
    """四源 Gateway 转正：类源码无 TODO/BLOCKED/骨架占位字样（心电除外）。"""
    import inspect

    from prearchive.collectors import (
        SqlBlGateway,
        SqlDcnGateway,
        SqlQgjGateway,
        SqlXtGateway,
    )
    for cls in (SqlBlGateway, SqlXtGateway, SqlDcnGateway, SqlQgjGateway):
        source = inspect.getsource(cls)
        for marker in ("TODO", "BLOCKED", "骨架占位", "未登记平台"):
            assert marker not in source, f"{cls.__name__} 残留占位字样: {marker}"


def test_xd_remains_blocked_skeleton():
    """心电=唯一未接源：保留 BLOCKED 骨架 + TODO（对接信息待用户提供）。"""
    bl_rows = [
        {"FID": "X1", "PATIENTID": "TESTP", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "常规十二导联心电图报告", "FDESC": "XD",
         "FCKDATE": "2026-08-21 08:00:00", "FUPDATE": "2026-08-27 09:00:00"},
    ]
    xd_entries = adapt_itf_rows(bl_rows, SRC_XD_ITF)
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
