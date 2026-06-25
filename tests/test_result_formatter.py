from app.services.result_formatter import format_query_result, rows_to_markdown


def test_rows_to_markdown_escapes_pipe_characters() -> None:
    markdown = rows_to_markdown([{"name": "A|B", "count": 2}])

    assert markdown is not None
    assert "A\\|B" in markdown


def test_format_query_result_counts_and_truncates_preview() -> None:
    rows = [{"id": i} for i in range(25)]

    result = format_query_result(rows, max_preview_rows=20)

    assert result["row_count"] == 25
    assert result["truncated"] is True
    assert result["preview_markdown"].count("\n") == 21

