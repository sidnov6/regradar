"""Ground-truth obligation set — the evaluation oracle (Parts 5 & 14).

Hand-labeled obligations for selected DORA articles: known obligations, known
control mappings, known gaps. This is what turns "cool demo" into graded results:
extraction precision/recall/F1, citation integrity, mapping accuracy, and
gap-detection are all measured against this. Build it first; grade every agent
from the moment it exists.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from regradar.agents.state import (
    Citation,
    Language,
    ModalForce,
    Obligation,
    ObligationType,
)


class GroundTruthObligation(BaseModel):
    id: str
    celex: str
    article_ref: str
    paragraph_ref: Optional[str] = None
    language: Language
    anchor_quote: str            # verbatim span; the verifier must find this in the article
    actor: str
    modal_force: ModalForce
    action: str
    obligation_type: ObligationType
    expected_theme: str          # impact-mapping theme tag
    expected_control_id: Optional[str] = None  # None => this obligation is a known GAP

    @property
    def is_gap(self) -> bool:
        return self.expected_control_id is None

    def to_obligation(self) -> Obligation:
        """Materialise as a first-class Obligation (used to seed/verify the oracle)."""
        return Obligation(
            id=self.id,
            actor=self.actor,
            modal_force=self.modal_force,
            action=self.action,
            obligation_type=self.obligation_type,
            language=self.language,
            confidence=1.0,
            citation=Citation(
                celex=self.celex,
                article_ref=self.article_ref,
                paragraph_ref=self.paragraph_ref,
                language=self.language,
                anchor_quote=self.anchor_quote,
            ),
        )


class GroundTruthSet(BaseModel):
    celex: str
    description: str = ""
    obligations: list[GroundTruthObligation] = Field(default_factory=list)

    @property
    def gap_ids(self) -> set[str]:
        return {o.id for o in self.obligations if o.is_gap}


_DEFAULT_PATH = Path(__file__).parent / "dora_32022R2554.groundtruth.json"


def load_groundtruth(path: Optional[Path] = None) -> GroundTruthSet:
    return GroundTruthSet.model_validate_json((path or _DEFAULT_PATH).read_text())
