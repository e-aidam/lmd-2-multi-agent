# KPI Analytics Agent

This repository includes a FastAPI + LangGraph backend for a text-to-SQL KPI analytics agent.

## Repository Inspection Summary

- Existing target files included `main.py`, `agent.py`, `requirements.txt`, `Dockerfile`, `start-dev.sh`, `.env`, and deployment workflow files.
- The public portal API shape from `main.py` was preserved: `GET /`, async `POST /chat`, `ChatRequest`, `interact(...)`, and `format_output(...)`.
- The implementation now lives under `app/`, with top-level `main.py` and `agent.py` kept as compatibility/deployment entrypoints.

## Setup

```bash
uv venv --python 3.13 .venv
source .venv/bin/activate
pip install ".[test]"
cp .env.example .env
```

Fill in `.env` with AWS Bedrock, Redshift, and Postgres memory settings. The checked-in example includes every runtime variable the service reads. The service also understands existing deployment aliases:

- `LMD_AWS_REGION` as a fallback for `AWS_REGION`
- `LMD_AWS_ACCESS_KEY_ID` and `LMD_AWS_SECRET_ACCESS_KEY` as fallbacks for AWS credentials
- `MODEL_ID` as the default for the master orchestrator and final answer agents (higher-accuracy work)
- `MODEL_ID_FAST` as the default for the SQL generator and SQL corrector agents (defaults to a Claude Haiku model, since SQL generation/correction is mechanical and benefits from lower latency/cost)
- any explicit `BEDROCK_MODEL_MASTER` / `BEDROCK_MODEL_SQL` / `BEDROCK_MODEL_CORRECTOR` / `BEDROCK_MODEL_FINAL` overrides the corresponding per-agent default
- `REDSHIFT_URI`, `DB_URI`, or `DATABASE_URL_READER` as a source for Redshift host/user/password
- `MEM_DB_URI` for Postgres-backed chat memory

The canonical analytics database remains `kpi_data`.

## Run

```bash
. .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Primary portal-compatible endpoints:

- `GET /`
- `POST /chat`

Additional structured endpoints:

- `GET /health`
- `POST /api/agent/query`

### Dashboard (Power BI) context

Both `POST /chat` and `POST /api/agent/query` accept a `page_context` payload describing what the
user is looking at in the portal. To give the agent structural awareness of the current KPI
dashboard, the frontend should include a `route` field set to the dashboard route slug:

- `global-scale`, `ethiopia`, `liberia`, `malawi`, `sierra_leone`

(`page`, `pathname`, or `path` — e.g. `/kpi-dashboard/malawi` — are also accepted; the last path
segment is used.) On each request the backend resolves that slug through `DashboardContextService`
(`app/services/dashboard_context.py`), which loads `app/data/dashboard_context.json` — a per-route
summary of that dashboard's KPIs, theory-of-change levels, chart types, and filters. The resolved
summary is attached to agent state at `state["context"]["dashboard_context"]` and passed to the
Master Orchestrator and SQL Generator so they can bias schema search and SQL toward the country/KPIs
the user is viewing. An unknown or absent route resolves to an empty summary (no behavior change).

`app/data/dashboard_context.json` is sourced from the portal repo's KPI metadata; update it when the
dashboards change.

## Tests

```bash
. .venv/bin/activate
pytest
```

Most tests use fakes and do not require AWS, Redshift, or Postgres. Optional Postgres memory integration tests can be added with `TEST_MEM_DB_URI`.

# Agent benchmark

| Query | Warm runs (s) | Avg (s) | Min (s) | Max (s) | Cold start (s) | OK | Needs DB | Row count | Error |
|---|---:|---:|---:|---:|---:|---|---|---:|---|
| `What is a KPI?` | 4.540, 5.080, 5.157 | 4.926 | 4.540 | 5.157 | 5.428 | True | False | - | - |
| `Show KPI metrics` | 19.756, 17.000, 13.221 | 16.659 | 13.221 | 19.756 | 21.605 | True | True | 6 | - |
| `Show the training KPI trend for Malawi` | 10.821, 11.786, 14.436 | 12.347 | 10.821 | 14.436 | 12.390 | True | True | 0 | - |

## Answer excerpts

- **direct_help**: ## Answer  A KPI (Key Performance Indicator) is a measurable value that demonstrates how effectively an organization, team, or individual is achieving key business objectives. KPIs
- **show_metrics**: ## Answer  Here are the current KPI metrics for your system:  - **Total KPI Approvals**: 214 records - **Approved KPIs**: 0 (no KPIs currently have approved status) - **Pending KPI
- **training_trend_malawi**: ## Answer  I was unable to retrieve the training KPI trend data for Malawi. The query executed successfully but returned no results, which suggests that either:  1. There is no tra
