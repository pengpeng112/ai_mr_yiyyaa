"""测试 audit_precheck 模块对不同 builder 类型的跳过判断。"""
from types import SimpleNamespace

from app.services.audit_precheck import summarize_bundles


def _make_bundle(bundle_id="B001", patient_id="P001", visit_number="1", sources=None):
    return SimpleNamespace(
        bundle_id=bundle_id,
        group_values={"patient_id": patient_id, "visit_number": visit_number},
        sources=sources or {},
    )


def _make_audit_type(builder):
    return SimpleNamespace(
        code="test_type",
        name="测试类型",
        payload={"builder": builder},
    )


class TestLabExamBuilder:
    def test_both_sides_present_is_pushable(self):
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = [_make_bundle(sources={"lab": [{"k": 1}], "progress": [{"k": 2}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0

    def test_empty_lab_exam_skipped(self):
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = [_make_bundle(sources={"progress": [{"k": 1}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 0
        assert result["skip_count"] == 1
        assert result["skip_reason_counts"]["empty_lab_exam"] == 1

    def test_empty_progress_nursing_skipped(self):
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = [_make_bundle(sources={"lab": [{"k": 1}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 0
        assert result["skip_count"] == 1
        assert result["skip_reason_counts"]["empty_progress_nursing"] == 1

    def test_empty_both_sides_skipped(self):
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = [_make_bundle(sources={})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 0
        assert result["skip_count"] == 1
        assert result["skip_reason_counts"]["empty_both_sides"] == 1

    def test_structured_variant_also_works(self):
        audit_type = _make_audit_type("lab_exam_structured_progress_nursing")
        bundles = [_make_bundle(sources={"exam": [{"k": 1}], "nursing": [{"k": 2}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0


class TestLegacyBuilder:
    def test_with_primary_is_pushable(self):
        audit_type = _make_audit_type("legacy_progress_nursing")
        bundles = [_make_bundle(sources={"primary": [{"k": 1}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0

    def test_with_progress_only_is_pushable(self):
        audit_type = _make_audit_type("legacy_progress_nursing")
        bundles = [_make_bundle(sources={"progress": [{"k": 1}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0

    def test_no_lab_exam_does_not_skip(self):
        audit_type = _make_audit_type("legacy_progress_nursing")
        bundles = [_make_bundle(sources={"progress": [{"k": 1}], "nursing": [{"k": 2}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0

    def test_empty_all_sources_skipped(self):
        audit_type = _make_audit_type("legacy_progress_nursing")
        bundles = [_make_bundle(sources={})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 0
        assert result["skip_count"] == 1
        assert result["skip_reason_counts"]["empty_primary"] == 1

    def test_custom_primary_source_is_pushable(self):
        """legacy builder 的 primary_source 非 primary 时，有数据不应跳过。"""
        audit_type = _make_audit_type("legacy_progress_nursing")
        bundle = SimpleNamespace(
            bundle_id="B001",
            group_values={"patient_id": "P001", "visit_number": "1"},
            sources={"medical": [{"k": 1}]},
            primary_source="medical",
        )
        result = summarize_bundles(audit_type, [bundle])
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0


class TestFrontpageBuilder:
    def test_with_frontpage_is_pushable(self):
        audit_type = _make_audit_type("frontpage_surgery_first_progress")
        bundles = [_make_bundle(sources={"frontpage": [{"k": 1}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0

    def test_with_first_progress_only_is_pushable(self):
        audit_type = _make_audit_type("frontpage_surgery_first_progress")
        bundles = [_make_bundle(sources={"first_progress": [{"k": 1}]})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0

    def test_empty_both_skipped(self):
        audit_type = _make_audit_type("frontpage_surgery_first_progress")
        bundles = [_make_bundle(sources={})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 0
        assert result["skip_count"] == 1
        assert result["skip_reason_counts"]["empty_frontpage"] == 1


class TestUnknownBuilder:
    def test_unknown_builder_never_skips(self):
        audit_type = _make_audit_type("some_unknown_builder")
        bundles = [_make_bundle(sources={})]
        result = summarize_bundles(audit_type, bundles)
        assert result["pushable_count"] == 1
        assert result["skip_count"] == 0
        assert result["skip_reason_counts"] == {}


class TestSourceRowCounts:
    def test_source_row_counts_passed_through(self):
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = []
        result = summarize_bundles(audit_type, bundles, source_row_counts={"lab": 10, "exam": 5})
        assert result["source_row_counts"] == {"lab": 10, "exam": 5}


class TestBundleSkipReasons:
    def test_bundle_skip_reasons_returned(self):
        """summarize_bundles 应返回每个 bundle 的跳过原因。"""
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = [
            _make_bundle(bundle_id="B001", sources={"lab": [{"k": 1}], "progress": [{"k": 2}]}),
            _make_bundle(bundle_id="B002", sources={"progress": [{"k": 1}]}),
            _make_bundle(bundle_id="B003", sources={}),
        ]
        result = summarize_bundles(audit_type, bundles)
        reasons = result["bundle_skip_reasons"]
        assert reasons["B001"] == ""
        assert reasons["B002"] == "empty_lab_exam"
        assert reasons["B003"] == "empty_both_sides"

    def test_skip_count_equals_bundle_count_minus_pushable(self):
        """skip_count + pushable_count 应等于 bundle_count。"""
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = [
            _make_bundle(bundle_id="B001", sources={"lab": [{"k": 1}], "progress": [{"k": 2}]}),
            _make_bundle(bundle_id="B002", sources={"progress": [{"k": 1}]}),
            _make_bundle(bundle_id="B003", sources={}),
        ]
        result = summarize_bundles(audit_type, bundles)
        assert result["skip_count"] + result["pushable_count"] == result["bundle_count"]

    def test_skip_reason_counts_sum_equals_skip_count(self):
        """skip_reason_counts 总和应等于 skip_count。"""
        audit_type = _make_audit_type("lab_exam_progress_nursing")
        bundles = [
            _make_bundle(bundle_id="B001", sources={"lab": [{"k": 1}], "progress": [{"k": 2}]}),
            _make_bundle(bundle_id="B002", sources={"progress": [{"k": 1}]}),
            _make_bundle(bundle_id="B003", sources={}),
        ]
        result = summarize_bundles(audit_type, bundles)
        assert sum(result["skip_reason_counts"].values()) == result["skip_count"]
