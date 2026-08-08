import pytest

from app.emr_vastbase_client import _validate_kind_filter


def test_kind_filter_allows_controlled_document_predicate():
    value = "AND COALESCE(progress_template_name,'') = '出院记录'"
    assert _validate_kind_filter(value) == value


def test_kind_filter_allows_controlled_in_list():
    value = (
        "AND COALESCE(progress_type_name,'') IN "
        "('术后首次病程','手术记录','术前小结')"
    )
    assert _validate_kind_filter(value, {"progress_type_name"}) == value


def test_kind_filter_rejects_arbitrary_sql():
    with pytest.raises(ValueError):
        _validate_kind_filter("AND 1=1; DROP TABLE v_blws")
    with pytest.raises(ValueError):
        _validate_kind_filter("OR patient_id = 'x'")
    with pytest.raises(ValueError):
        _validate_kind_filter(
            "AND COALESCE(progress_type_name,'') IN ('手术记录'); DROP TABLE v_blws"
        )
