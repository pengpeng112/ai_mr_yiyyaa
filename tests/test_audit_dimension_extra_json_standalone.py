"""
Standalone tests for extra_json column migration (ADR-1)
Does NOT import app.models (avoids cryptography dependency)
"""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_audit_dimension_result_column_definition():
    """Verify AuditDimensionResult has extra_json column by inspecting source"""
    models_path = Path(__file__).parent.parent / "app" / "models.py"
    source = models_path.read_text(encoding="utf-8")

    # Check class definition exists
    assert "class AuditDimensionResult(Base):" in source
    # Check extra_json column exists
    assert 'extra_json = Column(Text, default="{}")' in source
    # Check it's inside AuditDimensionResult class (before AuditConclusion)
    dim_start = source.find("class AuditDimensionResult(Base):")
    conclusion_start = source.find("class AuditConclusion(Base):")
    extra_json_in_dim = source.find('extra_json = Column(Text, default="{}")', dim_start, conclusion_start)
    assert extra_json_in_dim != -1, "extra_json column not found in AuditDimensionResult"


def test_audit_conclusion_column_definition():
    """Verify AuditConclusion has extra_json column by inspecting source"""
    models_path = Path(__file__).parent.parent / "app" / "models.py"
    source = models_path.read_text(encoding="utf-8")

    assert "class AuditConclusion(Base):" in source
    conclusion_start = source.find("class AuditConclusion(Base):")
    scheduler_start = source.find("class SchedulerHistory(Base):")
    extra_json_in_conclusion = source.find('extra_json = Column(Text, default="{}")', conclusion_start, scheduler_start)
    assert extra_json_in_conclusion != -1, "extra_json column not found in AuditConclusion"


def test_database_migration_includes_extra_json():
    """Verify database migration functions include extra_json"""
    db_path = Path(__file__).parent.parent / "app" / "database.py"
    source = db_path.read_text(encoding="utf-8")

    # Check _migrate_audit_dimension_result_columns has extra_json
    dim_migrate_start = source.find("def _migrate_audit_dimension_result_columns()")
    dim_migrate_end = source.find("def _migrate_audit_conclusion_columns()")
    dim_section = source[dim_migrate_start:dim_migrate_end]
    assert '("extra_json", "TEXT DEFAULT \'{}\'")' in dim_section

    # Check _migrate_audit_conclusion_columns has extra_json
    conclusion_migrate_start = source.find("def _migrate_audit_conclusion_columns()")
    conclusion_migrate_end = source.find("def _migrate_qc_feedback_columns()")
    conclusion_section = source[conclusion_migrate_start:conclusion_migrate_end]
    assert '("extra_json", "TEXT DEFAULT \'{}\'")' in conclusion_section


def test_verify_required_schema_includes_extra_json():
    """Verify _verify_required_schema checks extra_json"""
    db_path = Path(__file__).parent.parent / "app" / "database.py"
    source = db_path.read_text(encoding="utf-8")

    verify_start = source.find("def _verify_required_schema()")
    assert verify_start != -1

    # Check audit_dimension_result section includes extra_json
    dim_section_start = source.find('"audit_dimension_result":', verify_start)
    dim_section_end = source.find('"audit_conclusion":', dim_section_start)
    dim_section = source[dim_section_start:dim_section_end]
    assert '"extra_json"' in dim_section

    # Check audit_conclusion section includes extra_json
    conclusion_section_start = source.find('"audit_conclusion":', verify_start)
    conclusion_section_end = source.find('"qc_feedback":', conclusion_section_start)
    conclusion_section = source[conclusion_section_start:conclusion_section_end]
    assert '"extra_json"' in conclusion_section


def test_push_executor_has_extra_json_fallback():
    """Verify _save_audit_results has try/except fallback for extra_json"""
    executor_path = Path(__file__).parent.parent / "app" / "services" / "push_executor.py"
    source = executor_path.read_text(encoding="utf-8")

    save_start = source.find("def _save_audit_results")
    assert save_start != -1

    # Check dimension extra_json fallback
    dim_extra_fallback = source.find("try:\n                dim_result.extra_json =", save_start)
    assert dim_extra_fallback != -1, "Dimension extra_json fallback not found"

    # Check conclusion extra_json fallback
    conclusion_extra_fallback = source.find("try:\n            conclusion.extra_json =", save_start)
    assert conclusion_extra_fallback != -1, "Conclusion extra_json fallback not found"


def test_schemas_has_extra_json():
    """Verify AuditDimensionItem schema has extra_json field"""
    schemas_path = Path(__file__).parent.parent / "app" / "schemas.py"
    source = schemas_path.read_text(encoding="utf-8")

    item_start = source.find("class AuditDimensionItem(BaseModel):")
    assert item_start != -1

    item_end = source.find("class AuditReportResponse(BaseModel):", item_start)
    item_section = source[item_start:item_end]
    assert "extra_json" in item_section


def test_py_compile_all_modified_files():
    """Verify all modified Python files compile without syntax errors"""
    import py_compile

    files = [
        Path(__file__).parent.parent / "app" / "models.py",
        Path(__file__).parent.parent / "app" / "database.py",
        Path(__file__).parent.parent / "app" / "services" / "push_executor.py",
        Path(__file__).parent.parent / "app" / "schemas.py",
        Path(__file__).parent.parent / "tests" / "test_audit_dimension_extra_json.py",
    ]

    for f in files:
        assert f.exists(), f"File not found: {f}"
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            raise AssertionError(f"Syntax error in {f}: {e}")


if __name__ == "__main__":
    # Run all tests manually if pytest not available
    tests = [
        test_audit_dimension_result_column_definition,
        test_audit_conclusion_column_definition,
        test_database_migration_includes_extra_json,
        test_verify_required_schema_includes_extra_json,
        test_push_executor_has_extra_json_fallback,
        test_schemas_has_extra_json,
        test_py_compile_all_modified_files,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {test.__name__}: {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
