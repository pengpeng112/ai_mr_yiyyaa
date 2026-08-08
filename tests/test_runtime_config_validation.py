from app.config import validate_runtime_config


def test_inactive_postgresql_example_does_not_warn():
    warnings = validate_runtime_config(
        {
            "data_source": {"type": "oracle"},
            "postgresql": {"query_sql": "select * from example"},
        }
    )
    assert not any("PostgreSQL query_sql" in item for item in warnings)


def test_active_postgresql_query_remains_strictly_validated():
    warnings = validate_runtime_config(
        {
            "data_source": {"type": "postgresql"},
            "postgresql": {"query_sql": "select * from example"},
        }
    )
    assert any("PostgreSQL query_sql" in item for item in warnings)
