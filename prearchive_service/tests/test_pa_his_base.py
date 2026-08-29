# -*- coding: utf-8 -*-
"""T8-3 基本信息视图单测。

- 三视图 gateway + fixture 单测（VW_user_info/VW_dept_dict/VW_pats_out_hospital）；
- 映射注入接口：VW_user_info fixture 跑通一条工号→人员链路（receivers 集成）；
- 科室名规范化；
- 默认 disabled 不影响现状。
"""
from prearchive.config import DEFAULTS, validate_config
from prearchive.context import PatientContext
from prearchive.his_base import (
    FixtureHisBaseGateway,
    make_userid_mapper_from_his_base,
    normalize_dept_name,
)
from prearchive.receivers import DefaultReceiverResolver


def test_three_views_fixture_gateway():
    gw = FixtureHisBaseGateway()
    user = gw.fetch_user_by_code("TESTDOC01")
    assert user is not None
    assert user["user_name"] == "测试医生甲"
    assert user["active"] is True
    assert gw.fetch_user_by_code("NO_SUCH") is None

    depts = gw.fetch_dept_dict()
    assert {d["dept_name"] for d in depts} >= {"普外科", "呼吸内科"}

    discharged = gw.fetch_discharged_patients("2026-08-01", "2026-08-31")
    assert len(discharged) == 1 and discharged[0]["patient_id"] == "TEST0001"
    assert gw.fetch_discharged_patients("2026-09-01", "2026-09-30") == []


def test_userid_mapper_chain_via_receivers():
    """工号→人员链路：mapper 注入 receivers，wecom_userid 优先/停用不下探/未知工号 None。"""
    gw = FixtureHisBaseGateway()
    mapper = make_userid_mapper_from_his_base(gw)

    assert mapper("TESTDOC02") == "wecom-TESTDOC02"   # 视图含企微号：优先
    assert mapper("TESTDOC01") == "TESTDOC01"          # 无企微号：回落工号
    assert mapper("TESTDOC09") is None                 # 停用：不下探
    assert mapper("UNKNOWN01") is None                 # 未知工号：不透传

    ctx = PatientContext(patient_id="TESTP", visit_id="1",
                         first_finished_doctor_id="TESTDOC02")
    resolver = DefaultReceiverResolver(userid_mapper=mapper)
    receiver = resolver.resolve(ctx)
    assert receiver is not None
    assert receiver.user_id == "wecom-TESTDOC02"       # 链路跑通一条


def test_normalize_dept_name():
    gw = FixtureHisBaseGateway()
    rows = gw.fetch_dept_dict()
    assert normalize_dept_name(rows, "普外科") == "普外科"
    assert normalize_dept_name(rows, "  普外科 ") == "普外科"
    assert normalize_dept_name(rows, "不存在科室") == "不存在科室"   # fail-open


def test_his_base_defaults_disabled():
    cfg = validate_config(DEFAULTS)
    assert cfg["sources"]["his_base"]["enabled"] is False
    assert cfg["sources"]["his_base"]["host"].startswith("<")
