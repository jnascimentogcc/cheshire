"""Engine input and output types (docs/rule-language.md sections 8 and 9)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cheshire.catalog.models import SbbState, Status, Strength
from cheshire.engine.conditions import TraceTest, Tri

Source = Literal["stated", "inferred", "answered", "edited"]
Activation = Literal["identified", "confirmed", "potential"]
Coverage = Literal["covered", "conditional", "blocked", "gap"]
SbbResultKind = Literal["eligible", "conditional", "excluded"]
ExclusionCode = Literal["prohibited", "not_applies_when", "applies_when_not_met"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- input -------------------------------------------------------------------


class AbbMention(_Model):
    id: str
    span: str = ""


class AttributeValue(_Model):
    value: str | list[str]
    source: Source
    span: str = ""


class InterpreterOutput(_Model):
    abbs: list[AbbMention] = Field(default_factory=list)
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)


# --- output ------------------------------------------------------------------


class RuleEvidence(_Model):
    rule: str
    result: Tri
    strength: Strength
    status: Status
    reason: str
    tests: list[TraceTest]


class SbbOutcome(_Model):
    id: str
    name: str
    state: SbbState
    status: Status
    result: SbbResultKind
    exclusion: ExclusionCode | None = None
    reason: str = ""
    notes: list[str] = Field(default_factory=list)
    tests: list[TraceTest] = Field(default_factory=list)


class AbbResult(_Model):
    id: str
    activation: Activation
    strength: Strength | None = None
    validation: Status | None = None
    origin: list[RuleEvidence] = Field(default_factory=list)
    coverage: Coverage
    sbbs: list[SbbOutcome] = Field(default_factory=list)

    def ids(self, kind: SbbResultKind) -> list[str]:
        return [s.id for s in self.sbbs if s.result == kind]


class PendingQuestion(_Model):
    attribute: str
    question: str
    values: list[str]
    multi: bool
    impact: list[str]  # ids of the ABBs with an indeterminate evaluation it causes


class EngineResult(_Model):
    abbs: list[AbbResult]
    pending_questions: list[PendingQuestion]

    def abb(self, abb_id: str) -> AbbResult | None:
        return next((a for a in self.abbs if a.id == abb_id), None)


class EngineInputError(ValueError):
    """The interpreter output or the answers reference things the catalog does not declare."""
