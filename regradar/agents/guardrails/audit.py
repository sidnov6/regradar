"""Audit + flag helpers — the append-only provenance substrate (Part 10).

Every decision logs model, prompt, evidence, confidence, verifier verdict, and the
corpus version. This is both the robustness substrate and the thing you sell:
"why did it say that?" is answerable for any obligation, months later. The same
records back the Audit/Trace screen (Part 9, screen 5).
"""
from __future__ import annotations

import hashlib

from regradar.agents.state import AuditEntry, Flag, FlagKind, VerifierVerdict


def corpus_version_for(content_hash: str) -> str:
    """A reproducible corpus-snapshot id. For a single pinned doc this is its
    content hash; for a multi-doc KB snapshot, hash the sorted member hashes."""
    return f"cv:{content_hash[:16]}"


def snapshot_version(content_hashes: list[str]) -> str:
    joined = "|".join(sorted(content_hashes))
    return f"cv:{hashlib.sha256(joined.encode()).hexdigest()[:16]}"


def audit(
    node: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    prompt: str | None = None,
    evidence_refs: list[str] | None = None,
    confidence: float | None = None,
    verdict: VerifierVerdict | None = None,
    corpus_version: str | None = None,
    tokens: int | None = None,
    latency_ms: float | None = None,
) -> AuditEntry:
    return AuditEntry(
        node=node,
        model=model,
        provider=provider,
        prompt_hash=hashlib.sha256(prompt.encode()).hexdigest() if prompt else None,
        evidence_refs=evidence_refs or [],
        confidence=confidence,
        verifier_verdict=verdict,
        corpus_version=corpus_version,
        tokens=tokens,
        latency_ms=latency_ms,
    )


def flag(kind: FlagKind, message: str, *, obligation_id: str | None = None,
         severity: str = "warning") -> Flag:
    return Flag(kind=kind, message=message, obligation_id=obligation_id, severity=severity)  # type: ignore[arg-type]
