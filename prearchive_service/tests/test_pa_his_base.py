# -*- coding: utf-8 -*-
"""T8-3 HIS 基本信息视图单测（2026-08-29 实测列结构回填版）。

- 三视图 gateway + fixture 单测（VW_user_info FID=工号/FDOCT=科室名称等实测语义）；
- HisBaseUserIdMapper 三态：命中（企微优先/回落工号）/查无与停用（None 下探兜底链）/
  开关关闭不查（默认 passthrough 现状不变）；
- HisBaseDeptNormalizer 代码→名称 + 科室名规范化；
- config 开关校验（userid_mapper_source/dept_normalizer_source 白名单）。
"""
from prearchive.config import DEFAULTS, validate_config
from prearchive.context import PatientContext
from prearchive.his_base import (
    FixtureHisBaseGateway,
    HisBaseDeptNormalizer,
    SqlHisBaseGateway,
    make_userid_mapper_from_his_base,
    normalize_dept_name,
    normalize_user_row,
)
from prearchive.receivers import (
    DefaultReceiverResolver,
    HisBaseUserIdMapper,
    passthrough_userid_mapper,
)


def test_three_views_fixture_gateway_measured_columns():
    """fixture 行=VW_* 实测列名（FID/FNAME/FDEPT/FDOCT…），归一化映射正确。"""
    gw = FixtureHisBaseGateway()
    user = gw.fetch_user_by_code("TESTDOC01")
    assert user is not None
    assert user["user_code"] == "TESTDOC01"        # FID=工号
    assert user["user_name"] == "测试医生甲"          # FNAME=姓名
    assert user["dept_code"] == "D001"              # FDEPT=科室代码
    assert user["dept_name"] == "普外科"             # FDOCT=科室名称（非医生标志位）
    assert user["active"] is True                   # 实测视图无 active 列→缺省有效
    assert user["wecom_userid"] == ""               # 实测视图无企微列
    assert gw.fetch_user_by_code("NO_SUCH") is None

    users = gw.fetch_user_info()                    # 全量通道（4,278 行级）
    assert len(users) == 3
    assert normalize_user_row(users[1])["dept_name"] == "呼吸内科"

    depts = gw.fetch_dept_dict()
    assert {d["FNAME"] for d in depts} >= {"普外科", "呼吸内科"}

    sample = gw.fetch_out_hospital_sample(limit=10)
    assert len(sample) == 1 and sample[0]["FPATIENTID"] == "TEST0001"
    assert sample[0]["FGUIDANGDATE"] == "2026-08-31"   # 归档日期列在位
    assert gw.fetch_out_hospital_sample(limit=0) == []


def test_sql_gateway_uses_measured_views_and_columns():
    """SqlHisBaseGateway SQL=实测视图/列（hisuser.VW_*、FID/FNAME/FDEPT/FDOCT…）。"""
    assert "hisuser.VW_user_info" in SqlHisBaseGateway.USER_SQL
    assert "FDOCT" in SqlHisBaseGateway.USER_SQL          # 科室名称列（实测语义）
    assert "hisuser.VW_dept_dict" in SqlHisBaseGateway.DEPT_SQL
    assert "hisuser.VW_pats_out_hospital" in SqlHisBaseGateway.OUT_HOSPITAL_SQL
    assert "FGUIDANGDATE" in SqlHisBaseGateway.OUT_HOSPITAL_SQL   # 归档日期列在位
    assert "FETCH FIRST :limit" in SqlHisBaseGateway.OUT_HOSPITAL_SQL


def test_userid_mapper_three_states():
    """三态：命中（企微优先/回落工号）/查无与停用 None/异常 fail-open None。"""
    gw = FixtureHisBaseGateway()
    mapper = HisBaseUserIdMapper(gw)

    assert mapper("TESTDOC01") == "TESTDOC01"      # 无企微号：回落工号（实测视图恒此态）
    assert mapper("TESTDOC09") is None             # 停用：不下探透传
    assert mapper("UNKNOWN01") is None             # 未知工号：不透传
    assert mapper("") is None                      # 空工号

    # 企微号优先路径：视图若含 wecom_userid 列（实测暂无，预留语义）则优先返回
    gw_wecom = FixtureHisBaseGateway(users=[{
        "FID": "TESTDOC02", "FNAME": "测试医生乙", "FDEPT": "D002", "FDOCT": "呼吸内科",
        "FPOSITION": "主治医师", "FUSERTYPE": "医生", "wecom_userid": "wecom-TESTDOC02"}])
    assert HisBaseUserIdMapper(gw_wecom)("TESTDOC02") == "wecom-TESTDOC02"

    class _Boom:
        def fetch_user_by_code(self, code):
            raise RuntimeError("db down")

    assert HisBaseUserIdMapper(_Boom())("TESTDOC01") is None   # 查询异常 fail-open


def test_userid_mapper_chain_via_receivers_fallback():
    """查无返回 None → DefaultReceiverResolver 下探兜底链（管床接住）。"""
    gw = FixtureHisBaseGateway()
    mapper = HisBaseUserIdMapper(gw)

    # 首选完成医生不在视图 → 下探管床（在视图）接住，标记 is_fallback
    ctx = PatientContext(patient_id="TESTP", visit_id="1",
                         first_finished_doctor_id="GONE01",
                         attending_doctor_id="TESTDOC01")
    resolver = DefaultReceiverResolver(userid_mapper=mapper)
    receiver = resolver.resolve(ctx)
    assert receiver is not None
    assert receiver.via == "attending_doctor"
    assert receiver.user_id == "TESTDOC01" and receiver.is_fallback is True

    # 兼容旧工厂函数（等价 HisBaseUserIdMapper）
    mapper2 = make_userid_mapper_from_his_base(gw)
    assert mapper2("TESTDOC02") == "TESTDOC02"


def test_default_passthrough_unchanged():
    """默认开关=passthrough：不查视图，工号即 userid（现状行为不变）。"""
    cfg = validate_config(DEFAULTS)
    assert cfg["receiver"]["userid_mapper_source"] == "passthrough"
    assert cfg["receiver"]["dept_normalizer_source"] == "off"
    assert passthrough_userid_mapper("ANY01") == "ANY01"


def test_dept_normalizer_code_to_name():
    gw = FixtureHisBaseGateway()
    normalizer = HisBaseDeptNormalizer(gw.fetch_dept_dict())
    assert normalizer.name_for_code("D001") == "普外科"
    assert normalizer.name_for_code("D003") == "心脏大血管外科"
    assert normalizer.name_for_code("ZZZ") == "ZZZ"      # 未命中 fail-open 返回原代码
    assert normalizer.name_for_code("") == ""


def test_normalize_dept_name():
    gw = FixtureHisBaseGateway()
    rows = gw.fetch_dept_dict()
    assert normalize_dept_name(rows, "普外科") == "普外科"
    assert normalize_dept_name(rows, "  普外科 ") == "普外科"
    assert normalize_dept_name(rows, "不存在科室") == "不存在科室"   # fail-open
    normalizer = HisBaseDeptNormalizer(rows)
    assert normalizer.normalize_name("  普外科 ") == "普外科"


def test_config_rejects_unknown_mapper_source():
    bad = {"service": {"poll_interval_seconds": 60, "batch_limit": 10},
           "receiver": {"userid_mapper_source": "ldap"}}
    import pytest
    from prearchive.config import ConfigError
    with pytest.raises(ConfigError):
        validate_config(bad)
    bad2 = {"service": {"poll_interval_seconds": 60, "batch_limit": 10},
            "receiver": {"dept_normalizer_source": "emr"}}
    with pytest.raises(ConfigError):
        validate_config(bad2)


def test_run_service_wires_hisbase_switch():
    """接线面：run_service 源码含开关消费与 HisBaseUserIdMapper/Normalizer 构造。"""
    import run_service
    source = open(run_service.__file__, encoding="utf-8").read()
    for token in ("userid_mapper_source", "dept_normalizer_source",
                  "HisBaseUserIdMapper", "HisBaseDeptNormalizer",
                  "FixtureHisBaseGateway", "SqlHisBaseGateway"):
        assert token in source, f"run_service 缺接线: {token}"


def test_build_stack_hisbase_switch_fixture_chain(tmp_path):
    """build_stack 级接线：hisbase 开启（fixtures 模式）resolver 用 HisBaseUserIdMapper
    且 pusher 带科室规范化器；默认 passthrough/off 两者均不启用（现状不变）。"""
    import copy
    import json

    import run_service
    from prearchive.config import DEFAULTS, validate_config
    from prearchive.his_base import HisBaseDeptNormalizer
    from prearchive.receivers import HisBaseUserIdMapper, passthrough_userid_mapper

    rules_dir = str(__import__("pathlib").Path(run_service.__file__).parent / "rules")

    def _stack(receiver_overrides):
        config = copy.deepcopy(DEFAULTS)
        config["receiver"].update(receiver_overrides)
        config["rules"]["rules_file"] = f"{rules_dir}/example_rules.json"
        config["rules"]["extra_rules_files"] = [f"{rules_dir}/system_push_rules.json"]
        config = validate_config(config)
        cfg_path = tmp_path / f"config_{len(list(tmp_path.iterdir()))}.json"
        cfg_path.write_text(json.dumps(config), encoding="utf-8")
        return run_service.build_stack(config, str(cfg_path), fixtures=True)

    # 默认：passthrough/off —— 行为与现状完全一致
    poller, _repo, _hb, _st = _stack({})
    pusher = poller.processor.pusher
    assert pusher.resolver.userid_mapper is passthrough_userid_mapper
    assert pusher.dept_normalizer is None

    # hisbase 开启：fixture 链路映射正确
    poller2, _repo2, _hb2, _st2 = _stack({"userid_mapper_source": "hisbase",
                                          "dept_normalizer_source": "hisbase"})
    pusher2 = poller2.processor.pusher
    assert isinstance(pusher2.resolver.userid_mapper, HisBaseUserIdMapper)
    assert isinstance(pusher2.dept_normalizer, HisBaseDeptNormalizer)
    assert pusher2.resolver.userid_mapper("TESTDOC01") == "TESTDOC01"   # 命中回落工号
    assert pusher2.resolver.userid_mapper("UNKNOWN01") is None          # 查无→下探兜底
    assert pusher2.dept_normalizer.name_for_code("D002") == "呼吸内科"


def test_his_base_defaults_disabled():
    cfg = validate_config(DEFAULTS)
    assert cfg["sources"]["his_base"]["enabled"] is False
    assert cfg["sources"]["his_base"]["host"].startswith("<")
