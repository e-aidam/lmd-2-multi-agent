from __future__ import annotations

from typing import Any
import json
import logging

from app.config import SettingsError, get_settings
from app.logging import configure_logging
from app.models import AgentGraphResult, AgentQueryRequest, ChatRequest, HealthResponse
from agent import interact, format_output, run_agent_structured

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        return None

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    HTTPException = RuntimeError
    CORSMiddleware = object

    class FastAPI:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.state = type("State", (), {})()

        def add_middleware(self, *_: Any, **__: Any) -> None:
            return None

        def get(self, *_: Any, **__: Any) -> Any:
            def decorator(func: Any) -> Any:
                return func
            return decorator

        def post(self, *_: Any, **__: Any) -> Any:
            def decorator(func: Any) -> Any:
                return func
            return decorator

try:
    from json2xml import json2xml
    from json2xml.utils import readfromstring
except ImportError:
    json2xml = None
    readfromstring = None


load_dotenv()
settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="KPI Analytics Agent", version="0.1.0")

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"Hello": "World"}


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, service="kpi-agent", database=settings.redshift_database)


@app.post("/chat")
async def chat(request: ChatRequest) -> str:
    user_id = request.user_id
    message = request.message
    original_page_context = request.page_context
    database = request.database

    page_context_dict = original_page_context
    page_context_xml = None

    try:
        if json2xml is not None and readfromstring is not None:
            page_context_json = json.dumps(original_page_context)
            raw_page_context = readfromstring(page_context_json)
            page_context_xml = json2xml.Json2xml(raw_page_context).to_xml()
    except Exception as exc:
        logger.warning("page_context_xml_conversion_failed", extra={"error": str(exc)})

    page_context = {
        "dict": page_context_dict,
        "xml": page_context_xml,
    }

    try:
        response = await interact(user_id, message, page_context, database)
    except SettingsError as exc:
        logger.warning("agent_settings_error", extra={"error": str(exc)})
        return "I'm sorry, I cannot complete that request with the configured database settings."
    except Exception:
        logger.exception("agent_chat_failed")
        return "I'm sorry, I couldn't complete that request due to an internal error."

    messages = []
    for msg in response:
        messages.append(str(msg))

    raw_output = "\n".join(messages) if messages else "No response generated"
    return format_output(message, raw_output)


@app.post("/api/agent/query", response_model=AgentGraphResult)
async def query_agent(request: AgentQueryRequest) -> AgentGraphResult:
    page_context = _page_context_payload(request.page_context)
    try:
        return await run_agent_structured(request.user_id, request.message, page_context, request.database)
    except Exception:
        logger.exception("agent_structured_query_failed")
        return AgentGraphResult(
            ok=False,
            answer="I'm sorry, I couldn't complete that request due to an internal error.",
            needs_database=False,
            error="internal_error",
        )


def _page_context_payload(original_page_context: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    page_context_xml = None
    try:
        if json2xml is not None and readfromstring is not None:
            page_context_json = json.dumps(original_page_context)
            raw_page_context = readfromstring(page_context_json)
            page_context_xml = json2xml.Json2xml(raw_page_context).to_xml()
    except Exception as exc:
        logger.warning("page_context_xml_conversion_failed", extra={"error": str(exc)})
    return {"dict": original_page_context, "xml": page_context_xml}
