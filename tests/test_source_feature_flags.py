# -*- coding: utf-8 -*-
"""012 P2 草案测试：数据源 feature flag 默认旧路径、非法值 fail-closed。"""
import pytest

from app.services.source_feature_flags import (
    NURSING_SOURCE_LEGACY,
    NURSING_SOURCE_ORACLE_V1,
    PROGRESS_SOURCE_VASTBASE_V1,
    PROGRESS_SOURCE_V_BCJL,
    is_new_source_enabled,
    resolve_source_flags,
)


class TestDefaults:
    def test_empty_config_defaults_to_legacy(self):
        flags = resolve_source_flags(None)
        assert flags.progress_source == PROGRESS_SOURCE_V_BCJL
        assert flags.nursing_source == NURSING_SOURCE_LEGACY
        assert not is_new_source_enabled(flags)

    def test_empty_source_flags_dict_defaults(self):
        flags = resolve_source_flags({"source_flags": {}})
        assert flags.progress_source == PROGRESS_SOURCE_V_BCJL
        assert flags.nursing_source == NURSING_SOURCE_LEGACY


class TestValidation:
    def test_valid_new_values_accepted(self):
        flags = resolve_source_flags({
            "source_flags": {
                "progress_source": "vastbase_v1",
                "nursing_source": "oracle_v1",
            }
        })
        assert flags.progress_source == PROGRESS_SOURCE_VASTBASE_V1
        assert flags.nursing_source == NURSING_SOURCE_ORACLE_V1
        assert is_new_source_enabled(flags)

    def test_invalid_progress_source_fails_closed(self):
        with pytest.raises(ValueError):
            resolve_source_flags({"source_flags": {"progress_source": "v_blws_direct"}})

    def test_invalid_nursing_source_fails_closed(self):
        with pytest.raises(ValueError):
            resolve_source_flags({"source_flags": {"nursing_source": "v_hljl"}})

    def test_flags_immutable(self):
        flags = resolve_source_flags(None)
        with pytest.raises(AttributeError):
            flags.progress_source = PROGRESS_SOURCE_VASTBASE_V1  # type: ignore[misc]
