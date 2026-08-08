# -*- coding: utf-8 -*-
"""012 P2 草案测试：RelationPolicy 复刻现行关联语义（012 §6/§10.2）。"""
import pytest

from app.services.relation_policy import (
    RELATION_POLICY_VERSION_V1,
    RUN_MODE_DAILY,
    RUN_MODE_DISCHARGE,
    get_relation_policy,
    list_relation_policies,
    validate_required_sources,
)


class TestProgressVsNursingPolicy:
    def test_daily_requires_both_sources(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DAILY)
        assert set(policy.required_sources) == {"progress", "nursing"}
        assert policy.context_sources == ()
        assert "same_audit_day" in policy.relation_edges

    def test_daily_time_rules_frozen(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DAILY)
        assert "caption_date_time" in policy.time_rules["progress"]
        assert "form_time" in policy.time_rules["nursing"]

    def test_discharge_nursing_is_left_context(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DISCHARGE)
        assert policy.required_sources == ("progress",)
        assert "nursing" in policy.context_sources
        assert "created_date" in policy.time_rules["nursing"]
        assert "same_calendar_day" in policy.relation_edges


class TestOtherPolicies:
    def test_syssvsscbc_keeps_operation_date(self):
        policy = get_relation_policy("syssvsscbc", RUN_MODE_DISCHARGE)
        assert "operation_date" in policy.anchor_keys

    def test_surgery_chain_has_no_operation_date(self):
        for mode in (RUN_MODE_DAILY, RUN_MODE_DISCHARGE):
            policy = get_relation_policy("surgery_chain", mode)
            assert "operation_date" not in policy.anchor_keys
            assert len(policy.required_sources) == 3

    def test_jyjc_anchor_sources(self):
        policy = get_relation_policy("jyjc_vs_bcnursing", RUN_MODE_DAILY)
        assert set(policy.anchor_sources) == {"lab", "exam"}
        assert set(policy.context_sources) == {"progress", "nursing"}

    def test_admission_and_discharge_frontpage_required_pairs(self):
        admission = get_relation_policy("admission_vs_first_progress", RUN_MODE_DAILY)
        assert set(admission.required_sources) == {"admission_record", "first_progress"}
        discharge = get_relation_policy("discharge_vs_frontpage", RUN_MODE_DISCHARGE)
        assert set(discharge.required_sources) == {"discharge_record", "frontpage"}


class TestPolicyRegistry:
    def test_all_six_types_registered(self):
        codes = {p.audit_type_code for p in list_relation_policies()}
        assert codes == {
            "progress_vs_nursing",
            "jyjc_vs_bcnursing",
            "syssvsscbc",
            "admission_vs_first_progress",
            "surgery_chain",
            "discharge_vs_frontpage",
        }

    def test_unknown_policy_fails_closed(self):
        with pytest.raises(KeyError):
            get_relation_policy("progress_vs_nursing", "weekly")
        with pytest.raises(KeyError):
            get_relation_policy("unknown_type", RUN_MODE_DAILY)
        with pytest.raises(KeyError):
            get_relation_policy("progress_vs_nursing", RUN_MODE_DAILY, version="v0")

    def test_policies_immutable(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DAILY)
        with pytest.raises(AttributeError):
            policy.required_sources = ("progress",)  # type: ignore[misc]


class TestValidateRequiredSources:
    def test_query_failed_required_source_fails_closed(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DAILY)
        violations = validate_required_sources(policy, {"progress", "nursing"}, {"nursing"})
        assert any("fail-closed" in v for v in violations)

    def test_missing_required_source_violation(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DAILY)
        violations = validate_required_sources(policy, {"progress"}, set())
        assert any("缺失" in v for v in violations)

    def test_missing_context_source_tolerated(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DISCHARGE)
        assert validate_required_sources(policy, {"progress"}, set()) == []

    def test_all_available_passes(self):
        policy = get_relation_policy("progress_vs_nursing", RUN_MODE_DAILY)
        assert validate_required_sources(policy, {"progress", "nursing"}, set()) == []
