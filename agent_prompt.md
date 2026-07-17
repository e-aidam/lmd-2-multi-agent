Build a production-ready FastAPI + LangGraph service for a text-to-SQL analytics agent connected to an existing data portal.

The system should implement a master-orchestrated, self-correcting KPI analytics architecture inspired by the earlier n8n prototype.

## Pre-Implementation Requirement

Before creating, replacing, or modifying files, first inspect the existing repository structure.

Required behavior:

```text
1. Inspect the current repository tree.
2. Identify any existing FastAPI entrypoint, agent modules, service modules, tests, config files, and README files.
3. Adapt existing files where practical instead of replacing them wholesale.
4. Only create new files after confirming they do not already exist or after deciding they are necessary for the new architecture.
```

Do not assume a blank repository.

## Goal

Create a backend service that receives natural language analytics questions from a data portal, determines whether database access is needed, retrieves schema context, generates safe SQL, validates it, executes it against AWS Redshift, retries failed SQL with correction, and returns a structured response.

SQL retry behavior must be controlled by a deterministic Retry Controller node using the `MAX_SQL_RETRIES` environment variable. LLM agents must not decide how many retries to attempt.

Chat memory must be stored and retrieved from a Postgres database configured by `MEM_DB_URI`.

Use the standardized database name:

```text
kpi_data
```

Use AWS Bedrock Runtime and AWS Bedrock Agents where appropriate.

## Stack

Use:

* Python 3.11+
* FastAPI
* LangGraph
* AWS Bedrock Runtime / AWS Bedrock Agents where appropriate
* SQLAlchemy or `redshift_connector` for Redshift access
* Pydantic for request/response schemas
* Postgres-backed chat memory using `MEM_DB_URI`
* Optional Redis or Postgres for schema caching
* Structured JSON logging

## High-Level Architecture

Implement this graph:

```text
User Question
→ derive_session_id
→ save_user_message
→ load_chat_memory
→ Master Orchestrator
→ Save Orchestrator Decision to Memory
→ Need database?
   ├─ no → Final Answer Agent → Save Final Answer to Memory
   └─ yes
      → Get or Refresh Schema Context
      → SQL Generator Agent
      → SQL Validation Guardrail
      → Execute SQL
      → Query succeeded?
         ├─ yes → Format Query Result → Final Answer Agent → Save Final Answer to Memory
         └─ no
            → Retry Controller
            → Can retry?
               ├─ yes
               │  → SQL Corrector Agent
               │  → SQL Validation Guardrail
               │  → Execute SQL
               │  → Query succeeded?
               │     ├─ yes → Format Query Result → Final Answer Agent → Save Final Answer to Memory
               │     └─ no → Retry Controller
               └─ no
                  → Final Error Response → Save Final Error to Memory
```

The Master Orchestrator is for routing only.

The Final Answer Agent is distinct from the Master Orchestrator and is responsible for synthesizing final user-facing responses.

The retry loop must be deterministic:

```text
Execute SQL fails
→ Retry Controller checks retry_count < MAX_SQL_RETRIES
→ if true, increment retry_count and route to SQL Corrector
→ if false, route to Final Error Response
```

## Required Components

### 1. FastAPI App

Adapt the existing FastAPI entrypoint instead of replacing it wholesale.

The current portal-facing API uses:

* `GET /`
* `POST /chat`
* `ChatRequest`
* `interact(...)`
* `format_output(...)`
* CORS enabled for all origins
* optional conversion of `page_context` from JSON to XML before agent execution

Preserve this public API shape unless there is a strong reason to change it.

Required implementation:

```python
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Dict, Any, Union
from fastapi.middleware.cors import CORSMiddleware

import json

from json2xml import json2xml
from json2xml.utils import readfromstring

from agent import interact, format_output

load_dotenv()

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    user_id: str
    page_context: Union[List[Dict[str, Any]], Dict[str, Any]] = {}
    database: str = "kpi_data"


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/chat")
async def chat(request: ChatRequest) -> str:
    user_id = request.user_id
    message = request.message
    original_page_context = request.page_context
    database = request.database

    page_context_dict = original_page_context
    page_context_xml = None

    try:
        page_context_json = json.dumps(original_page_context)
        raw_page_context = readfromstring(page_context_json)
        page_context_xml = json2xml.Json2xml(raw_page_context).to_xml()
    except Exception as e:
        print(f"Error converting page_context to XML: {e}")

    page_context = {
        "dict": page_context_dict,
        "xml": page_context_xml,
    }

    response = await interact(user_id, message, page_context, database)

    messages = []
    for msg in response:
        messages.append(str(msg))

    raw_output = "\n".join(messages) if messages else "No response generated"
    return format_output(message, raw_output)
```

Requirements:

* Make `/chat` async.
* Preserve page context as both dict/list and XML.
* Pass page context to the graph as:

```python
state["context"]["page_context"] = {
    "dict": ...,
    "xml": ...
}
```

Revise the internals behind `interact(...)` so that it uses the new LangGraph architecture:

```text
interact(user_id, message, page_context, database)
→ build initial AgentState
→ derive_session_id
→ save_user_message
→ load_chat_memory
→ master_orchestrator
→ deterministic database routing
→ schema retrieval / SQL generation / validation / execution / retry controller / correction loop
→ final_answer_agent
→ save_final_response
→ return iterable/list of response messages compatible with existing `/chat` code
```

#### Backward Compatibility Requirements

* Keep `POST /chat` as the primary endpoint.
* Keep `/chat` async.
* Keep `ChatRequest.message`.
* Keep `ChatRequest.user_id`.
* Keep `ChatRequest.page_context`.
* Keep `ChatRequest.database`, defaulting to `"kpi_data"`.
* Keep `GET /`.
* Keep `format_output(message, raw_output)` as the final response formatting step.
* Keep `interact(user_id, message, page_context, database)` as the public agent function called by FastAPI.
* Ensure `interact(...)` can return an iterable/list of messages, because the current `/chat` handler joins each item with newlines.
* Do not require the data portal to change its request format.

#### Recommended Internal Response Shape

Although `/chat` returns a string for compatibility, internally the graph should produce a structured response:

```python
class AgentGraphResult(BaseModel):
    ok: bool
    answer: str
    needs_database: bool
    sql_used: str | None = None
    row_count: int | None = None
    preview_markdown: str | None = None
    error: str | None = None
    assumptions: list[str] = []
    metadata: dict[str, Any] = {}
```

Then `interact(...)` may convert the structured result into one or more string messages for the existing FastAPI handler.

#### Session and Memory Behavior

Because the current `ChatRequest` does not include `session_id`, derive the memory session ID deterministically from available request fields.

Required graph order:

```text
derive_session_id → save_user_message → load_chat_memory
```

Recommended behavior:

```python
page_context_dict = page_context.get("dict") if isinstance(page_context, dict) else None
session_id = page_context_dict.get("session_id") if isinstance(page_context_dict, dict) else None
session_id = session_id or f"{database}:{user_id}"
```

Chat memory must still be stored in Postgres using `MEM_DB_URI`.

#### Page Context Handling

The existing API converts `page_context` to XML before calling `interact(...)`.

Preserve this behavior, but ensure the graph receives both:

* original dict/list page context
* XML string page context, if conversion succeeds

The Master Orchestrator should receive page context as:

```python
state["context"]["page_context"]["dict"]
state["context"]["page_context"]["xml"]
```

Use page context to resolve portal-specific follow-up questions, filters, selected geography, selected KPI, dashboard state, or page-level metadata.

#### Database Parameter

Use `ChatRequest.database` to select the target database context.

Initial allowed value:

```python
"kpi_data"
```

If another database value is provided, either:

* reject it with a clear user-facing error, or
* route it only if explicitly configured in allowed database settings.

Do not silently query an unknown database.

#### Optional Additional Endpoint

You may add a structured endpoint for future frontend use:

```http
POST /api/agent/query
```

This endpoint may return `AgentGraphResult` directly.

But do not remove or break `/chat`.

#### Error Handling

The `/chat` endpoint should never expose stack traces, credentials, raw driver errors, or internal LangGraph state.

If the graph fails unexpectedly, return a clear response such as:

```text
I’m sorry, I couldn’t complete that request due to an internal error.
```

Log the detailed exception server-side using structured logging.

#### Health Check

Keep:

```http
GET /
```

Optionally add:

```http
GET /health
```

returning:

```python
{
    "ok": True,
    "service": "kpi-agent",
    "database": "kpi_data"
}
```

### 2. LangGraph State

Define a shared graph state:

```python
class AgentState(TypedDict, total=False):
    question: str
    user_id: str | None
    session_id: str | None
    database: str
    context: dict[str, Any]

    chat_history: list[dict[str, str]]
    memory_loaded: bool
    memory_saved: bool

    needs_database: bool
    route_reason: str

    schema_context: dict[str, Any]
    schema_search_terms: list[str]

    generated_sql: str
    validated_sql: str
    sql_assumptions: list[str]

    query_result: list[dict[str, Any]] | None
    query_error: str | None

    corrected_sql: str
    correction_reason: str

    retry_count: int
    max_sql_retries: int
    can_retry: bool

    final_answer: str
    preview_markdown: str | None
    row_count: int | None
    ok: bool
    final_error: str | None
```

### 3. Configuration

Create a centralized config object loaded from environment variables.

Support:

```env
AWS_REGION=
BEDROCK_MODEL_MASTER=
BEDROCK_MODEL_SQL=
BEDROCK_MODEL_CORRECTOR=
BEDROCK_MODEL_FINAL=

REDSHIFT_HOST=
REDSHIFT_PORT=
REDSHIFT_DATABASE=kpi_data
REDSHIFT_USER=
REDSHIFT_PASSWORD=
REDSHIFT_SCHEMA=public

MEM_DB_URI=

SCHEMA_CACHE_TTL_SECONDS=86400
MAX_SQL_RETRIES=1
QUERY_TIMEOUT_SECONDS=30
DEFAULT_LIMIT=100
MAX_LIMIT=1000
MAX_SCHEMA_TABLES_RETURNED=25
```

Requirements:

* Standardize the database to `kpi_data`.
* `MAX_SQL_RETRIES` must default to `1`.
* `MAX_SQL_RETRIES` must be parsed as a non-negative integer.
* If `MAX_SQL_RETRIES=0`, the system must not call the SQL Corrector after an execution failure.
* `MEM_DB_URI` is required in production.
* The service should fail fast at startup if required environment variables are missing.

### 4. Postgres Chat Memory Service

Implement a deterministic chat memory service backed by `MEM_DB_URI`.

Create:

```text
app/services/chat_memory.py
```

Responsibilities:

* Connect to Postgres using `MEM_DB_URI`.
* Create tables if they do not exist.
* Load recent chat history by `session_id`.
* Save user messages, assistant messages, routing decisions, and final answers.
* Keep memory scoped by `session_id`.
* Optionally include `user_id`.

Suggested table:

```sql
CREATE TABLE IF NOT EXISTS agent_chat_memory (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

Suggested indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_agent_chat_memory_session_created
ON agent_chat_memory (session_id, created_at DESC)
```

Expose methods:

```python
class ChatMemoryService:
    async def init_db(self) -> None: ...

    async def load_history(
        self,
        session_id: str,
        limit: int = 20
    ) -> list[dict[str, str]]: ...

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None
    ) -> None: ...
```

### 5. Memory Nodes

Add deterministic LangGraph nodes:

#### `derive_session_id`

Runs before saving or loading memory.

Responsibilities:

* Use `page_context["dict"]["session_id"]` when available.
* Otherwise derive `session_id` as:

```python
session_id = f"{database}:{user_id}"
```

* Store it in `state["session_id"]`.

#### `save_user_message`

Runs immediately after `derive_session_id`.

Responsibilities:

* Save the incoming user message to Postgres.
* Store metadata such as `user_id`, portal context, database, and timestamp.

#### `load_chat_memory`

Runs after `save_user_message` and before the Master Orchestrator.

Responsibilities:

* Load recent chat history using `session_id`.
* Store it in `state["chat_history"]`.
* Set `state["memory_loaded"] = True`.

#### `save_orchestrator_decision`

Runs after the Master Orchestrator.

Responsibilities:

* Save route decision metadata, including:

  * `needs_database`
  * `route_reason`
  * `schema_search_terms`

#### `save_final_response`

Runs at the end of the graph.

Responsibilities:

* Save the assistant’s final answer or final error response.
* Include SQL metadata when available:

  * `validated_sql`
  * `corrected_sql`
  * `row_count`
  * `query_error`
  * `retry_count`

### 6. Master Orchestrator Node

The Master Orchestrator is for routing only.

It decides whether database access is needed.

It receives:

* current user question
* recent chat history from Postgres
* portal context as both dict/list and XML

It should return structured JSON:

```json
{
  "needs_database": true,
  "route_reason": "The user is asking for a KPI total from database contents.",
  "schema_search_terms": ["mlw_upskill", "training", "chw"]
}
```

Rules:

* General conceptual questions can be routed to the Final Answer Agent without database access.
* KPI totals, counts, trends, comparisons, country metrics, quarterly metrics, narratives, or service delivery questions require database access.
* The Master Orchestrator must not write SQL.
* The Master Orchestrator must not synthesize final user-facing answers.
* The Master Orchestrator must not decide retry count.
* It should use chat history to resolve follow-ups such as “what about Malawi?” or “compare that to FY25.”
* It should only route, summarize intent, and produce schema search terms.

### 7. Schema Retrieval Node

Implement deterministic schema retrieval using a read-through schema cache.

The schema retriever is the only component allowed to access Redshift metadata tables such as `information_schema`.

Responsibilities:

* Retrieve schema metadata from cache when available.
* Refresh metadata from Redshift when the cache is missing, expired, or explicitly invalidated.
* Filter schema context based on orchestrator-provided search terms.
* Return only relevant tables and columns to downstream SQL generation agents.

#### Metadata Query

Use the following approved metadata query:

```sql
SELECT
    table_schema,
    table_name,
    column_name,
    data_type,
    ordinal_position
FROM information_schema.columns
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_schema, table_name, ordinal_position
```

The system must retrieve the full schema snapshot and perform filtering in application code rather than repeatedly querying metadata for individual search terms.

Only the schema retrieval component may query `information_schema`.

#### Schema Context Output

Return filtered schema context in this shape:

```python
{
    "tables": [
        {
            "table_schema": "public",
            "table_name": "mlw_upskill_training",
            "columns": [
                {
                    "column_name": "country",
                    "data_type": "varchar"
                },
                {
                    "column_name": "fy_q",
                    "data_type": "varchar"
                }
            ]
        }
    ]
}
```

Filtering should match against:

* table names
* column names
* optional table descriptions
* orchestrator search terms

Example search terms:

```python
["training", "chw", "mlw_upskill"]
```

The filtered schema context is passed to the SQL Generator Agent.

If filtering returns no matching tables, return an empty schema context and route to a clear final response explaining that no relevant schema was found.

### 8. Schema Cache Service

Implement a dedicated schema cache service.

Create:

```text
app/services/schema_cache.py
```

Purpose:

* Avoid repeated `information_schema` scans.
* Reduce Redshift metadata load.
* Improve SQL generation latency.
* Provide deterministic schema context to downstream agents.

#### Cache Strategy

Use a read-through cache.

Flow:

```text
Schema Retrieval Node
    ↓
Schema Cache
    ├─ Cache Hit
    │     ↓
    │  Filter Schema Context
    │     ↓
    │  Return Context
    │
    └─ Cache Miss / Expired
          ↓
    Query information_schema
          ↓
    Build Full Schema Snapshot
          ↓
    Store in Cache
          ↓
    Filter Schema Context
          ↓
    Return Context
```

#### What Gets Cached

Cache the complete schema snapshot, not search-term-specific results.

Example cache key:

```text
agent:schema:redshift:{database}:{schema}
```

Example:

```text
agent:schema:redshift:kpi_data:public
```

Cache payload:

```json
{
  "cached_at": "2026-06-09T12:00:00Z",
  "database": "kpi_data",
  "schema": "public",
  "tables": []
}
```

The `tables` array should contain grouped table metadata:

```json
{
  "table_schema": "public",
  "table_name": "mlw_upskill_training",
  "columns": [
    {
      "column_name": "country",
      "data_type": "varchar",
      "ordinal_position": 1
    }
  ]
}
```

#### Storage Options

Development:

```python
dict[str, Any]
```

Production:

* Redis preferred
* PostgreSQL JSONB cache table optional

#### TTL

Default:

```env
SCHEMA_CACHE_TTL_SECONDS=86400
```

This is 24 hours.

#### Cache Refresh Rules

Refresh schema when:

* cache entry is missing
* cache entry TTL has expired
* manual refresh is requested
* application startup warmup runs
* SQL execution fails with a schema-related error:

  * `relation does not exist`
  * `column does not exist`
  * `schema does not exist`

For schema-related SQL failures, the graph should follow this path:

```text
Execute SQL
    ↓
Schema Error?
    ↓ yes
Refresh Schema Cache
    ↓
Run Retry Controller
    ↓
If retry allowed, run SQL Corrector Agent with refreshed schema context
```

This ensures the SQL Corrector receives the latest schema before attempting a repair.

#### Schema Cache Interface

Implement an interface like:

```python
class SchemaCache:
    def get_schema_context(
        self,
        search_terms: list[str],
        database: str,
        schema_name: str | None = None,
        force_refresh: bool = False
    ) -> dict[str, Any]:
        ...
```

The service should:

1. Load the full schema snapshot from cache.
2. Refresh if missing or expired.
3. Refresh if `force_refresh=True`.
4. Filter the snapshot using search terms.
5. Return only relevant schema context to downstream agents.

#### Filtering Requirements

Filtering must be deterministic and performed in application code.

Recommended behavior:

* Normalize search terms to lowercase.
* Normalize table names and column names to lowercase.
* Include a table if:

  * any search term appears in the table name;
  * any search term appears in a column name;
  * any search term appears in an optional table description;
  * or a country/domain prefix maps clearly to the table name.

If a table matches, include all columns for that table so the SQL Generator has enough context.

If many tables match, cap the returned context to a configurable limit, such as:

```env
MAX_SCHEMA_TABLES_RETURNED=25
```

Include metadata in the returned context:

```python
{
    "tables": [...],
    "metadata": {
        "cache_hit": True,
        "cached_at": "...",
        "force_refresh": False,
        "search_terms": ["training", "chw", "mlw_upskill"],
        "matched_table_count": 3
    }
}
```

### 9. SQL Generator Agent

The SQL Generator receives:

* user question
* chat history when useful
* schema context
* database rules
* KPI acronym/domain guidance

It outputs strict JSON:

```json
{
  "sql": "SELECT ...",
  "assumptions": ["Using fy_q for fiscal-year filtering."],
  "confidence": "medium"
}
```

SQL generation rules:

* Only generate `SELECT` or `WITH ... SELECT`.
* Never generate write statements.
* Never use `SELECT *`.
* Use only verified tables and columns from schema context.
* Prefer simple SQL.
* Prefer aggregates over raw rows.
* Use `LIMIT` for detail queries.
* For fiscal years, prefer `fy_q` when available.
* For numeric-looking varchar columns, start with simple safe cleaning:

```sql
SUM(CAST(NULLIF(REPLACE(TRIM(column_name), ',', ''), '') AS INTEGER))
```

* Avoid regex unless a previous failure indicates non-numeric values.

### 10. SQL Validation Guardrail

Implement deterministic validation in Python.

Validator must reject:

* multiple statements
* semicolons except trailing removable semicolon
* comments
* non-SELECT statements
* `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `COPY`, `UNLOAD`, `CALL`, `EXECUTE`, `GRANT`, `REVOKE`
* `information_schema`, `pg_catalog`, `pg_`, `stl_`, `stv_`, `svl_`, `svv_`
* `SELECT *`
* unresolved placeholders such as `undefined`, `NaN`, `{{...}}`, `${...}`

Validator should also:

* normalize whitespace
* remove trailing semicolon
* add `LIMIT 100` if no limit is present
* cap `LIMIT` at 1000
* return the sanitized SQL

### 11. SQL Executor

Implement Redshift query execution.

Requirements:

* read-only connection credentials from environment variables or AWS Secrets Manager
* query timeout
* row limit
* return rows as `list[dict]`
* never throw uncaught exceptions into the API response
* capture SQL errors as structured state:

```python
{
    "query_error": "...",
    "query_result": None
}
```

### 12. Retry Controller Node

Implement a deterministic Retry Controller node.

Create:

```text
app/services/retry_controller.py
```

The Retry Controller must not use an LLM.

Responsibilities:

* Read `retry_count` from state.
* Read `max_sql_retries` from config, sourced from `MAX_SQL_RETRIES`.
* Decide whether another SQL correction attempt is allowed.
* Increment `retry_count` only when routing to the SQL Corrector.
* Set `state["can_retry"]`.

Pseudo-code:

```python
def retry_controller(state: AgentState, config: Settings) -> AgentState:
    retry_count = int(state.get("retry_count", 0))
    max_retries = config.max_sql_retries

    can_retry = bool(state.get("query_error")) and retry_count < max_retries

    state["max_sql_retries"] = max_retries
    state["can_retry"] = can_retry

    if can_retry:
        state["retry_count"] = retry_count + 1

    return state
```

Routing behavior:

```python
if state["can_retry"]:
    return "sql_corrector"
return "final_error"
```

Requirements:

* `MAX_SQL_RETRIES=0` means no correction attempts.
* `MAX_SQL_RETRIES=1` means one correction attempt after the initial SQL execution fails.
* `MAX_SQL_RETRIES=3` means up to three correction attempts after execution failures.
* The SQL Corrector must never be called unless the Retry Controller returns `can_retry=True`.
* The Master Orchestrator must not decide retry count.

### 13. SQL Corrector Agent

Run only when the Retry Controller allows it.

Input:

* original question
* chat history if relevant
* schema context
* failed SQL
* validator output
* Redshift error message
* prior assumptions
* retry count
* max retries

Output strict JSON:

```json
{
  "corrected_sql": "SELECT ...",
  "correction_reason": "Removed commas before integer casting."
}
```

Rules:

* Correct only the SQL.
* Use only verified schema.
* Do not change the user’s analytical intent.
* Prefer minimal fixes.
* Do not decide whether to retry again. That belongs only to the Retry Controller.

### 14. Format Query Result Node

Create Markdown preview table.

Output:

```python
{
    "row_count": len(rows),
    "preview_markdown": "...",
    "truncated": bool
}
```

Show up to 20 preview rows.

Escape pipe characters in Markdown cells.

### 15. Final Answer Agent

The Final Answer Agent is distinct from the Master Orchestrator.

Responsibilities:

* Synthesize the final user-facing response.
* Use the question, chat history, page context, route decision, SQL metadata, query result preview, assumptions, and errors.
* Answer direct no-database questions.
* Summarize database-backed results.
* Include SQL used if database was queried.
* Include Markdown preview table if available.
* State assumptions clearly.
* If the correct table or column cannot be identified, say so clearly and ask for clarification.

Use this format:

````markdown
## Answer

...

## SQL Used

```sql
...
```

## Data Preview

...
````

### 16. Final Error Response Node

Create a deterministic final error node for retry exhaustion.

It should return:

```python
{
    "ok": False,
    "final_error": "I could not complete the query after the configured retry limit.",
    "final_answer": "...",
    "retry_count": state["retry_count"],
    "max_sql_retries": state["max_sql_retries"],
    "query_error": state["query_error"],
    "validated_sql": state.get("validated_sql"),
}
```

The final error response should be clear and user-facing, but should not expose stack traces or credentials.

## Project Structure

Create or adapt these files after inspecting the existing repository structure:

```text
app/
  main.py
  config.py
  graph.py
  state.py
  models.py

  agents/
    master_orchestrator.py
    sql_generator.py
    sql_corrector.py
    final_answer.py

  services/
    bedrock.py
    redshift.py
    schema_cache.py
    chat_memory.py
    retry_controller.py
    sql_validator.py
    result_formatter.py

  prompts/
    master_orchestrator.md
    sql_generator.md
    sql_corrector.md
    final_answer.md

  tests/
    test_sql_validator.py
    test_result_formatter.py
    test_retry_controller.py
    test_chat_memory.py
    test_graph_routes.py
```

## LangGraph Routing Requirements

Build the graph using deterministic conditional edges.

Required graph behavior:

```text
START
→ derive_session_id
→ save_user_message
→ load_chat_memory
→ master_orchestrator
→ save_orchestrator_decision
→ route_database_decision

if needs_database == false:
    → final_answer_agent
    → save_final_response
    → END

if needs_database == true:
    → schema_retrieval
    → sql_generator
    → sql_validator
    → sql_executor
    → route_query_result

if query_error is None:
    → result_formatter
    → final_answer_agent
    → save_final_response
    → END

if query_error is not None:
    → retry_controller
    → route_retry_decision

if can_retry == true:
    → sql_corrector
    → sql_validator
    → sql_executor
    → route_query_result

if can_retry == false:
    → final_error_response
    → save_final_response
    → END
```

Do not implement retry logic inside the SQL Corrector, SQL Executor, or Master Orchestrator.

## Testing

Add tests for:

* SQL validator rejects unsafe statements
* SQL validator adds/caps limits
* schema retrieval returns expected structure with mocked Redshift
* executor captures SQL errors instead of throwing
* retry controller respects `MAX_SQL_RETRIES=0`
* retry controller increments retry count only when retrying
* retry controller stops after max retries
* graph routes no-database questions to final answer agent directly
* graph routes database questions through schema → generator → validator → executor
* graph calls corrector only when Retry Controller allows it
* final error response after retry exhaustion
* chat memory derives session ID correctly
* chat memory loads history by `session_id`
* chat memory saves user and assistant turns to Postgres
* `/chat` is async and preserves page context as dict/list and XML

## Deliverables

Return complete code for the FastAPI + LangGraph service.

Include:

* repository inspection summary before file changes
* runnable `main.py`
* graph construction
* Pydantic models
* prompt files
* SQL validator
* Redshift service
* schema cache service
* chat memory service
* retry controller service
* result formatter
* example `.env.example`
* pytest tests
* brief README with setup and run instructions
