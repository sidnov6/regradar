"""RegRadar API gateway + console host (Part 2, Application/API layer).

A single FastAPI service: REST endpoints over the processed pipeline state, an SSE
stream that replays the agent pipeline for the live "watch it work" feel, and the
static console served at /. One deployable unit (Render/Fly/HF Spaces).

    uvicorn regradar.server:app --reload
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import os

from regradar.agents.memo.draft import draft_memo
from regradar.agents.memo.export import approve, reject, to_html, to_markdown
from regradar.data.pipeline import ingest_eurlex, ingest_fixture, process_document
from regradar.models.router import router as llm_router

CONSOLE_DIR = Path(__file__).parent / "console"

# Source selection (real data vs bundled fixture).
#   REGRADAR_SOURCE = fixture (default) | eurlex   — live fetch from EUR-Lex
#   REGRADAR_CELEX, REGRADAR_LANG                   — which document
#   REGRADAR_MAX_ARTICLES                           — cap live extraction (quota/time)
SOURCE = os.getenv("REGRADAR_SOURCE", "fixture").lower()
CELEX = os.getenv("REGRADAR_CELEX", "32022R2554")
LANG = os.getenv("REGRADAR_LANG", "en")
_MAX_ART_ENV = os.getenv("REGRADAR_MAX_ARTICLES")
# 0 (or unset for fixture) = all articles; default cap of 8 only for live source.
if _MAX_ART_ENV is not None:
    _v = int(_MAX_ART_ENV)
    MAX_ARTICLES = None if _v == 0 else _v
else:
    MAX_ARTICLES = 8 if SOURCE == "eurlex" else None


class Service:
    """Processes the document once and caches the resulting state + memo."""

    def __init__(self):
        self._state: Optional[dict] = None
        self._memo = None

    def state(self) -> dict:
        if self._state is None:
            if SOURCE == "eurlex":
                rec, _ = ingest_eurlex(CELEX, language=LANG)  # LIVE real data
            else:
                rec, _ = ingest_fixture(celex=CELEX, language=LANG)
            self._state = process_document(rec, max_articles=MAX_ARTICLES)
        return self._state

    def memo(self, language: str = "en", regenerate: bool = False):
        if self._memo is None or regenerate or self._memo.language != language:
            # Pass the router so DE memos get LLM-translated prose (anchors stay
            # original-language). EN is fully deterministic — no LLM call.
            self._memo = draft_memo(self.state(), language=language, router=llm_router)
        return self._memo


svc = Service()
app = FastAPI(title="RegRadar · KOMPASS", version="0.1.0")


# --------------------------------------------------------------------------- API
@app.get("/api/health")
def health():
    return {"ok": True, "providers": llm_router.active_providers}


@app.get("/api/state")
def get_state():
    s = svc.state()
    parsed = s["parsed_doc"]
    obls = s["obligations"]
    links = s["impact_links"]
    prio = s["prioritized"]
    gaps = [l for l in links if l.status == "gap"]
    covered = [l for l in links if l.status == "covered"]
    unmapped = [l for l in links if l.status == "unmapped"]
    in_scope = len(covered) + len(gaps)
    nearest = min((p.deadline_days for p in prio if p.deadline_days is not None), default=None)
    return {
        "celex": parsed.celex,
        "title": parsed.title,
        "language": parsed.language,
        "providers": llm_router.active_providers,
        "status": s["status"],
        "corpus_version": s.get("corpus_version"),
        "counters": {
            "obligations": len(obls),
            "gaps": len(gaps),
            "covered": len(covered),
            "unmapped": len(unmapped),
            "in_scope": in_scope,
            "coverage_pct": round(100 * len(covered) / in_scope) if in_scope else 0,
            "deadlines_lt_90d": sum(1 for p in prio if p.deadline_days is not None and p.deadline_days < 90),
            "nearest_deadline_days": nearest,
            "flags": len(s["flags"]),
            "audit_entries": len(s["audit_trail"]),
            "needs_human_gate": s.get("human_gate") is not None,
        },
        "obligations": [o.model_dump(mode="json") for o in obls],
        "impact_links": [l.model_dump(mode="json") for l in links],
        "prioritized": [p.model_dump(mode="json") for p in prio],
        "flags": [f.model_dump(mode="json") for f in s["flags"]],
    }


@app.get("/api/document")
def get_document():
    parsed = svc.state()["parsed_doc"]
    return {
        "celex": parsed.celex, "title": parsed.title, "language": parsed.language,
        "articles": [
            {
                "number": a.number, "label": a.label, "title": a.title, "chapter": a.chapter,
                "paragraphs": [{"ref": p.ref, "text": p.text, "points": p.points} for p in a.paragraphs],
            }
            for a in parsed.articles
        ],
    }


@app.get("/api/audit")
def get_audit():
    return [a.model_dump(mode="json") for a in svc.state()["audit_trail"]]


class MemoReq(BaseModel):
    language: str = "en"


@app.post("/api/memo")
def gen_memo(req: MemoReq):
    memo = svc.memo(language=req.language, regenerate=True)
    return {"title": memo.title, "language": memo.language, "status": memo.status,
            "markdown": memo.body_markdown, "citations": len(memo.citation_appendix)}


class DecisionReq(BaseModel):
    approver: str = "reviewer"
    notes: str = ""


@app.post("/api/memo/approve")
def memo_approve(req: DecisionReq):
    if svc._memo is None:
        raise HTTPException(400, "no memo drafted yet")
    svc._memo, gate = approve(svc._memo, req.approver, req.notes)
    return {"status": svc._memo.status, "approver": gate.approver}


@app.post("/api/memo/reject")
def memo_reject(req: DecisionReq):
    if svc._memo is None:
        raise HTTPException(400, "no memo drafted yet")
    svc._memo, gate = reject(svc._memo, req.approver, req.notes)
    return {"status": svc._memo.status, "approver": gate.approver}


@app.get("/api/memo/export")
def memo_export(format: str = "html", language: str = "en"):
    memo = svc.memo(language=language)
    if format == "md":
        return PlainTextResponse(to_markdown(memo), media_type="text/markdown",
                                 headers={"Content-Disposition": "attachment; filename=regradar_memo.md"})
    return HTMLResponse(to_html(memo))


@app.get("/api/stream")
async def stream():
    """Replay the agent pipeline as SSE events for the live console feel."""
    s = svc.state()
    obls = s["obligations"]
    links = s["impact_links"]
    gaps = sum(1 for l in links if l.is_gap)

    async def gen():
        steps = [
            ("monitor", "Source-Monitor", f"caught {s['parsed_doc'].celex} off the feed"),
            ("parser", "Parser / Intake", f"segmented {len(s['parsed_doc'].articles)} articles → Silver"),
            ("extraction", "Obligation-Extraction", f"extracting obligations (temp 0)…"),
        ]
        for kind, agent, msg in steps:
            yield _sse({"type": "agent", "kind": kind, "agent": agent, "message": msg})
            await asyncio.sleep(0.45)
        for o in obls:
            yield _sse({"type": "obligation", "id": o.id, "article": o.citation.article_ref,
                        "verified": True, "obligation_type": o.obligation_type.value})
            await asyncio.sleep(0.12)
        yield _sse({"type": "agent", "kind": "mapping", "agent": "Impact-Mapping",
                    "message": f"mapped {len(links)} obligations · {gaps} gaps"})
        await asyncio.sleep(0.4)
        yield _sse({"type": "agent", "kind": "prioritize", "agent": "Prioritization",
                    "message": "ranked by deadline · effort · risk"})
        await asyncio.sleep(0.4)
        yield _sse({"type": "done", "message": "pipeline complete"})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# --------------------------------------------------------------------------- console
if CONSOLE_DIR.exists():
    app.mount("/static", StaticFiles(directory=CONSOLE_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    idx = CONSOLE_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return HTMLResponse("<h1>RegRadar API</h1><p>Console not built.</p>")
