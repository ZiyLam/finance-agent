# Engineering verification baseline

Last reviewed: 2026-08-02. This is a personal-development project, not a
production service. Measurements and tests below are reproducible evidence for
the current codebase; they are not uptime, real-time market-data, or investment
performance claims.

## Reproducible entry points

```powershell
cd 'G:\Program Files\Codex\finance-agent'
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' -m pip install -e .
$env:PYTHONPATH = 'src'
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' scripts/measure_fast_path.py --iterations 50
node --test tests/test_web_api_client.js
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' scripts/export_openapi.py --output "$env:TEMP\finance-agent-openapi.json"
& 'G:\Program Files\Codex\.venv\Scripts\python.exe' scripts/generate_design_tokens.py --check
```

The local Web entry is `finance-agent-api` followed by
`http://127.0.0.1:8000/web/`; the authenticated mini-program API contract and
personal-only deployment limits are in [mini-program-backend.md](mini-program-backend.md).
API-only mode, strict CORS, and independent Web URL resolution are covered by
`test_api_deployment.py` and `test_web_api_client.js`.

Current suite result: **208 Python tests passed in 5.983 seconds**, plus **4
JavaScript tests passed in 0.470 seconds**, on 2026-08-02.

## Automated-test classification and risk coverage

| Test type | Main evidence | High-risk behavior covered |
| --- | --- | --- |
| Unit | `test_input_parser.py`, `test_entity_resolution.py`, adapter tests, `test_tools.py` | input limits, invalid/missing dates, unknown tools, provider gating, safe error redaction |
| Integration | `test_api.py`, `test_research_service.py`, `test_web_workspace.py`, `test_langchain_integration.py` | user/session ownership, clarification before queueing, deterministic report path, Web/API wiring |
| Deployment contract | `test_api_deployment.py`, `test_web_api_client.js`, `scripts/export_openapi.py` | API-only startup, static-host compatibility, strict CORS, independent API URL resolution, OpenAPI export |
| Cross-client contract | `test_design_tokens.py`, `test_frontend_contracts.py`, `scripts/generate_design_tokens.py` | generated Web/WXSS variables, one request gateway per client, mini-program compatibility, and OpenAPI call coverage |
| Regression | `test_analysis_execution.py`, `test_research_report.py`, `test_beginner_research.py`, `test_source_connectivity.py` | evidence provenance, source fallback, unavailable/malformed data, stale local-service state, source timeouts |
| Performance | `test_performance.py`, `scripts/measure_fast_path.py` | deterministic fast path, bounded timeout return, and identical in-flight request coalescing |

| Required scenario | Verified behavior and evidence |
| --- | --- |
| Missing or stale data | Empty/malformed/no-candle responses become `market_data.status=unavailable`; no price is fabricated (`test_tool_failure_is_presented_as_unavailable_not_fabricated_data`). Freshness/source limitations remain part of snapshot and report payloads. |
| Source failure and degradation | An EODHD failure falls back once to yfinance when it returns usable candles (`test_falls_back_to_yfinance_when_eodhd_has_no_usable_candles`); if no tool succeeds, the result remains unavailable. |
| Ambiguous entities | The reviewed HSBC name yields both Hong Kong ordinary-share and US ADR candidates; explicit exchange/ticker resolves only that listing (`test_entity_resolution.py`). Unknown names do not guess. |
| Timeout | Blocked market source, index read, sector scan, and connectivity probe paths return a bounded unavailable/timeout response rather than waiting for the upstream call indefinitely (`test_performance.py`, `test_source_connectivity.py`). |
| Duplicate requests | Since this review, identical in-flight `(security, start date, end date, limit)` reads share one source request; later completed requests are **not** cached, so they read fresh data. `test_identical_concurrent_reads_share_one_in_flight_source_call` verifies two callers receive a result from one source call. |
| Unsafe write actions | Every Agent-callable tool declares a `ToolSideEffect`; the registry fails closed unless it is `READ_ONLY`, and the negative test rejects an injected mutating order tool before execution (`test_tools.py`). Codex CLI also runs in its read-only sandbox (`test_codex_cli.py`). |

## Measured local fixture baseline

Command: `python scripts/measure_fast_path.py --iterations 50` with
`PYTHONPATH=src`, run on 2026-08-02. The tool uses only local deterministic
fixtures; network and model-provider time are intentionally excluded.

| Metric | Observed result |
| --- | --- |
| Fast-path p50 | 110.665 ms |
| Fast-path p95 | 1464.197 ms |
| Fast-path min / max | 22.836 ms / 1915.957 ms |
| Identical in-flight pair | 2 logical requests, 1 source call, 1 call avoided (50.0% reduction) |

The high p95 is an observed development-host baseline, not a responsiveness
claim. Keep tracking it after changes and measure real source/model paths
separately before defining a user-facing latency objective.

## RAG and research boundaries

The LCEL local RAG corpus currently contains **21 application-owned documents**:
two fixed research/request-boundary documents plus generated scenario and
source-capability documents. It is rebuilt from reviewed source code at process
startup; it does not ingest external web pages, raw market data, secrets, or
private user documents. Default retrieval returns at most four documents,
using deterministic lexical overlap (ASCII terms and Chinese 1/2/3-character
grams), then stable corpus order as a fallback. Update it only through reviewed
code and rerun `test_langchain_retrieval.py` after a policy or catalog change.

The retrieved material describes research scope, tool capabilities, and data
limits; it cannot establish a market fact. Reports preserve source/time scope,
degrade or refuse unsupported conclusions, never execute trades, and state that
output is not investment advice. Tencent ima, if configured, remains a separate
read-only knowledge search and still requires primary-source verification for
material conclusions.

## Outstanding deployment work

Do not expose the current development service publicly. Before personal
mini-program deployment, supply the personal-user allowlist ID, configure the
WeChat AppID/AppSecret only in a secure server-side store, and register an HTTPS
domain. PostgreSQL, Redis, and a Secret Manager remain future requirements for
durable or multi-instance deployment. Separating static Web hosting from the
API removes release coupling, but does not make the in-memory backend suitable
for multi-instance production use.
