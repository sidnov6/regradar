"""Synthetic Bank Profile schema (Part 5, design move).

A realistic but fictional bank: business functions, systems, processes, and a
Control Library. The Impact-Mapping agent maps obligations onto this; gaps are
obligations with no covering control. Being synthetic and public-data-only is
exactly why this is a clean $0 build (Part 10).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class BusinessFunction(BaseModel):
    id: str
    name: str
    description: str = ""


class System(BaseModel):
    id: str
    name: str
    function_ids: list[str] = Field(default_factory=list)
    is_third_party: bool = False
    description: str = ""


class Process(BaseModel):
    id: str
    name: str
    function_ids: list[str] = Field(default_factory=list)


class Control(BaseModel):
    id: str
    name: str
    description: str = ""
    # Thematic tags used by the deterministic candidate matcher (Part 3, agent 5).
    covers_themes: list[str] = Field(default_factory=list)
    system_ids: list[str] = Field(default_factory=list)
    function_ids: list[str] = Field(default_factory=list)


class BankProfile(BaseModel):
    name: str
    functions: list[BusinessFunction] = Field(default_factory=list)
    systems: list[System] = Field(default_factory=list)
    processes: list[Process] = Field(default_factory=list)
    controls: list[Control] = Field(default_factory=list)

    def control(self, control_id: str) -> Optional[Control]:
        return next((c for c in self.controls if c.id == control_id), None)

    def controls_for_theme(self, theme: str) -> list[Control]:
        t = theme.lower()
        return [c for c in self.controls if any(t == ct.lower() for ct in c.covers_themes)]


_DEFAULT_PATH = Path(__file__).parent / "synthetic_bank.json"


def load_profile(path: Optional[Path] = None) -> BankProfile:
    return BankProfile.model_validate_json((path or _DEFAULT_PATH).read_text())
