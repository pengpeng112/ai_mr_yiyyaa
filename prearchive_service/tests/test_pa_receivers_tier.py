# -*- coding: utf-8 -*-
"""推送对象降级档位单测（031 T2-2）。

- 默认 fallback_order 不变（first_finished_doctor → attending_doctor）；
- 新档 doc_author（文书书写医生）仅显式配置才生效；
- doctor_guid 缺失时跳过该档下探；企微映射函数保持可注入 mock。
"""
from datetime import datetime

from prearchive.collectors import JhemrCollector
from prearchive.context import FinishedVisit, PatientContext
from prearchive.fixture_sources import FixtureJhemrGateway
from prearchive.receivers import DefaultReceiverResolver, FALLBACK_ORDER


def _ctx(**overrides):
    base = dict(
        patient_id="TEST0001", visit_id="1",
        first_finished_doctor_id="", first_finished_doctor_name="",
        attending_doctor_id="", attending_doctor_name="",
        last_doc_author_id="", last_doc_author_name="",
    )
    base.update(overrides)
    return PatientContext(**base)


def test_default_fallback_order_unchanged():
    assert FALLBACK_ORDER == ("first_finished_doctor", "attending_doctor")
    resolver = DefaultReceiverResolver()
    assert "doc_author" not in resolver.fallback_order


def test_doc_author_tier_used_when_configured():
    # 完成医生无数据（029 P0-6 现状）→ 配置 doc_author 档后由文书医生接住
    ctx = _ctx(last_doc_author_id="TESTAUTH01", last_doc_author_name="文书医生甲")
    resolver = DefaultReceiverResolver(
        fallback_order=("first_finished_doctor", "doc_author", "attending_doctor"))
    receiver = resolver.resolve(ctx)
    assert receiver is not None
    assert receiver.via == "doc_author"
    assert receiver.doctor_id == "TESTAUTH01"
    assert receiver.user_id == "TESTAUTH01"     # passthrough 映射
    assert receiver.is_fallback is True


def test_doc_author_missing_falls_through_to_attending():
    # doctor_guid 缺失：跳过 doc_author 档，继续下探管床
    ctx = _ctx(attending_doctor_id="TESTATT02", attending_doctor_name="管床医生乙")
    resolver = DefaultReceiverResolver(
        fallback_order=("first_finished_doctor", "doc_author", "attending_doctor"))
    receiver = resolver.resolve(ctx)
    assert receiver is not None
    assert receiver.via == "attending_doctor"


def test_default_order_ignores_doc_author_data():
    # 默认顺序不含 doc_author：即使有文书作者数据也不用（现状行为不破）
    ctx = _ctx(last_doc_author_id="TESTAUTH01",
               attending_doctor_id="TESTATT02", attending_doctor_name="管床乙")
    receiver = DefaultReceiverResolver().resolve(ctx)
    assert receiver.via == "attending_doctor"


def test_mapper_is_injectable():
    calls = []

    def mapper(doctor_id):
        calls.append(doctor_id)
        return None if doctor_id == "TESTAUTH01" else f"u-{doctor_id}"

    ctx = _ctx(last_doc_author_id="TESTAUTH01",
               attending_doctor_id="TESTATT02")
    resolver = DefaultReceiverResolver(
        userid_mapper=mapper,
        fallback_order=("doc_author", "attending_doctor"))
    receiver = resolver.resolve(ctx)
    # 映射失败的档继续下探
    assert calls == ["TESTAUTH01", "TESTATT02"]
    assert receiver.via == "attending_doctor"
    assert receiver.user_id == "u-TESTATT02"


def test_blws_latest_author_aggregation():
    # 采集器聚合最新文书作者：按 update_time 最新的 doctor_guid
    pat_visits = [{
        "patient_id": "TEST0009", "visit_id": "1", "visit_number": "1",
        "patient_name": "赵某某", "dept_code": "D001", "dept_name": "普外科",
        "finished_date_time": "2026-08-27 10:00:00",
    }]
    blws = {
        "TEST0009|1": [
            {"progress_template_name": "入院记录", "progress_status": "完成",
             "record_time": "2026-08-20 09:00:00", "finished_time": "2026-08-20 09:00:00",
             "update_time": "2026-08-20 09:00:00",
             "doctor_guid": "TESTOLD01", "doctor_name": "早期作者"},
            {"progress_template_name": "手术记录", "progress_status": "完成",
             "record_time": "2026-08-24 16:00:00", "finished_time": "2026-08-24 16:00:00",
             "update_time": "2026-08-26 18:00:00",
             "doctor_guid": "TESTNEW02", "doctor_name": "最新作者"},
        ],
    }
    collector = JhemrCollector(FixtureJhemrGateway(pat_visits, blws))
    visit = collector.fetch_finished_visits(None, 10)[0]
    ctx = collector.load_part("TEST0009", "1", visit)
    assert ctx.last_doc_author_id == "TESTNEW02"
    assert ctx.last_doc_author_name == "最新作者"
    assert isinstance(ctx.finished_date_time, datetime)
