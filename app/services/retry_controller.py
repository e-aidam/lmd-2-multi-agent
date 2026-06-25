from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping


@dataclass(frozen=True)
class RetryController:
    max_sql_retries: int = 1

    def __post_init__(self) -> None:
        if self.max_sql_retries < 0:
            raise ValueError("max_sql_retries must be non-negative.")

    def apply(self, state: MutableMapping[str, Any]) -> dict[str, Any]:
        retry_count = int(state.get("retry_count", 0) or 0)
        can_retry = bool(state.get("query_error")) and retry_count < self.max_sql_retries

        updates: dict[str, Any] = {
            "max_sql_retries": self.max_sql_retries,
            "can_retry": can_retry,
            "retry_count": retry_count + 1 if can_retry else retry_count,
        }
        return updates


def retry_controller(state: MutableMapping[str, Any], max_sql_retries: int = 1) -> dict[str, Any]:
    return RetryController(max_sql_retries=max_sql_retries).apply(state)

