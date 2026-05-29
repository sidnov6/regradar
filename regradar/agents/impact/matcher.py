"""Deterministic control matcher (Part 3, agent 5 — the deterministic half).

"a deterministic matcher proposes candidate controls, the LLM confirms/explains."
This module is the deterministic proposer: it infers which regulatory *themes* an
obligation touches (by keyword signatures over its action + anchor), then proposes
the controls in the synthetic bank that cover those themes. No covering control ->
the obligation is a gap.

Keeping this in pure, unit-tested Python (not the LLM) is the determinism boundary
(Part 11.1): mapping is reproducible and gradeable; the LLM only adds rationale and
confidence on top. A pgvector semantic matcher can augment this later (Part 7).
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from regradar.agents.state import Obligation
from regradar.knowledge.profile.schema import BankProfile, Control

# Theme signatures — keyword sets that identify the regulatory theme of an
# obligation, aligned to the control library's `covers_themes` tags and to real
# DORA vocabulary. Some themes are intentionally NOT covered by any control
# (incident-reporting, resilience-testing, threat-led-penetration-testing,
# information-sharing) — these are the DORA-specific obligations a mid-tier bank
# typically has not yet built, and they surface as genuine gaps.
THEME_SIGNATURES: dict[str, tuple[str, ...]] = {
    "ict-governance": (
        "governance", "management body", "internal governance", "control framework",
        "roles and responsibilities", "responsible for the implementation",
    ),
    "ict-risk-framework": (
        "ict risk management framework", "strategies, policies, procedures",
        "ict protocols and tools", "information assets", "ict assets",
        "sound, comprehensive", "well-documented",
    ),
    "ict-asset-management": (
        "identify, classify", "ict-supported business functions", "interdependencies",
        "configuration", "inventory", "sources of ict risk",
    ),
    "access-control": (
        "access management", "access rights", "authentication", "authorisation",
        "least privilege", "privileged access", "physical access",
    ),
    "data-protection": (
        "encryption", "cryptographic", "confidentiality", "in transit", "at rest",
        "data and system integrity",
    ),
    "ict-detection": (
        "anomalous activities", "detection mechanisms", "monitoring", "early warning",
        "detect anomalous", "logging",
    ),
    "ict-response-recovery": (
        "response and recovery", "recovery plans", "crisis communication", "restore",
        "respond to",
    ),
    "backup-restoration": (
        "backup", "restoration", "redundancy", "recovery point", "recovery time",
    ),
    "business-continuity": (
        "business continuity", "continuity of", "continuity policy", "contingency",
    ),
    "incident-management": (
        "incident management process", "detect, manage", "record all ict-related incidents",
        "root cause", "handling and follow-up", "manage and notify",
    ),
    "incident-classification": (
        "classify ict-related incidents", "classification", "materiality thresholds",
        "classify",
    ),
    "incident-reporting": (
        "report major", "competent authority", "initial notification",
        "intermediate report", "final report", "submit", "notify the relevant",
    ),
    "resilience-testing": (
        "testing programme", "operational resilience testing", "weaknesses, deficiencies",
        "corrective measures", "preparedness for handling", "vulnerability assessments",
    ),
    "threat-led-penetration-testing": (
        "threat-led penetration testing", "tlpt", "advanced testing", "penetration testing",
    ),
    "third-party-risk": (
        "ict third-party risk", "third-party service providers", "ict third-party",
        "subcontracting", "ict services provided",
    ),
    "third-party-register": (
        "register of information", "contractual arrangements on the use of ict",
    ),
    "third-party-contractual": (
        "contractual provisions", "key contractual", "termination rights",
        "service level agreements", "exit strategies",
    ),
    "information-sharing": (
        "information-sharing arrangements", "cyber threat information and intelligence",
        "share, amongst themselves", "intelligence",
    ),
    "vulnerability-management": ("vulnerabilities", "patches", "patch management"),
    "change-management": ("changes to ict", "change management"),
    "ict-audit": ("internal audit", "audit plans", "ict audits"),
    "training-awareness": ("awareness", "training"),
    "network-security": ("network security", "segmentation", "network management"),
    "ict-acquisition": ("acquisition", "maintenance of ict systems", "ict projects"),
}

# Default owning function per theme — used to populate ImpactLink.function even for
# gaps (where there is no control to read the owner from).
THEME_DEFAULT_FUNCTION: dict[str, str] = {
    "ict-governance": "FN-ICT", "ict-risk-framework": "FN-ICT",
    "ict-asset-management": "FN-ICT", "access-control": "FN-SEC",
    "data-protection": "FN-SEC", "ict-detection": "FN-SEC",
    "ict-response-recovery": "FN-BCM", "backup-restoration": "FN-ICT",
    "business-continuity": "FN-BCM", "incident-management": "FN-SEC",
    "incident-classification": "FN-SEC", "incident-reporting": "FN-RISK",
    "resilience-testing": "FN-ICT", "threat-led-penetration-testing": "FN-SEC",
    "third-party-risk": "FN-PROC", "third-party-register": "FN-PROC",
    "third-party-contractual": "FN-PROC", "information-sharing": "FN-SEC",
    "vulnerability-management": "FN-SEC", "change-management": "FN-ICT",
    "ict-audit": "FN-RISK", "training-awareness": "FN-SEC",
    "network-security": "FN-SEC", "ict-acquisition": "FN-ICT",
}


@dataclass
class ControlCandidate:
    control: Control
    theme: str
    score: float  # 0..1 confidence the control covers this obligation


def infer_themes(obligation: Obligation) -> list[tuple[str, float]]:
    """Score each theme by keyword presence in the obligation's action + anchor.
    Returns (theme, score) sorted descending, only for themes that hit."""
    text = f"{obligation.action} {obligation.citation.anchor_quote}".lower()
    scored: list[tuple[str, float]] = []
    for theme, kws in THEME_SIGNATURES.items():
        hits = sum(1 for kw in kws if kw in text)
        if hits:
            scored.append((theme, min(1.0, 0.4 + 0.2 * hits)))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def propose_controls(
    obligation: Obligation, profile: BankProfile, *, min_score: float = 0.4
) -> list[ControlCandidate]:
    """Propose candidate controls for an obligation, best first. Empty => gap."""
    themes = infer_themes(obligation)
    candidates: list[ControlCandidate] = []
    seen: set[str] = set()
    obl_text = f"{obligation.action} {obligation.citation.anchor_quote}"
    # Coverage is decided by the obligation's DOMINANT theme(s). If the top-scored
    # theme has no covering control, this is a gap — do not fall through to an
    # incidental secondary theme that happens to be covered (e.g. an Art 24 testing
    # obligation that merely *references* the ICT risk management framework).
    top_score = themes[0][1] if themes else 0.0
    themes = [(t, s) for t, s in themes if s >= top_score]
    for theme, theme_score in themes:
        for ctl in profile.controls_for_theme(theme):
            if ctl.id in seen:
                continue
            # Blend theme confidence with text similarity to the control description.
            text_sim = fuzz.token_set_ratio(obl_text, f"{ctl.name} {ctl.description}") / 100.0
            score = round(0.6 * theme_score + 0.4 * text_sim, 3)
            if score >= min_score:
                candidates.append(ControlCandidate(control=ctl, theme=theme, score=score))
                seen.add(ctl.id)
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def best_theme(obligation: Obligation) -> str | None:
    themes = infer_themes(obligation)
    return themes[0][0] if themes else None
