"""Medallion ingestion pipeline glue (Part 6): source -> Bronze -> Silver.

Deterministic and idempotent. Live CELLAR fetching plugs in here later; for the
keystone we ingest the pinned DORA fixture so the whole flow is exercised offline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from regradar import config
from regradar.agents.parser.formex import parse_formex
from regradar.agents.state import Language, Manifestation, ParsedRegDoc, RawRegDoc
from regradar.data.bronze.store import BronzeStore


def ingest_bytes_to_bronze(
    raw: bytes,
    *,
    celex: str,
    manifestation: Manifestation,
    language: Language,
    source_uri: str,
    store: Optional[BronzeStore] = None,
) -> RawRegDoc:
    """Pin raw bytes into Bronze (idempotent by content hash)."""
    store = store or BronzeStore()
    return store.put(
        celex=celex,
        manifestation=manifestation,
        language=language,
        source_uri=source_uri,
        raw=raw,
    )


def bronze_to_silver(rec: RawRegDoc, store: Optional[BronzeStore] = None) -> ParsedRegDoc:
    """Parse a pinned Bronze record into a Silver article tree. The Silver doc
    carries the Bronze content_hash so a citation is pinned to an exact version."""
    store = store or BronzeStore()
    raw = store.get_bytes(rec)
    if rec.manifestation is Manifestation.FORMEX:
        return parse_formex(
            raw, celex=rec.celex, language=rec.language, content_hash=rec.content_hash
        )
    if rec.manifestation is Manifestation.XHTML:
        from regradar.agents.parser.xhtml import parse_eurlex_html

        return parse_eurlex_html(
            raw, celex=rec.celex, language=rec.language, content_hash=rec.content_hash
        )
    raise NotImplementedError(f"parser for {rec.manifestation} not wired (PDF+OCR is a later fallback)")


def ingest_eurlex(
    celex: str,
    *,
    language: Language = "en",
    store: Optional[BronzeStore] = None,
) -> tuple[RawRegDoc, ParsedRegDoc]:
    """LIVE: fetch the real document from EUR-Lex, pin it into Bronze (immutable,
    hash-pinned), and parse to a Silver article tree. This is the production
    ingestion path — same downstream pipeline as the offline fixture."""
    from regradar.data.sources.cellar import CellarClient

    raw = CellarClient().fetch_eurlex_html(celex, language)
    rec = ingest_bytes_to_bronze(
        raw, celex=celex, manifestation=Manifestation.XHTML, language=language,
        source_uri=config.EURLEX_HTML_URL.format(lang=language.upper(), celex=celex),
        store=store,
    )
    return rec, bronze_to_silver(rec, store=store)


def process_document(rec: RawRegDoc, *, store: Optional[BronzeStore] = None,
                     router=None, explain: bool = False,
                     max_articles: Optional[int] = None) -> dict:
    """Run a document from a pinned Bronze record through Silver + extraction +
    guardrails, returning a populated RegRadarState dict (Part 3.1). This is the
    agentic run up to (not including) impact mapping — the Phase 2 boundary."""
    import uuid

    from regradar.agents.obligation.run import extract_document, fold_into_state

    parsed = bronze_to_silver(rec, store=store)
    state: dict = {
        "run_id": str(uuid.uuid4()),
        "raw_doc": rec,
        "parsed_doc": parsed,
        "is_amendment": False,
        "obligations": [],
        "impact_links": [],
        "prioritized": [],
        "audit_trail": [],
        "flags": [],
        "status": "extracting",
    }
    outcome = extract_document(parsed, router=router, max_articles=max_articles)
    state = fold_into_state(state, outcome)

    # Phase 3: impact mapping + prioritization onto the synthetic bank.
    # Runs on the accepted (verified) obligations only.
    from regradar.agents.impact.map import map_obligations
    from regradar.agents.prioritize.score import prioritize
    from regradar.knowledge.profile.schema import load_profile

    profile = load_profile()
    links = map_obligations(state["obligations"], profile, router=router, explain=explain)
    state["impact_links"] = links
    state["prioritized"] = prioritize(state["obligations"], links)
    if state["status"] != "awaiting_human":
        state["status"] = "prioritizing"
    return state


def ingest_fixture(
    fixture_path: Optional[Path] = None,
    *,
    celex: str = "32022R2554",
    language: Language = "en",
    store: Optional[BronzeStore] = None,
) -> tuple[RawRegDoc, ParsedRegDoc]:
    """Convenience: ingest the bundled DORA Formex fixture through Bronze -> Silver."""
    fixture_path = fixture_path or (
        config.FIXTURES_DIR / f"dora_{celex}_{language}.formex.xml"
    )
    raw = fixture_path.read_bytes()
    rec = ingest_bytes_to_bronze(
        raw,
        celex=celex,
        manifestation=Manifestation.FORMEX,
        language=language,
        source_uri=f"file://{fixture_path}",
        store=store,
    )
    parsed = bronze_to_silver(rec, store=store)
    return rec, parsed
