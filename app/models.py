from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    from pydantic import BaseModel, Field
except ImportError:
    _MISSING = object()

    class _FieldInfo:
        def __init__(self, default: Any = _MISSING, default_factory: Any = None) -> None:
            self.default = default
            self.default_factory = default_factory

    def Field(default: Any = _MISSING, *, default_factory: Any = None, **_: Any) -> Any:
        return _FieldInfo(default, default_factory)

    class BaseModel:
        def __init__(self, **data: Any) -> None:
            annotations: dict[str, Any] = {}
            for cls in reversed(type(self).mro()):
                annotations.update(getattr(cls, "__annotations__", {}))
            for name in annotations:
                default = getattr(type(self), name, _MISSING)
                if name in data:
                    value = data[name]
                elif isinstance(default, _FieldInfo):
                    if default.default_factory is not None:
                        value = default.default_factory()
                    elif default.default is not _MISSING:
                        value = deepcopy(default.default)
                    else:
                        raise TypeError(f"Missing required field: {name}")
                elif default is not _MISSING:
                    value = deepcopy(default)
                else:
                    raise TypeError(f"Missing required field: {name}")
                setattr(self, name, value)

        def model_dump(self) -> dict[str, Any]:
            annotations: dict[str, Any] = {}
            for cls in reversed(type(self).mro()):
                annotations.update(getattr(cls, "__annotations__", {}))
            return {name: getattr(self, name) for name in annotations}


class ChatRequest(BaseModel):
    message: str
    user_id: str
    page_context: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=dict)
    database: str = "kpi_data"


class AgentGraphResult(BaseModel):
    ok: bool
    answer: str
    needs_database: bool
    sql_used: str | None = None
    row_count: int | None = None
    preview_markdown: str | None = None
    error: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentQueryRequest(BaseModel):
    message: str
    user_id: str
    page_context: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=dict)
    database: str = "kpi_data"


class HealthResponse(BaseModel):
    ok: bool
    service: str
    database: str

