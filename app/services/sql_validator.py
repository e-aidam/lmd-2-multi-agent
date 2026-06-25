from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SQLValidationResult:
    ok: bool
    sql: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SQLValidatorConfig:
    default_limit: int = 100
    max_limit: int = 1000


class SQLValidator:
    blocked_keywords = (
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "create",
        "copy",
        "unload",
        "call",
        "execute",
        "grant",
        "revoke",
        "merge",
        "vacuum",
        "analyze",
    )

    def __init__(self, config: SQLValidatorConfig | None = None) -> None:
        self.config = config or SQLValidatorConfig()

    def validate(self, raw_sql: str | None) -> SQLValidationResult:
        if raw_sql is None or not raw_sql.strip():
            return SQLValidationResult(ok=False, error="SQL is empty.")

        sql = self._strip_code_fence(raw_sql.strip())
        if self._has_comments(sql):
            return SQLValidationResult(ok=False, error="SQL comments are not allowed.")
        if self._has_unresolved_placeholder(sql):
            return SQLValidationResult(ok=False, error="SQL contains unresolved placeholders.")

        sql = self._remove_single_trailing_semicolon(sql)
        if ";" in sql:
            return SQLValidationResult(ok=False, error="Only one SQL statement is allowed.")

        compact = self._normalize_whitespace(sql)
        lowered = compact.lower()
        if not re.match(r"^(select|with)\b", lowered):
            return SQLValidationResult(ok=False, error="Only SELECT or WITH queries are allowed.")

        for keyword in self.blocked_keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                return SQLValidationResult(ok=False, error=f"Blocked SQL keyword detected: {keyword}.")

        if re.search(r"\b(information_schema|pg_catalog|pg_|stl_|stv_|svl_|svv_)", lowered):
            return SQLValidationResult(ok=False, error="System catalog queries are not allowed.")

        if self._has_select_star(compact):
            return SQLValidationResult(ok=False, error="SELECT * is not allowed.")

        limited = self._ensure_limit(compact)
        return SQLValidationResult(ok=True, sql=limited)

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        match = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else text

    @staticmethod
    def _has_comments(text: str) -> bool:
        return "--" in text or "/*" in text or "*/" in text

    @staticmethod
    def _has_unresolved_placeholder(text: str) -> bool:
        return bool(
            re.search(r"\b(undefined|nan)\b", text, flags=re.IGNORECASE)
            or "{{" in text
            or "}}" in text
            or "${" in text
        )

    @staticmethod
    def _remove_single_trailing_semicolon(text: str) -> str:
        stripped = text.strip()
        if stripped.endswith(";"):
            stripped = stripped[:-1].strip()
        return stripped

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _has_select_star(sql: str) -> bool:
        return bool(
            re.search(r"\bselect\s+(?:[a-zA-Z_][\w$]*\.)?\*", sql, flags=re.IGNORECASE)
            or re.search(r",\s*(?:[a-zA-Z_][\w$]*\.)?\*", sql, flags=re.IGNORECASE)
        )

    def _ensure_limit(self, sql: str) -> str:
        limit_match = list(re.finditer(r"\blimit\s+(\d+)\b", sql, flags=re.IGNORECASE))
        if not limit_match:
            return f"{sql} LIMIT {self.config.default_limit}"

        match = limit_match[-1]
        limit_value = int(match.group(1))
        if limit_value <= self.config.max_limit:
            return sql

        return f"{sql[:match.start(1)]}{self.config.max_limit}{sql[match.end(1):]}"

