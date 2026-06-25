#!/usr/bin/env python3
"""
Standalone benchmark harness for the KPI analytics agent.

This script is intentionally external to the application code path: it does not
import the agent graph, patch runtime behavior, or modify any server logic.
Instead, it behaves like a regular client and measures end-to-end latency by
issuing HTTP requests against the existing FastAPI API. That makes it useful
when you want to benchmark the real query-to-response experience without
altering the code behind the agent itself.

Typical usage:

1. Benchmark an already running local server:

   python benchmark.py --base-url http://127.0.0.1:8000 --include-cold-start

2. Start the existing uvicorn app automatically, wait for /health to respond,
   run the benchmarks, and then stop the temporary server process:

   python benchmark.py --start-server --include-cold-start

3. Produce machine-readable output for later analysis or spreadsheet import:

   python benchmark.py --start-server --json

What the script measures:

- A configurable set of example prompts defined in DEFAULT_QUERIES.
- Optional "cold start" timing for one first request per prompt.
- A configurable number of warm runs per prompt.
- End-to-end request duration for POST /api/agent/query.
- A few high-level response fields such as ok, needs_database, row_count, and
  a short answer excerpt for quick inspection.

How to interpret the output:

- Cold-start timing is useful for catching one-time overhead such as model
  initialization, connection setup, schema caching, or startup-related latency.
- Warm timings are better for estimating steady-state user experience once the
  service is already active.
- Database-backed prompts will usually be slower than purely explanatory
  prompts because they may route through schema retrieval, SQL generation,
  validation, execution, formatting, and final answer generation.

Important behavior notes:

- Each request gets a unique generated session_id so runs do not accidentally
  collapse into the same conversational session.
- The benchmark targets the public structured endpoint instead of internal
  Python functions, which keeps the measurement realistic.
- The script assumes the service is reachable locally unless --base-url points
  somewhere else.
- It does not write benchmark results to a file; redirect stdout if you want to
  save the report.
"""
from __future__ import annotations

import argparse
import json
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_QUERIES: tuple[dict[str, Any], ...] = (
    {
        "label": "direct_help",
        "message": "What is a KPI?",
        "page_context": {},
    },
    {
        "label": "show_metrics",
        "message": "Show KPI metrics",
        "page_context": {},
    },
    {
        "label": "training_trend_malawi",
        "message": "Show the training KPI trend for Malawi",
        "page_context": {"selected_kpi": "training", "country": "Malawi"},
    },
)


@dataclass
class BenchmarkResult:
    label: str
    message: str
    cold_start_sec: float | None
    runs: list[float]
    ok: bool | None
    needs_database: bool | None
    row_count: int | None
    error: str | None
    answer_excerpt: str

    @property
    def avg_sec(self) -> float | None:
        return statistics.mean(self.runs) if self.runs else None

    @property
    def min_sec(self) -> float | None:
        return min(self.runs) if self.runs else None

    @property
    def max_sec(self) -> float | None:
        return max(self.runs) if self.runs else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark query-to-response latency for the KPI analytics agent without modifying the service."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL for the running agent service.")
    parser.add_argument("--endpoint", default="/api/agent/query", help="Benchmark target endpoint.")
    parser.add_argument("--health-endpoint", default="/health", help="Health endpoint used when waiting for the server.")
    parser.add_argument("--user-id-prefix", default="benchmark-user", help="Prefix used for generated benchmark user IDs.")
    parser.add_argument("--database", default="kpi_data", help="Database value sent to the API.")
    parser.add_argument("--runs", type=int, default=3, help="Number of warm benchmark runs per query.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds.")
    parser.add_argument(
        "--include-cold-start",
        action="store_true",
        help="Measure a single cold-start-style request before the warm runs for each query.",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="Start the existing FastAPI service with uvicorn before benchmarking.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to use when starting uvicorn.")
    parser.add_argument("--port", type=int, default=8000, help="Port to use when starting uvicorn.")
    parser.add_argument(
        "--app",
        default="app.main:app",
        help="ASGI app import path used when starting uvicorn.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON results instead of the default terminal report.",
    )
    return parser.parse_args()


def build_url(base_url: str, endpoint: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))


def post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[float, int | None, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as exc:
        body = _load_error_body(exc)
        status = exc.code
    elapsed = time.perf_counter() - start
    return elapsed, status, body


def print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _load_error_body(exc: urllib.error.HTTPError) -> dict[str, Any]:
    raw = exc.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"error": raw}
    return {"http_error": exc.code, "body": parsed}


def benchmark_query(
    *,
    url: str,
    query: dict[str, Any],
    user_id_prefix: str,
    database: str,
    runs: int,
    timeout: float,
    include_cold_start: bool,
) -> BenchmarkResult:
    label = str(query["label"])
    message = str(query["message"])
    page_context = dict(query.get("page_context", {}))

    cold_start_sec: float | None = None
    response_body: dict[str, Any] = {}

    request_index = 0
    total_requests = runs + (1 if include_cold_start else 0)
    if include_cold_start:
        request_index += 1
        payload = build_payload(
            user_id_prefix=user_id_prefix,
            label=label,
            message=message,
            page_context=page_context,
            database=database,
            request_index=request_index,
        )
        cold_start_sec, _, response_body = perform_request(
            url=url,
            payload=payload,
            timeout=timeout,
            label=label,
            phase="cold start",
            request_index=request_index,
            total_requests=total_requests,
        )

    timings: list[float] = []
    for warm_run_index in range(1, runs + 1):
        request_index += 1
        payload = build_payload(
            user_id_prefix=user_id_prefix,
            label=label,
            message=message,
            page_context=page_context,
            database=database,
            request_index=request_index,
        )
        elapsed, _, response_body = perform_request(
            url=url,
            payload=payload,
            timeout=timeout,
            label=label,
            phase=f"warm {warm_run_index}/{runs}",
            request_index=request_index,
            total_requests=total_requests,
        )
        timings.append(elapsed)

    answer = build_answer_excerpt(response_body.get("answer"))
    return BenchmarkResult(
        label=label,
        message=message,
        cold_start_sec=cold_start_sec,
        runs=timings,
        ok=_coerce_bool(response_body.get("ok")),
        needs_database=_coerce_bool(response_body.get("needs_database")),
        row_count=_coerce_int(response_body.get("row_count")),
        error=_coerce_str(response_body.get("error")),
        answer_excerpt=answer[:180],
    )


def build_payload(
    *,
    user_id_prefix: str,
    label: str,
    message: str,
    page_context: dict[str, Any],
    database: str,
    request_index: int,
) -> dict[str, Any]:
    session_id = f"{user_id_prefix}-{label}-{request_index}"
    return {
        "user_id": session_id,
        "message": message,
        "page_context": {
            **page_context,
            "session_id": session_id,
        },
        "database": database,
    }


def perform_request(
    *,
    url: str,
    payload: dict[str, Any],
    timeout: float,
    label: str,
    phase: str,
    request_index: int,
    total_requests: int,
) -> tuple[float, int | None, dict[str, Any]]:
    session_id = str(payload["page_context"]["session_id"])
    print_progress(f"[{label}] -> sending {phase} request {request_index}/{total_requests} ({session_id})")
    elapsed, status, body = post_json(url, payload, timeout)
    print_progress(
        f"[{label}] <- received {phase} response {request_index}/{total_requests} "
        f"status={status if status is not None else '?'} in {elapsed:.3f}s"
    )
    return elapsed, status, body


def build_answer_excerpt(answer: Any, limit: int = 180) -> str:
    text = str(answer or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _coerce_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _coerce_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _coerce_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def wait_for_healthcheck(health_url: str, timeout: float) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.5)
    if last_error is not None:
        raise RuntimeError(f"Server did not become healthy at {health_url}: {last_error}") from last_error
    raise RuntimeError(f"Server did not become healthy at {health_url}.")


def start_server(app: str, host: str, port: int, health_url: str) -> subprocess.Popen[str]:
    print_progress(f"Starting server with {app} on http://{host}:{port}")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        app,
        "--host",
        host,
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        print_progress(f"Waiting for health check at {health_url}")
        wait_for_healthcheck(health_url, timeout=30.0)
        print_progress("Server is healthy")
        return process
    except Exception:
        stop_server(process)
        raise


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    print_progress("Stopping benchmark server")
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def render_terminal(results: list[BenchmarkResult], include_cold_start: bool) -> str:
    lines = ["Agent benchmark", "================", ""]
    for index, result in enumerate(results, start=1):
        runs = ", ".join(f"{value:.3f}s" for value in result.runs)
        lines.extend(
            [
                f"{index}. {result.label}",
                f"   Query: {result.message}",
                f"   Warm runs: {runs}",
                f"   Avg / Min / Max: {result.avg_sec:.3f}s / {result.min_sec:.3f}s / {result.max_sec:.3f}s",
                f"   OK / Needs DB / Row count: {_format_bool(result.ok)} / {_format_bool(result.needs_database)} / {_format_value(result.row_count)}",
                f"   Error: {result.error or '-'}",
            ]
        )
        if include_cold_start:
            lines.append(f"   Cold start: {_format_duration(result.cold_start_sec)}")
        lines.append("   Answer excerpt:")

        excerpt_lines = (result.answer_excerpt or "(no answer excerpt captured)").splitlines()
        for line in excerpt_lines:
            lines.append(f"     {line}")

        if index < len(results):
            lines.append("")
    return "\n".join(lines)


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _format_duration(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}s"


def _format_value(value: Any) -> str:
    return "-" if value is None else str(value)


def render_json(results: list[BenchmarkResult]) -> str:
    payload = []
    for result in results:
        payload.append(
            {
                "label": result.label,
                "message": result.message,
                "cold_start_sec": round(result.cold_start_sec, 3) if result.cold_start_sec is not None else None,
                "runs": [round(value, 3) for value in result.runs],
                "avg_sec": round(result.avg_sec, 3) if result.avg_sec is not None else None,
                "min_sec": round(result.min_sec, 3) if result.min_sec is not None else None,
                "max_sec": round(result.max_sec, 3) if result.max_sec is not None else None,
                "ok": result.ok,
                "needs_database": result.needs_database,
                "row_count": result.row_count,
                "error": result.error,
                "answer_excerpt": result.answer_excerpt,
            }
        )
    return json.dumps(payload, indent=2)


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    base_url = args.base_url
    if args.start_server:
        base_url = f"http://{args.host}:{args.port}"

    benchmark_url = build_url(base_url, args.endpoint)
    health_url = build_url(base_url, args.health_endpoint)

    server_process: subprocess.Popen[str] | None = None
    try:
        if args.start_server:
            server_process = start_server(args.app, args.host, args.port, health_url)

        results = [
            benchmark_query(
                url=benchmark_url,
                query=query,
                user_id_prefix=args.user_id_prefix,
                database=args.database,
                runs=args.runs,
                timeout=args.timeout,
                include_cold_start=args.include_cold_start,
            )
            for query in DEFAULT_QUERIES
        ]
    finally:
        if server_process is not None:
            stop_server(server_process)

    if args.json:
        print(render_json(results))
    else:
        print(render_terminal(results, include_cold_start=args.include_cold_start))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
