# Prompt for Claude Fable 5 — LMD 2.0 Next Steps

Copy everything below the line into Fable 5 (ideally with repo/tool access to `lmd-2-multi-agent`).

---

You are working on the backend for Last Mile Health's Last Mile Data Portal (LMD) 2.0, a text-to-SQL analytics agent that lets community health program staff ask natural-language questions about KPI data stored in Amazon Redshift. The service is a FastAPI + LangGraph app living in this repository, with the graph defined in `app/graph.py`, agents in `app/agents/`, supporting services in `app/services/`, per-agent prompt templates in `app/prompts/`, and configuration in `app/config.py`. It also ships a deterministic non-LangGraph fallback path (`KPIAnalyticsGraph._run_fallback`) that must stay behaviorally identical to the LangGraph path, since `langgraph` may not be importable in some environments. Tests live in `tests/` and mostly run against fakes rather than live AWS/Redshift/Postgres.

A progress report on this project just shipped, and it lists several "Next Steps" for the following phase. I want you to implement three of them. Treat each as a self-contained task with its own acceptance criteria, but keep all three consistent with each other and with existing code conventions (frozen dataclasses for settings, `TypedDict` for `AgentState`, async agent methods, prompt text loaded via `load_prompt(...)` from `app/prompts/*.md`, JSON-in/JSON-out Bedrock calls via `BedrockService.generate_json`). Do not change the public request/response shape of `POST /chat` or `POST /api/agent/query` unless a task below explicitly requires it, and if it does, update `app/models.py`, `README.md`, and the relevant tests in the same change.

Before writing code, inspect the current implementation of each area named below so your changes slot into the existing pattern rather than inventing a parallel one.

## Task 1 — LLM Model Adjustments (right-size models per agent)

Today, `app/config.py` defines four independent Bedrock model settings — `BEDROCK_MODEL_MASTER`, `BEDROCK_MODEL_SQL`, `BEDROCK_MODEL_CORRECTOR`, `BEDROCK_MODEL_FINAL` — but `Settings.from_env` falls all four back to the same `MODEL_ID` default (currently `us.anthropic.claude-sonnet-4-20250514-v1:0`) when the specific env var is unset. There is no differentiation by workload today, which is exactly the latency/cost problem the report calls out.

Implement per-agent default model routing:

1. Give `SQLGeneratorAgent` and `SQLCorrectorAgent` a faster/cheaper default (a Claude Haiku Bedrock model id) instead of silently inheriting `MODEL_ID`, while `MasterOrchestratorAgent` and `FinalAnswerAgent` keep a stronger default (the current Sonnet default), since routing and final-response synthesis have a higher accuracy bar. Preserve the existing override behavior — an explicit `BEDROCK_MODEL_SQL`/`BEDROCK_MODEL_CORRECTOR`/etc. in the environment must still win.
2. Update `.env.example` to document the new per-agent defaults and explain (in a comment) why SQL generation/correction default to Haiku.
3. Update `README.md`'s setup section if the defaults you choose change onboarding instructions.
4. `Settings.validate_runtime()` currently requires all four `BEDROCK_MODEL_*` values to be non-empty in production. Confirm your new defaulting logic still satisfies that check, and add/update a unit test (near the existing config tests) asserting the SQL/corrector defaults differ from the master/final defaults when no env override is present.
5. Update `benchmark.py` and its expectations if it hardcodes model ids or timing assumptions that would change materially under a faster SQL model (don't fabricate new benchmark numbers — just make sure nothing breaks).

Acceptance check: with a clean `.env` (no `BEDROCK_MODEL_*` set, only `MODEL_ID` optionally set), `get_settings()` should resolve four different, correct model ids for the four agents, and `pytest` should still pass.

## Task 2 — Power BI / Dashboard Context Injection

`MasterOrchestratorAgent.route(...)` already accepts a `page_context` argument, and `AgentState["context"]["page_context"]` already flows through `app/graph.py` and into `SQLGeneratorAgent` and `FinalAnswerAgent`. Right now `page_context` only carries whatever the frontend happens to pass per-request (e.g. `selected_kpi`, `session_id` — see `tests/test_main_api.py` and `benchmark.py` for the current shape). It does **not** carry any structural knowledge of what's actually on the dashboards.

The report's "Power BI Context" next step asks us to inject awareness of the portal's dashboard pages so the agent understands what KPIs, filters, and views a user is likely looking at when they ask a question. The relevant frontend files (in the separate Next.js portal repo, not this backend repo) are:

- `src/app/(protected)/kpi-dashboard/global-scale/page.tsx`
- `src/app/(protected)/kpi-dashboard/ethiopia/page.tsx`
- `src/app/(protected)/kpi-dashboard/liberia/page.tsx`
- `src/app/(protected)/kpi-dashboard/malawi/page.tsx`
- `src/app/(protected)/kpi-dashboard/sierra_leone/page.tsx`

Since those files live outside this repo, design this as an ingestion step rather than assuming the files are present here:

1. Add a small `DashboardContextService` (in `app/services/`) that loads a structured summary per dashboard route — e.g. a JSON/YAML fixture checked into this repo at something like `app/data/dashboard_context.json`, keyed by route slug (`global-scale`, `ethiopia`, `liberia`, `malawi`, `sierra_leone`), each entry describing the KPIs, chart types, and filters that page exposes. Ask me for the actual `page.tsx` contents if you need them to populate this fixture accurately; otherwise stub it with a clearly-marked placeholder schema so it's easy to fill in later.
2. Extend `AgentState["context"]` to carry a `dashboard_context` key populated from this service, keyed off whatever route identifier the frontend already sends in `page_context` (check `page_context.dict` for something like a `route` or `page` field — if that field doesn't exist yet, add it to the expected `page_context` shape and document it in `README.md`).
3. Pass `dashboard_context` into `MasterOrchestratorAgent.route(...)` and `SQLGeneratorAgent` alongside the existing `page_context`, and update `app/prompts/master_orchestrator.md` and `app/prompts/sql_generator.md` so the LLM is told how to use it (e.g., "if the user is on the Malawi dashboard, prefer filtering to Malawi unless they say otherwise").
4. Update the heuristic fallback routing in `MasterOrchestratorAgent._heuristic_route` to also factor in `dashboard_context` terms, mirroring how it already folds in `page_context` via `_stringify_context`.
5. Add tests covering: a request tagged with a known dashboard route gets the right `dashboard_context` attached to state, and the heuristic router's search terms include dashboard-derived terms.

Acceptance check: a `/chat` request with `page_context` indicating the Malawi dashboard route should result in `schema_search_terms` and the SQL generator payload both reflecting Malawi-specific context, verifiable via a new/updated test in `tests/`.

## Task 3 — Dynamic Visualization Agent

Today, query results only ever become a markdown table: `app/services/result_formatter.py::format_query_result` turns `query_result` rows into `preview_markdown`, and that's what `FinalAnswerAgent` surfaces. There's no chart/graph generation anywhere in the graph.

Add a new `VisualizationAgent` (in `app/agents/visualization_agent.py`, with its prompt in `app/prompts/visualization_agent.md`) that the Master Orchestrator can trigger dynamically:

1. Extend the Master Orchestrator's JSON output contract (and `app/prompts/master_orchestrator.md`) with a `needs_visualization: bool` field, decided the same way `needs_database` is today, alongside a heuristic fallback (extend `MasterOrchestratorAgent._heuristic_route` with chart-intent markers like "chart", "graph", "trend", "compare", "over time", "plot").
2. Add `needs_visualization`, `chart_spec`, and `visualization_error` fields to `AgentState` (`app/state.py`).
3. Wire a new `visualization_agent` node into both `KPIAnalyticsGraph._build_langgraph` and `KPIAnalyticsGraph._run_fallback`, so it runs after `result_formatter` (it needs `query_result`/rows to work with) and before `final_answer_agent`, but only actually calls the LLM/builds a spec when `state["needs_visualization"]` is true — otherwise it's a no-op passthrough. Keep the two execution paths behaviorally identical, the same way every other node pair does today.
4. The agent should turn `query_result` rows into a minimal, frontend-renderable chart spec — pick a simple, well-documented JSON shape (e.g. `{"chart_type": "line"|"bar"|"pie", "x_field": ..., "y_field": ..., "series_field": null|..., "title": ...}`) rather than a heavyweight spec language, so the portal frontend can map it to whatever charting library it already uses. Document the shape in `README.md`.
5. Update `FinalAnswerAgent` and `app/prompts/final_answer.md` so that when `chart_spec` is present, the final response references it appropriately (e.g., includes a short caption and doesn't just repeat the raw table if a chart is being shown), and confirm the API response models in `app/models.py` expose `chart_spec` to callers when present.
6. Add tests: one where a chart-worthy question with real rows produces a valid `chart_spec`; one where `needs_visualization` is false and the node is a clean no-op; one where visualization fails gracefully (e.g., empty rows) without breaking the overall response.

Acceptance check: sending a request like "show the training KPI trend for Malawi over time" through the graph (against the existing test fakes, not live Redshift) results in a populated, schema-valid `chart_spec` in the final state, and `pytest` passes for both the LangGraph and fallback code paths.

## General constraints for all three tasks

Keep changes minimal and consistent with existing style — no new dependencies unless clearly justified (state why, and update `requirements.txt`/`pyproject.toml` if you add one). Every behavior change needs a corresponding test using the existing fake/stub patterns already in `tests/` (no live AWS Bedrock, Redshift, or Postgres calls in tests). Run the full `pytest` suite after each task and paste the results. If you hit a genuine ambiguity — especially in Task 2, where the actual dashboard `page.tsx` content isn't available in this repo — stop and ask rather than guessing at frontend structure.

## Git / GitHub workflow — merge after each task

The repo currently sits on `main`, tracking a personal fork remote (`personal` → `e-aidam/lmd-2-agent`), with the org repo available as `origin` (`Last-Mile-Health/lmd-2-agent`). Treat each of the three tasks above as its own isolated, mergeable unit of work:

1. Before starting a task, create a dedicated branch off `main`, e.g. `git checkout -b task-1-model-routing` (`task-2-dashboard-context`, `task-3-visualization-agent`).
2. Implement that task only, keep its diff scoped to what the task describes, and commit with a clear message (e.g. `git commit -m "Route SQL generator/corrector to Haiku by default"`).
3. Run the full `pytest` suite and confirm it's green before merging — do not merge on red tests.
4. Push the branch (`git push -u personal task-1-model-routing`, or `origin` if you have write access there and that's the intended target — ask me if it's unclear which remote to push to).
5. Merge the branch into `main`: either open a pull request and merge it once CI (`.github/workflows/deploy.yml`) passes, or merge locally with `git checkout main && git merge --no-ff task-1-model-routing && git push` if we've agreed direct merges are fine — tell me which you did.
6. Only after that merge is confirmed pushed to GitHub should you branch off the updated `main` for the next task, so each task builds on a clean, already-merged base rather than stacking unmerged branches.

If a push or merge fails (auth, conflicts, protected branch, failing CI), stop and report the exact error rather than force-pushing or bypassing checks.

Work through the tasks in order (1, then 2, then 3) — implement, test, merge to GitHub, then move to the next — and give me a short summary plus a diff after each one before moving on.
