"""测试 emr_vastbase_client 的基本行为。"""
import pytest

pytest.importorskip("cryptography")

from app.emr_vastbase_client import _validate_field_name, _get_field, _build_kind_filter, fetch_emr_documents_by_visits


# ---- 字段名校验 ----

def test_validate_field_name_accepts_valid():
    assert _validate_field_name("patient_id") == "patient_id"
    assert _validate_field_name("_col1") == "_col1"
    assert _validate_field_name("X") == "X"


def test_validate_field_name_rejects_invalid():
    with pytest.raises(ValueError, match="非法字段名"):
        _validate_field_name("")
    with pytest.raises(ValueError, match="非法字段名"):
        _validate_field_name("123abc")
    with pytest.raises(ValueError, match="非法字段名"):
        _validate_field_name("col-name")
    with pytest.raises(ValueError, match="非法字段名"):
        _validate_field_name("col name")
    with pytest.raises(ValueError, match="非法字段名"):
        _validate_field_name("a" * 65)


def test_get_field_uses_config_value():
    cfg = {"my_field": "custom_col"}
    assert _get_field(cfg, "my_field", "default_col") == "custom_col"


def test_get_field_falls_back_to_default():
    cfg = {}
    assert _get_field(cfg, "missing", "default_col") == "default_col"


def test_get_field_rejects_invalid_config_value():
    cfg = {"my_field": "123bad"}
    with pytest.raises(ValueError, match="非法字段名"):
        _get_field(cfg, "my_field", "default_col")


# ---- fetch_emr_documents_by_visits 参数绑定 ----

def test_fetch_emr_documents_by_visits_empty_keys():
    """空 patient_keys 应返回空字典，不连接数据库。"""
    result = fetch_emr_documents_by_visits({"enabled": True}, [], document_kind="all")
    assert result == {}


# ---- 文书类别过滤 ----

def test_discharge_filter_uses_template_exact_match():
    """出院记录仅按 progress_template_name 精确匹配，避免标题/类型误命中。"""
    sql = _build_kind_filter("type_name", "title_name", "template_name", "discharge")
    assert "template_name" in sql
    assert "= '出院记录'" in sql
    assert "LIKE" not in sql
    assert "type_name" not in sql
    assert "title_name" not in sql


def test_progress_filter_uses_allowed_templates_only():
    """病程记录仅按模板名中的病程类别导出，不导出知情同意书等其他模板。"""
    sql = _build_kind_filter("type_name", "title_name", "template_name", "progress")
    assert "template_name" in sql
    assert "病程" in sql
    assert "LIKE" in sql
    assert "知情同意书" not in sql
    assert "type_name" not in sql
    assert "title_name" not in sql


def test_first_progress_filter_uses_template_exact_match():
    sql = _build_kind_filter("type_name", "title_name", "template_name", "first_progress")
    assert "template_name" in sql
    assert "首次病程" in sql
    assert "LIKE" in sql
