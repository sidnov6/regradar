# RegRadar · KOMPASS

Agentic EU Regulatory-Impact Engine — watches the EU regulatory firehose, extracts
the concrete obligations from each text, maps them to a bank's systems, flags
deadlines, and drafts the gap-assessment memo. Every claim traceable to the exact
article, in German and English. Built on a robustness-first, $0 free-tier stack.

> Status: **Phases 0–4 complete + live console** — foundations, ingestion, the
> hand-labeled DORA oracle, the synthetic bank profile, the programmatic citation
> verifier, the extraction+guardrail orchestrator, an exact response cache, impact
> mapping (gaps surfaced), deadline/effort/risk prioritization, **gap-assessment memo
> generation (EN + German) with a human approval gate and DOCX/HTML export, and a
> dark "command center" web console (FastAPI + SSE)**. The full agentic run goes raw
> document → verified obligations → impact map → ranked actions → drafted memo → human
> gate, watchable live in the browser.

## The console

```bash
./scripts/serve.sh            # http://localhost:8000  (or: uvicorn regradar.server:app --reload)
```

Five screens, dark regulatory-command-center design: **Radar Feed** (counters + live
agent stream over SSE), **Obligation Workbench** (source text with verified obligation
anchors highlighted in place), **Impact Map** (obligations → controls; gaps glow red),
**Memo Studio** (generate EN/DE memo, approve/reject, export), **Audit & Trace**
(append-only log with per-claim verifier verdicts). One FastAPI service serves the API
*and* the console — a single deployable unit.

## What runs today

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[llm,dev]"          # core + LiteLLM/Groq + pytest
cp .env.example .env                 # add GROQ_API_KEY (optional; mock floor works without)

python scripts/keystone_demo.py            # full keystone, live extraction if a key is set
python scripts/keystone_demo.py --no-live  # deterministic only, no LLM calls
python scripts/grade_live_extraction.py    # Phase 2: live extraction across DORA, graded vs oracle
python scripts/grade_impact_mapping.py     # Phase 3: mapping + prioritization, graded vs oracle
./scripts/serve.sh                         # Phase 4: launch the console at http://localhost:8000
pytest -q                                  # 57 tests, no network/keys required
python -m regradar.eval.run                # eval-as-CI-gate (Part 11.8)
```

### Real data (live EU source)

```bash
python scripts/ingest_real.py --celex 32022R2554 --lang en --articles 8   # fetch real DORA from EUR-Lex
REGRADAR_SOURCE=eurlex REGRADAR_MAX_ARTICLES=8 ./scripts/serve.sh          # console on live data
```

`ingest_eurlex()` fetches the real, structured act from the EUR-Lex legal-content
endpoint, pins it into Bronze by hash, and parses **all 64 real DORA articles** into
Silver. Verified: 10/11 of the hand-labeled anchors match the live text verbatim, and
live extraction holds **100% citation integrity against the genuine EUR-Lex source**.
Extraction is article-capped by default (free-tier friendly; cached after first run).

### Bundled demo (offline)

The demo: ingests DORA (Reg (EU) 2022/2554) → Bronze (hash-pinned, idempotent) →
Silver (article tree) → grades against the labeled oracle (100% citation integrity,
gap-detection F1 1.0) → if Groq is live, extracts obligations from an article and
**programmatically verifies every citation** against the pinned source.

**Latest live graded extraction** (full DORA subset, Groq→Gemini failover):
precision **0.917** · recall **1.000** · F1 **0.957** · citation integrity **100%**
on accepted obligations. The verifier rejected 2 ungrounded anchors the model
over-extracted from Article 19's list items and opened a human gate — exactly the
intended behaviour (no unverified legal claim reaches the user).

## Architecture map (where the blueprint lives in the code)

| Blueprint | Module |
|---|---|
| Shared state + schemas (Part 3.1) | `regradar/agents/state.py` |
| Citation verifier — the killer feature (Part 11.3) | `regradar/agents/guardrails/verifier.py` |
| LLM gateway + failover + repair-retry (Parts 11.2/11.4) | `regradar/models/router.py` |
| Source-Monitor + CELLAR connector (Part 3 agent 1, Part 5) | `regradar/agents/monitor/`, `regradar/data/sources/` |
| Bronze store — immutable, hash-pinned (Parts 6/11.7) | `regradar/data/bronze/store.py` |
| Formex → Silver parser (Part 3 agent 2) | `regradar/agents/parser/formex.py` |
| EUR-Lex XHTML → Silver parser (real data) | `regradar/agents/parser/xhtml.py` |
| Live EUR-Lex fetch → Bronze | `ingest_eurlex()` in `regradar/data/pipeline.py` |
| Obligation extraction (Part 3 agent 3) | `regradar/agents/obligation/extract.py` |
| Extraction+guardrail orchestrator (Part 3 + 11.2/11.3) | `regradar/agents/obligation/run.py` |
| Impact mapping — matcher + agent (Part 3 agent 5) | `regradar/agents/impact/` |
| Prioritization — deadlines + scorer (Part 3 agent 6) | `regradar/agents/prioritize/` |
| Memo drafting + export + approval (Part 3 agent 7) | `regradar/agents/memo/` |
| API gateway + SSE + console host (Part 2) | `regradar/server.py` |
| Console UI — 5 screens (Part 9) | `regradar/console/index.html` |
| Audit trail + corpus version (Part 10) | `regradar/agents/guardrails/audit.py` |
| Exact response cache (Part 11.6) | `regradar/models/cache.py` |
| Synthetic bank profile (Part 5) | `regradar/knowledge/profile/` |
| DORA ground-truth oracle (Parts 5/14) | `regradar/data/groundtruth/` |
| Eval harness + CI gate (Parts 11.8/14) | `regradar/eval/` |
| Config — all thresholds, no hardcoding (Part 11.11) | `regradar/config.py` |

## Robustness properties already in place

- **Determinism boundary** (11.1): parsing, hashing, citation matching, scoring are pure Python; LLM only extracts.
- **Citation integrity by construction** (11.3): no obligation is trusted until its anchor quote is found in the cited article of the pinned source.
- **No single point of quota failure** (11.4): router fails over Groq → Gemini → OpenRouter → Ollama → deterministic mock floor.
- **Idempotency** (11.7): re-ingesting identical bytes is a no-op; same hash = same pin.
- **Eval-as-gate** (11.8): `regradar/eval/run.py` exits non-zero on regression.
- **Secrets hygiene** (11.11): keys only in gitignored `.env`; thresholds in `config.py`.

## Free-tier note (observed, not hypothetical)

Groq's free tier caps at ~100k tokens/day. Running the full-document live grade a
few times exhausts it. When that happens the router fails over to the deterministic
floor, the floor's output fails schema validation, and the guardrail flags it and
opens a human gate — the system degrades, it does not crash (Parts 11.4 / 11.2 /
3.3). The exact cache (Part 11.6) means already-extracted articles don't re-spend
tokens on the next run. For an unthrottled full grade, add a second provider
(Gemini free tier, or local Ollama) to the chain in `regradar/models/router.py`, or
re-run after the daily quota resets.

## Deploy

One service (API + console) deploys anywhere that runs a container or a Python web
service:

- **Render** — `render.yaml` is included; connect the repo, set `GROQ_API_KEY` and
  `GOOGLE_API_KEY` as secrets, deploy (free plan).
- **Docker / Fly / HF Spaces** — `Dockerfile` builds and runs `uvicorn regradar.server:app`.
  Inject the two keys as runtime env vars (never baked into the image).

Locally: `./scripts/serve.sh`.

## Next phases

Phase 5 — Change-Diff agent for amendments + remaining hardening. German *ingestion*
(a DE manifestation end-to-end; DE memo output already works). Deferred infra:
article-level pgvector KB. See the architecture blueprint, Part 13, for the roadmap.
