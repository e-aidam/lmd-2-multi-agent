import benchmark


def test_render_terminal_adds_spacing_between_answer_excerpts() -> None:
    results = [
        benchmark.BenchmarkResult(
            label="first",
            message="What is a KPI?",
            cold_start_sec=1.234,
            runs=[0.5, 0.6],
            ok=True,
            needs_database=False,
            row_count=0,
            error=None,
            answer_excerpt="First answer",
        ),
        benchmark.BenchmarkResult(
            label="second",
            message="Show KPI metrics",
            cold_start_sec=2.345,
            runs=[1.1, 1.2],
            ok=True,
            needs_database=True,
            row_count=5,
            error=None,
            answer_excerpt="Second answer",
        ),
    ]

    rendered = benchmark.render_terminal(results, include_cold_start=True)

    assert "   Answer excerpt:\n     First answer\n\n2. second" in rendered
    assert "   Cold start: 1.234s" in rendered


def test_benchmark_query_prints_progress_to_stderr(capsys) -> None:
    calls = 0

    def fake_post_json(url: str, payload: dict[str, object], timeout: float) -> tuple[float, int, dict[str, object]]:
        nonlocal calls
        calls += 1
        return 0.25, 200, {"answer": "Ready", "ok": True, "needs_database": False, "row_count": 0}

    original_post_json = benchmark.post_json
    benchmark.post_json = fake_post_json
    try:
        result = benchmark.benchmark_query(
            url="http://example.test/api/agent/query",
            query={"label": "direct_help", "message": "What is a KPI?", "page_context": {}},
            user_id_prefix="bench",
            database="kpi_data",
            runs=2,
            timeout=10.0,
            include_cold_start=True,
        )
    finally:
        benchmark.post_json = original_post_json

    captured = capsys.readouterr()

    assert calls == 3
    assert "[direct_help] -> sending cold start request 1/3" in captured.err
    assert "[direct_help] <- received warm 2/2 response 3/3 status=200 in 0.250s" in captured.err
    assert result.answer_excerpt == "Ready"
