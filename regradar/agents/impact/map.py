"""Impact-Mapping agent (Part 3, agent 5) — "what does it touch here".

Maps each obligation onto the synthetic bank: affected function, system, process,
and existing control — or flags a gap (obligation with no covering control). The
deterministic matcher proposes candidates; an optional LLM step confirms/explains
(off by default so grading is reproducible and token-free).

This is what turns "a regulation exists" into "you, specifically, must do X to
system Y."
"""
from __future__ import annotations

from pydantic import BaseModel

from regradar.agents.impact.matcher import (
    THEME_DEFAULT_FUNCTION,
    best_theme,
    infer_themes,
    propose_controls,
)
from regradar.agents.state import ImpactLink, Obligation
from regradar.knowledge.profile.schema import BankProfile
from regradar.models.router import Router, SchemaRepairFailed


class _Confirmation(BaseModel):
    applies: bool
    rationale: str
    confidence: float = 1.0


def _function_name(profile: BankProfile, function_id: str | None) -> str:
    fn = next((f for f in profile.functions if f.id == function_id), None)
    return fn.name if fn else (function_id or "")


def _system_name(profile: BankProfile, system_id: str | None) -> str:
    sys = next((s for s in profile.systems if s.id == system_id), None)
    return sys.name if sys else (system_id or "")


def map_obligation(
    obligation: Obligation,
    profile: BankProfile,
    *,
    router: Router | None = None,
    explain: bool = False,
) -> ImpactLink:
    themes = infer_themes(obligation)

    if not themes:
        # No ICT control theme at all — typically a procedural/definitional/scope
        # provision (e.g. addressed to regulators), not a control to build.
        return ImpactLink(
            obligation_id=obligation.id,
            function="", system="", process="", control_id=None,
            is_gap=False, status="unmapped",
            rationale="No ICT control theme identified — likely procedural/out of scope; manual review.",
            confidence=0.5,
        )

    candidates = propose_controls(obligation, profile)
    if not candidates:
        # Real gap: an identifiable ICT theme with no covering control.
        theme = themes[0][0]
        fn_id = THEME_DEFAULT_FUNCTION.get(theme, "FN-RISK")
        return ImpactLink(
            obligation_id=obligation.id,
            function=_function_name(profile, fn_id),
            system="", process="", control_id=None,
            is_gap=True, status="gap",
            rationale=f"No control covers theme '{theme}'. Gap — control must be built.",
            confidence=0.9,
        )

    top = candidates[0]
    ctl = top.control
    rationale = (
        f"Obligation maps to theme '{top.theme}', covered by {ctl.id} '{ctl.name}'."
    )
    confidence = top.score

    if explain and router is not None:
        try:
            conf = _llm_confirm(obligation, ctl, router)
            rationale = conf.rationale or rationale
            confidence = max(0.0, min(1.0, conf.confidence))
            if not conf.applies and len(candidates) > 1:
                top = candidates[1]
                ctl = top.control
        except SchemaRepairFailed:
            pass  # fall back to the deterministic mapping (graceful degradation)

    return ImpactLink(
        obligation_id=obligation.id,
        function=_function_name(profile, ctl.function_ids[0] if ctl.function_ids else None),
        system=_system_name(profile, ctl.system_ids[0] if ctl.system_ids else None),
        process="",
        control_id=ctl.id,
        is_gap=False,
        rationale=rationale,
        confidence=confidence,
    )


def map_obligations(
    obligations: list[Obligation],
    profile: BankProfile,
    *,
    router: Router | None = None,
    explain: bool = False,
) -> list[ImpactLink]:
    return [map_obligation(o, profile, router=router, explain=explain) for o in obligations]


_CONFIRM_PROMPT = """You are mapping an EU regulatory obligation to a bank's internal control.
Does the control adequately address the obligation? Answer strictly as JSON:
{{"applies": true|false, "rationale": "<one sentence>", "confidence": 0.0-1.0}}

OBLIGATION ({obl_type}): {actor} {force} {action}
CONTROL {ctl_id} — {ctl_name}: {ctl_desc}
"""


def _llm_confirm(obligation: Obligation, control, router: Router) -> _Confirmation:
    prompt = _CONFIRM_PROMPT.format(
        obl_type=obligation.obligation_type.value,
        actor=obligation.actor,
        force=obligation.modal_force.value,
        action=obligation.action,
        ctl_id=control.id,
        ctl_name=control.name,
        ctl_desc=control.description,
    )
    conf, _ = router.call_structured(prompt, _Confirmation, temperature=0.0)
    return conf
