import asyncio
import inspect
import os
from typing import Any

from app.models import ChatRequest

os.environ["MEM_DB_URI"] = ""

import app.main as main


def test_chat_endpoint_is_async() -> None:
    assert inspect.iscoroutinefunction(main.chat)


def test_chat_preserves_page_context_dict_and_xml(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class FakeJson2xml:
        def __init__(self, raw: Any) -> None:
            self.raw = raw

        def to_xml(self) -> str:
            return "<context />"

    class FakeJsonModule:
        Json2xml = FakeJson2xml

    async def fake_interact(user_id: str, message: str, page_context: dict[str, Any], database: str) -> list[str]:
        captured["user_id"] = user_id
        captured["message"] = message
        captured["page_context"] = page_context
        captured["database"] = database
        return ["ok"]

    monkeypatch.setattr(main, "json2xml", FakeJsonModule)
    monkeypatch.setattr(main, "readfromstring", lambda text: {"raw": text})
    monkeypatch.setattr(main, "interact", fake_interact)

    request = ChatRequest(
        message="Show total KPI",
        user_id="u1",
        page_context={"session_id": "s1", "selected_kpi": "training"},
        database="kpi_data",
    )

    result = asyncio.run(main.chat(request))

    assert result == "ok"
    assert captured["page_context"]["dict"] == {"session_id": "s1", "selected_kpi": "training"}
    assert captured["page_context"]["xml"] == "<context />"
    assert captured["database"] == "kpi_data"
