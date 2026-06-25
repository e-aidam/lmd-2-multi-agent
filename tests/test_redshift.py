import asyncio

from app.config import Settings
from app.services.redshift import RedshiftService, is_schema_error


def test_executor_captures_errors_instead_of_throwing() -> None:
    service = RedshiftService(Settings())

    result = asyncio.run(service.execute_sql("SELECT id FROM public.metrics"))

    assert result.rows is None
    assert result.error is not None


def test_schema_error_detection() -> None:
    assert is_schema_error("ERROR: relation does not exist") is True
    assert is_schema_error("ERROR: column does not exist") is True
    assert is_schema_error("timeout") is False

