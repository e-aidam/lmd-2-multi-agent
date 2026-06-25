from __future__ import annotations

from typing import Any, Mapping


def escape_markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def rows_to_markdown(rows: list[Mapping[str, Any]], max_rows: int = 20) -> str | None:
    if not rows:
        return None

    columns = list(rows[0].keys())
    header = "| " + " | ".join(escape_markdown_cell(column) for column in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows[:max_rows]:
        body.append("| " + " | ".join(escape_markdown_cell(row.get(column)) for column in columns) + " |")
    return "\n".join([header, separator, *body])


def format_query_result(rows: list[dict[str, Any]] | None, max_preview_rows: int = 20) -> dict[str, Any]:
    safe_rows = rows or []
    preview_rows = safe_rows[:max_preview_rows]
    return {
        "row_count": len(safe_rows),
        "preview_markdown": rows_to_markdown(preview_rows, max_rows=max_preview_rows),
        "truncated": len(safe_rows) > max_preview_rows,
    }

