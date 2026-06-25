from app.services.retry_controller import RetryController


def test_max_sql_retries_zero_never_retries() -> None:
    controller = RetryController(max_sql_retries=0)

    result = controller.apply({"query_error": "failed", "retry_count": 0})

    assert result["can_retry"] is False
    assert result["retry_count"] == 0


def test_increments_only_when_retrying() -> None:
    controller = RetryController(max_sql_retries=2)

    result = controller.apply({"query_error": "failed", "retry_count": 1})

    assert result["can_retry"] is True
    assert result["retry_count"] == 2


def test_stops_after_max_retries() -> None:
    controller = RetryController(max_sql_retries=2)

    result = controller.apply({"query_error": "failed", "retry_count": 2})

    assert result["can_retry"] is False
    assert result["retry_count"] == 2


def test_does_not_retry_without_query_error() -> None:
    controller = RetryController(max_sql_retries=2)

    result = controller.apply({"query_error": None, "retry_count": 0})

    assert result["can_retry"] is False
    assert result["retry_count"] == 0

