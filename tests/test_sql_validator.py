from app.services.sql_validator import SQLValidator, SQLValidatorConfig


def test_rejects_unsafe_statements() -> None:
    validator = SQLValidator()
    unsafe_sql = [
        "DELETE FROM public.metrics",
        "SELECT * FROM public.metrics",
        "SELECT id FROM information_schema.columns",
        "SELECT id FROM public.metrics; SELECT id FROM public.other",
        "SELECT id FROM public.metrics -- nope",
        "SELECT {{column}} FROM public.metrics",
    ]

    for sql in unsafe_sql:
        result = validator.validate(sql)
        assert result.ok is False, sql


def test_adds_default_limit() -> None:
    validator = SQLValidator(SQLValidatorConfig(default_limit=100, max_limit=1000))
    result = validator.validate("SELECT id FROM public.metrics")

    assert result.ok is True
    assert result.sql == "SELECT id FROM public.metrics LIMIT 100"


def test_caps_existing_limit() -> None:
    validator = SQLValidator(SQLValidatorConfig(default_limit=100, max_limit=1000))
    result = validator.validate("SELECT id FROM public.metrics LIMIT 5000")

    assert result.ok is True
    assert result.sql == "SELECT id FROM public.metrics LIMIT 1000"


def test_allows_count_star() -> None:
    validator = SQLValidator()
    result = validator.validate("SELECT COUNT(*) AS row_count FROM public.metrics")

    assert result.ok is True

