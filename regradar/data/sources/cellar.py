"""CELLAR / EUR-Lex connector — the ingestion backbone (Parts 5 & 6).

Flow: Atom feed (change notification) -> dedup by CELEX+hash -> SPARQL metadata
enrichment -> REST content fetch (Formex preferred, else XHTML, else PDF) -> Bronze.

Network calls are best-effort and wrapped in the backoff client. The pure parsing
functions (`parse_atom`, `classify_in_scope`) are deterministic and unit-testable
offline; live fetching is exercised separately so CI never depends on a remote.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from lxml import etree

from regradar import config
from regradar.agents.state import (
    Language,
    Manifestation,
    SourceEvent,
    SourceSystem,
)
from regradar.data.sources import http_client

# CELLAR content-negotiation Accept headers per manifestation.
_ACCEPT = {
    Manifestation.FORMEX: "application/xml;notice=branch",
    Manifestation.XHTML: "application/xhtml+xml",
    Manifestation.PDF: "application/pdf",
}

_CELEX_RE = re.compile(r"CELEX[:%]?3?\d?[A-Z]?\d{4}[A-Z]\d{4}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pure, deterministic helpers (offline-testable)
# ---------------------------------------------------------------------------
def extract_celex(text: str) -> Optional[str]:
    """Pull a CELEX number out of a URI or title."""
    m = re.search(r"3\d?[A-Z]?\d{4}[A-Z]\d{4}", text or "")
    if m:
        return m.group(0)
    m = _CELEX_RE.search(text or "")
    return m.group(0).split(":")[-1] if m else None


def classify_in_scope(title: str, summary: str = "") -> tuple[bool, str]:
    """Deterministic relevance prefilter (Part 3, agent 1). The LLM classifier can
    refine borderline cases later; this keyword gate is the cheap first pass."""
    hay = f"{title}\n{summary}".lower()
    for kw in config.IN_SCOPE_KEYWORDS:
        if kw.lower() in hay:
            return True, f"matched in-scope keyword: {kw}"
    return False, "no in-scope keyword matched"


def parse_atom(xml_bytes: bytes) -> list[SourceEvent]:
    """Parse an Atom/RSS change feed into SourceEvents. Handles both Atom <entry>
    and RSS <item> shapes."""
    root = etree.fromstring(xml_bytes)
    events: list[SourceEvent] = []

    # Strip namespaces for tolerant tag matching across feed dialects.
    def local(tag: str) -> str:
        return etree.QName(tag).localname if isinstance(tag, str) and "}" in tag else tag

    for el in root.iter():
        if local(el.tag) not in ("entry", "item"):
            continue
        title = link = summary = pub = ""
        for child in el:
            name = local(child.tag)
            if name == "title":
                title = (child.text or "").strip()
            elif name == "summary" or name == "description":
                summary = (child.text or "").strip()
            elif name == "link":
                link = (child.get("href") or child.text or "").strip()
            elif name in ("updated", "published", "pubDate", "date"):
                pub = (child.text or "").strip()
        if not link:
            continue
        celex = extract_celex(link) or extract_celex(title)
        in_scope, reason = classify_in_scope(title, summary)
        events.append(
            SourceEvent(
                celex=celex,
                uri=link,
                source=SourceSystem.EUR_LEX,
                title=title,
                published=_parse_date(pub),
                in_scope=in_scope,
                scope_reason=reason,
            )
        )
    return events


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Live client (best-effort, backoff-wrapped)
# ---------------------------------------------------------------------------
class CellarClient:
    def fetch_feed(self, feed_url: Optional[str] = None) -> list[SourceEvent]:
        url = feed_url or config.EURLEX_ATOM_FEED
        resp = http_client.get(url, accept="application/atom+xml, application/rss+xml, application/xml")
        return parse_atom(resp.content)

    def resolve_metadata(self, celex: str) -> dict:
        """SPARQL metadata enrichment: title, type, dates. Returns {} on failure
        (graceful degradation — Part 11.10)."""
        query = f"""
        PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
        SELECT ?title ?date WHERE {{
          ?work cdm:resource_legal_id_celex "{celex}"^^<http://www.w3.org/2001/XMLSchema#string> .
          OPTIONAL {{ ?work cdm:work_date_document ?date . }}
          OPTIONAL {{ ?expr cdm:expression_belongs_to_work ?work ;
                           cdm:expression_title ?title . }}
        }} LIMIT 1
        """
        try:
            resp = http_client.get(
                config.CELLAR_SPARQL_ENDPOINT,
                params={"query": query, "format": "application/sparql-results+json"},
                accept="application/sparql-results+json",
            )
            bindings = resp.json().get("results", {}).get("bindings", [])
            if not bindings:
                return {}
            b = bindings[0]
            return {
                "title": b.get("title", {}).get("value", ""),
                "date": b.get("date", {}).get("value", ""),
            }
        except Exception:
            return {}

    def fetch_content(
        self,
        celex: str,
        manifestation: Manifestation,
        language: Language,
    ) -> bytes:
        """Fetch a content manifestation by CELEX via CELLAR REST content negotiation."""
        url = f"{config.CELLAR_REST_BASE}/celex/{celex}"
        resp = http_client.get(
            url,
            accept=_ACCEPT[manifestation],
            headers={"Accept-Language": language},
        )
        return resp.content

    def fetch_eurlex_html(self, celex: str, language: Language) -> bytes:
        """Fetch the real, structured article text from the EUR-Lex legal-content
        HTML endpoint (the reliable XHTML manifestation). Returns raw bytes to pin
        into Bronze immutably."""
        url = config.EURLEX_HTML_URL.format(lang=language.upper(), celex=celex)
        resp = http_client.get(url, accept="text/html,application/xhtml+xml")
        return resp.content
