# -*- coding: utf-8 -*-
"""012 P2 草案测试：双源 Builder（progress_nursing_multi_source）。"""
from datetime import datetime

import pytest

from app.services.data_source_loader import PatientBundle
from app.services.progress_nursing_multi_source_builder import (
    BUILDER_NAME,
    _MAX_TOTAL_CHARS,
    build_progress_nursing_multi_source_payload,
    register_dual_source_builder,
)


class _Payload:
    def __init__(self, builder=BUILDER_NAME, **values):
        self._d = {"builder": builder, **values}

    def model_dump(self):
        return dict(self._d)


class _AuditType:
    code = "progress_vs_nursing"
    name = "病程与护理"

    def __init__(self, builder=BUILDER_NAME, **values):
        self.payload = _Payload(builder, **values)


def _bundle(progress_records, nursing_records):
    return PatientBundle(
        bundle_id="P-1::3",
        group_values={"patient_id": "P-1", "visit_number": "3"},
        sources={"progress": progress_records, "nursing": nursing_records},
        primary_source="progress",
        query_date="2026-08-04",
    )


def _progress(content="病程正文", **overrides):
    base = dict(
        record_id="F-1", record_subtype="daily_progress", record_name="日常病程记录",
        content=content, event_time=datetime(2026, 8, 4, 10, 0),
        source_status="ok", mapping_version="progress-scope-mapping-v1-20260808",
    )
    base.update(overrides)
    return base


def _nursing(content="护理正文", **overrides):
    base = dict(
        record_id="88001", record_name="一般患者护理记录单",
        content=content, event_time=datetime(2026, 8, 4, 9, 0),
        created_at=datetime(2026, 8, 4, 21, 0),
        structured_fields={"temperature": "36.5", "pulse": "80"},
        mapping_version="nursing-node-map-v2-20260807",
    )
    base.update(overrides)
    return base


class TestMrText:
    def test_daily_sections_and_edge(self):
        payload, mr_text = build_progress_nursing_multi_source_payload(
            _AuditType(), _bundle([_progress()], [_nursing()]), "2026-08-04",
        )
        assert mr_text.startswith("审核日期: 2026-08-04")
        assert "[病历文书]" in mr_text
        assert "[护理记录]" in mr_text
        assert "【病程时间线】" not in mr_text
        assert "病程正文" in mr_text and "护理正文" in mr_text
        assert "temperature=36.5" in mr_text
        assert payload["mr_text"] == mr_text

    def test_discharge_edge_uses_created_date_semantics(self):
        _, mr_text = build_progress_nursing_multi_source_payload(
            _AuditType(), _bundle([_progress()], [_nursing()]), "2026-08-04",
            audit_run_mode="discharge_final",
        )
        assert "── 2026-08-04 ──" in mr_text
        assert "[病程 #1]" in mr_text
        assert "[护理 #1]" in mr_text

    def test_missing_content_marked(self):
        _, mr_text = build_progress_nursing_multi_source_payload(
            _AuditType(), _bundle([_progress(content=None, source_status="missing_content")], []), "2026-08-04",
        )
        assert "内容: （正文缺失）" in mr_text

    def test_relation_metadata_is_deidentified_and_tracks_missing_content(self):
        bundle = _bundle(
            [_progress(content=None, source_status="missing_content")],
            [_nursing(record_id="N-1")],
        )
        payload, _ = build_progress_nursing_multi_source_payload(_AuditType(), bundle, "2026-08-04")
        relation = payload["relation"]
        assert relation["missing_content_count"] == 1
        assert len(relation["source_hashes"]["progress"]) == 64
        assert "F-1" not in str(relation)
        assert "N-1" not in str(relation)

    def test_limits_report_truncation_and_omitted_records_without_whole_text_cut(self):
        bundle = _bundle(
            [_progress(record_id="F-1", content="x" * 20), _progress(record_id="F-2", content="later")],
            [_nursing(record_id="N-1", content="y" * 20), _nursing(record_id="N-2", content="later")],
        )
        payload, mr_text = build_progress_nursing_multi_source_payload(
            _AuditType(max_progress_records=1, max_nursing_records=1,
                       max_progress_chars=5, max_nursing_chars=5),
            bundle, "2026-08-04",
        )
        relation = payload["relation"]
        assert relation["truncated"] == {"progress": True, "nursing": True}
        assert relation["omitted_count"] == {"progress": 1, "nursing": 1}
        assert "其余 1 条记录已省略" in mr_text
        assert "正文已按配置截断" in mr_text

    def test_char_budget_is_shared_by_all_records_in_one_source(self):
        bundle = _bundle(
            [_progress(record_id="F-1", content="abc"), _progress(record_id="F-2", content="def")],
            [_nursing()],
        )
        payload, mr_text = build_progress_nursing_multi_source_payload(
            _AuditType(max_progress_chars=4), bundle, "2026-08-04",
        )
        assert "abc" in mr_text
        assert "d（正文已按配置截断）" in mr_text
        assert "def" not in mr_text
        assert payload["relation"]["truncated"]["progress"] is True

    def test_source_hash_changes_when_content_changes_under_stable_id(self):
        first, _ = build_progress_nursing_multi_source_payload(
            _AuditType(), _bundle([_progress(content="版本一")], [_nursing()]), "2026-08-04",
        )
        second, _ = build_progress_nursing_multi_source_payload(
            _AuditType(), _bundle([_progress(content="版本二")], [_nursing()]), "2026-08-04",
        )
        assert first["relation"]["source_hashes"]["progress"] != second["relation"]["source_hashes"]["progress"]

    def test_discharge_record_limit_is_global_not_reset_per_day(self):
        bundle = _bundle(
            [
                _progress(record_id="F-1", event_time=datetime(2026, 8, 3, 10, 0)),
                _progress(record_id="F-2", event_time=datetime(2026, 8, 4, 10, 0)),
            ],
            [],
        )
        payload, mr_text = build_progress_nursing_multi_source_payload(
            _AuditType(max_progress_records=1), bundle, "2026-08-04",
            audit_run_mode="discharge_final",
        )
        assert mr_text.count("[病程 #") == 1
        assert payload["relation"]["omitted_count"]["progress"] == 1

    def test_empty_sources_render_placeholder(self):
        _, mr_text = build_progress_nursing_multi_source_payload(_AuditType(), _bundle([], []), "2026-08-04")
        assert "[病历文书]" in mr_text and "[护理记录]" in mr_text

    def test_total_length_capped(self):
        big = _bundle([_progress(content="x" * 3000)], [_nursing(content="y" * 3000)])
        _, mr_text = build_progress_nursing_multi_source_payload(_AuditType(), big, "2026-08-04")
        assert len(mr_text) <= _MAX_TOTAL_CHARS

    def test_no_mr_txt_key_anywhere(self):
        payload, _ = build_progress_nursing_multi_source_payload(
            _AuditType(), _bundle([_progress()], [_nursing()]), "2026-08-04",
        )
        assert "mr_txt" not in payload
        assert "mr_text" in payload

    def test_payload_metadata(self):
        payload, _ = build_progress_nursing_multi_source_payload(
            _AuditType(), _bundle([_progress()], [_nursing()]), "2026-08-04",
        )
        assert payload["sources"]["progress"]["count"] == 1
        assert payload["sources"]["nursing"]["count"] == 1
        assert payload["relation_policy_version"].startswith("relation-policy-v1")
        assert payload["mapping_versions"]["progress"].startswith("progress-scope-mapping")
        assert payload["patient_info"]["patient_id"] == "P-1"
        assert payload["patient_info"]["visit_number"] == "3"
        assert set(("admission_no", "patient_name", "department", "dept")).issubset(payload["patient_info"])

    def test_unknown_type_fails_closed(self):
        class _Other(_AuditType):
            code = "unknown_type"
        with pytest.raises(KeyError):
            build_progress_nursing_multi_source_payload(_Other(), _bundle([], []), "2026-08-04")


class TestRegistration:
    def test_register_idempotent(self):
        register_dual_source_builder()
        register_dual_source_builder()
        from app.services.builder_registry import get_builder, has_builder
        assert has_builder(BUILDER_NAME)
        assert get_builder(BUILDER_NAME) is build_progress_nursing_multi_source_payload
