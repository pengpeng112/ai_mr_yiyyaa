from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workbench_does_not_duplicate_api_base_prefix():
    source = (ROOT / "frontend/src/features/workbench/WorkbenchPage.vue").read_text(
        encoding="utf-8"
    )

    assert "apiGet" in source
    assert "'/api/" not in source
    assert '"/api/' not in source


def test_feedback_single_delete_has_one_request():
    source = (ROOT / "frontend/src/features/closure/FeedbackPage.vue").read_text(
        encoding="utf-8"
    )
    start = source.index("async function deleteCase")
    end = source.index("async function deleteSelected", start)
    delete_case_source = source[start:end]

    assert delete_case_source.count("apiDelete(") == 1
