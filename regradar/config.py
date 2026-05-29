"""Central config. Every threshold lives here, not hardcoded in logic (Part 11.11).

Values can be overridden via environment variables so a deployment never needs
a code change to retune. Secrets are read from the environment only (never stored
here).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env if present; no-op in prod where env is injected

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PKG_ROOT = Path(__file__).resolve().parent
DATA_ROOT = PKG_ROOT / "data"
BRONZE_STORE = DATA_ROOT / "bronze" / "store"
SILVER_STORE = DATA_ROOT / "silver" / "store"
GOLD_STORE = DATA_ROOT / "gold" / "store"
GROUNDTRUTH_DIR = DATA_ROOT / "groundtruth"
FIXTURES_DIR = DATA_ROOT / "sources" / "fixtures"


def _f(env: str, default: float) -> float:
    raw = os.getenv(env)
    return float(raw) if raw not in (None, "") else default


def _i(env: str, default: int) -> int:
    raw = os.getenv(env)
    return int(raw) if raw not in (None, "") else default


# ---------------------------------------------------------------------------
# Guardrail / verifier thresholds (Part 11.3)
# ---------------------------------------------------------------------------
# Fuzzy-match score required for an anchor quote to count as "present" in the
# cited article. The blueprint uses 0.92.
CITATION_FUZZY_THRESHOLD: float = _f("REGRADAR_CITATION_FUZZY_THRESHOLD", 0.92)

# Below this confidence an obligation/mapping is routed to a human gate (Part 3.3).
CONFIDENCE_HUMAN_GATE: float = _f("REGRADAR_CONFIDENCE_HUMAN_GATE", 0.70)

# ---------------------------------------------------------------------------
# Structured-output repair (Part 11.2)
# ---------------------------------------------------------------------------
SCHEMA_MAX_REPAIR: int = _i("REGRADAR_SCHEMA_MAX_REPAIR", 2)

# ---------------------------------------------------------------------------
# Source-monitor / CELLAR (Part 11.5 — stay inside free tiers deliberately)
# ---------------------------------------------------------------------------
CELLAR_REST_BASE = os.getenv("CELLAR_REST_BASE", "https://publications.europa.eu/resource/cellar")
CELLAR_CELEX_BASE = os.getenv("CELLAR_CELEX_BASE", "http://publications.europa.eu/resource/celex")
CELLAR_SPARQL_ENDPOINT = os.getenv("CELLAR_SPARQL_ENDPOINT", "http://publications.europa.eu/webapi/rdf/sparql")
# EUR-Lex legal-content HTML — the reliable path to real, structured article text.
EURLEX_HTML_URL = os.getenv(
    "EURLEX_HTML_URL",
    "https://eur-lex.europa.eu/legal-content/{lang}/TXT/HTML/?uri=CELEX:{celex}",
)
EURLEX_ATOM_FEED = os.getenv("EURLEX_ATOM_FEED", "https://eur-lex.europa.eu/EN/display-feed.rss")
HTTP_TIMEOUT_S: float = _f("REGRADAR_HTTP_TIMEOUT_S", 30.0)
HTTP_MAX_RETRIES: int = _i("REGRADAR_HTTP_MAX_RETRIES", 4)
HTTP_BACKOFF_BASE_S: float = _f("REGRADAR_HTTP_BACKOFF_BASE_S", 1.0)

# Languages we ingest. DE/EN is the differentiator (Part 8).
LANGUAGES: tuple[str, ...] = ("en", "de")

# In-scope subject filter for the relevance classifier (Part 3, agent 1).
IN_SCOPE_KEYWORDS: tuple[str, ...] = (
    "ICT", "operational resilience", "DORA", "MiCAR", "crypto-asset",
    "anti-money laundering", "AML", "prudential", "CRR", "CRD", "capital",
    "banking", "credit institution", "payment", "AI Act",
)

# ---------------------------------------------------------------------------
# Prioritization (Part 3, agent 6) — priority = f(deadline, effort, risk),
# weights in config not hardcoded. Computed in Python; LLM only supplies inputs.
# ---------------------------------------------------------------------------
PRIORITY_WEIGHT_DEADLINE: float = _f("REGRADAR_W_DEADLINE", 0.5)
PRIORITY_WEIGHT_EFFORT: float = _f("REGRADAR_W_EFFORT", 0.2)
PRIORITY_WEIGHT_RISK: float = _f("REGRADAR_W_RISK", 0.3)
# Deadline urgency decays to ~0 over this horizon; <= 0 days (overdue) = max urgency.
PRIORITY_DEADLINE_HORIZON_DAYS: int = _i("REGRADAR_DEADLINE_HORIZON_DAYS", 540)

# ---------------------------------------------------------------------------
# LLM router (Part 11.4) — ordered failover chain, ending at a local/mock floor.
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
