"""Orchestrator tests using a fake router (no network/tokens).

Verify the guardrail routing: verified obligations are accepted, fabricated ones
are rejected + flagged + open a human gate, duplicates collapse, and every step
writes an audit entry."""
import json

from regradar.agents.obligation.run import extract_document
from regradar.agents.state import FlagKind
from regradar.models.router import LLMResult, Router

# Real anchors (verify against the fixture) and a fabricated one (must be rejected).
REAL_A5 = "The management body of the financial entity shall define, approve, oversee"
REAL_A17 = "Financial entities shall define, establish and implement an ICT-related incident management process"
FAKE = "Financial entities shall repaint all servers blue every Tuesday"


def _ob(actor, action, anchor, para, typ="governance", force="shall"):
    return {"actor": actor, "modal_force": force, "action": action,
            "conditions": "", "obligation_type": typ, "paragraph_ref": para,
            "anchor_quote": anchor}


class FakeRouter(Router):
    """Returns canned extraction JSON based on which article is in the prompt."""

    def __init__(self, by_article):
        super().__init__(chain=())
        self.by_article = by_article

    def complete(self, prompt, *, temperature=None):
        # Match the unique prompt header "Article N — Title", not bare "Article N"
        # (article bodies cross-reference other articles, which would leak).
        for label, obls in self.by_article.items():
            if f"{label} — " in prompt:
                return LLMResult(json.dumps({"obligations": obls}), "fake", "fake-model", 0.0)
        return LLMResult('{"obligations": []}', "fake", "fake-model", 0.0)


def test_verified_accepted_fabricated_rejected(parsed_dora):
    router = FakeRouter({
        "Article 5": [_ob("The management body", "define and oversee ICT framework", REAL_A5, "2")],
        "Article 17": [_ob("Financial entities", "implement incident process", REAL_A17, "1", "ict-control")],
        "Article 6": [_ob("Financial entities", "do something fictional", FAKE, "1")],
    })
    out = extract_document(parsed_dora, router=router)

    accepted_ids = {o.citation.anchor_quote[:20] for o in out.obligations}
    assert REAL_A5[:20] in accepted_ids
    assert REAL_A17[:20] in accepted_ids
    assert len(out.obligations) == 2           # the two verified ones
    assert len(out.rejected) == 1              # the fabricated one
    assert out.citation_integrity == 2 / 3

    assert any(f.kind == FlagKind.VERIFIER_REJECTED for f in out.flags)
    assert out.needs_human_gate                # a rejection must open the gate


def test_dedup_collapses_identical_obligations(parsed_dora):
    dup = _ob("The management body", "define and oversee", REAL_A5, "2")
    router = FakeRouter({"Article 5": [dup, dict(dup)]})
    out = extract_document(parsed_dora, router=router)
    assert len(out.obligations) == 1           # duplicate collapsed


def test_audit_trail_and_corpus_version(parsed_dora):
    router = FakeRouter({"Article 5": [_ob("The management body", "x", REAL_A5, "2")]})
    out = extract_document(parsed_dora, router=router)
    nodes = {a.node for a in out.audit_trail}
    assert "obligation_extraction" in nodes
    assert "citation_verifier" in nodes
    assert out.corpus_version.startswith("cv:")
    # the verifier audit entry carries a verdict
    v = [a for a in out.audit_trail if a.node == "citation_verifier"]
    assert v and v[0].verifier_verdict is not None


def test_clean_document_advances_to_mapping(parsed_dora):
    from regradar.agents.obligation.run import fold_into_state
    router = FakeRouter({"Article 5": [_ob("The management body", "x", REAL_A5, "2")]})
    out = extract_document(parsed_dora, router=router)
    state = fold_into_state({}, out)
    assert state["status"] == "mapping"        # no flags -> no human gate
    assert state["human_gate"] is None if "human_gate" in state else True
