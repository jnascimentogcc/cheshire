"""Catalog model. Built from `catalog/*.yaml` (M1) and from the database (M2+).

Pure data: no I/O. The engine imports only this module from the catalog package.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

Status = Literal["draft", "proposed", "validated"]
SbbState = Literal["recommended", "accepted", "deprecating", "prohibited"]
Strength = Literal["requires", "considers"]

# Weakest first, used to pick "the weakest status among the rules that activated it".
STATUS_ORDER: dict[str, int] = {"draft": 0, "proposed": 1, "validated": 2}

RESERVED_CONDITION_KEYS = ("abb_present", "except")


class Condition(BaseModel):
    """A map of tests that must all hold (AND). See docs/rule-language.md section 2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attributes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    abb_present: tuple[str, ...] = ()
    unless: Condition | None = None  # YAML key `except`

    def is_empty(self) -> bool:
        return not self.attributes and not self.abb_present and self.unless is None

    def to_raw(self) -> dict[str, Any]:
        raw: dict[str, Any] = {k: list(v) for k, v in self.attributes.items()}
        if self.abb_present:
            raw["abb_present"] = list(self.abb_present)
        if self.unless is not None:
            raw["except"] = self.unless.to_raw()
        return raw


def _string_list(key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"condition key {key!r} must be a list of strings, got {value!r}")
    return tuple(value)


def parse_condition(raw: object) -> object:
    """Turn the YAML shape of a condition into a `Condition`."""
    if raw is None:
        return Condition()
    if isinstance(raw, Condition):
        return raw
    if not isinstance(raw, Mapping):
        raise ValueError(f"a condition must be a map, got {raw!r}")
    attributes: dict[str, tuple[str, ...]] = {}
    abb_present: tuple[str, ...] = ()
    unless: Condition | None = None
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"condition keys must be strings, got {key!r}")
        if key == "abb_present":
            abb_present = _string_list(key, value)
        elif key == "except":
            parsed = parse_condition(value)
            assert isinstance(parsed, Condition)
            unless = parsed
        else:
            attributes[key] = _string_list(key, value)
    return Condition(attributes=attributes, abb_present=abb_present, unless=unless)


Cond = Annotated[Condition, BeforeValidator(parse_condition)]


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Attribute(_Item):
    id: str
    layer: Literal["core", "extension"]
    values: list[str]
    multi: bool = False
    question: str
    ask_if: Cond = Field(default_factory=Condition)
    applies_to_abbs: list[str] = Field(default_factory=list)
    status: Status = "validated"


class Characteristic(_Item):
    id: str
    values: list[str]
    status: Status = "validated"


class Lens(_Item):
    id: str
    name: str
    question: str
    feeds_attributes: list[str] = Field(default_factory=list)
    typical_dependencies: list[str] = Field(default_factory=list)
    status: Status = "validated"


class Abb(_Item):
    id: str
    name: str
    domain: str
    cross_cutting: bool = False
    description: str = ""
    recognition: list[str] = Field(default_factory=list)
    does_not_apply_when: str = ""
    status: Status = "validated"


class Sbb(_Item):
    id: str
    name: str
    realises: str
    state: SbbState
    applies_when: Cond = Field(default_factory=Condition)
    not_applies_when: Cond = Field(default_factory=Condition)
    reason_not_applies: str = ""
    reason_prohibited: str = ""
    when_to_choose: str = ""
    limitations: str = ""
    owner: str = ""
    characteristics: dict[str, str] = Field(default_factory=dict)
    status: Status = "validated"


class Rule(_Item):
    id: str
    when: Cond = Field(default_factory=Condition)
    activates: str
    strength: Strength
    reason: str = ""
    status: Status = "validated"


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attributes: list[Attribute] = Field(default_factory=list)
    characteristics: list[Characteristic] = Field(default_factory=list)
    lenses: list[Lens] = Field(default_factory=list)
    abbs: list[Abb] = Field(default_factory=list)
    sbbs: list[Sbb] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)

    def attribute(self, attribute_id: str) -> Attribute | None:
        return next((a for a in self.attributes if a.id == attribute_id), None)

    def abb(self, abb_id: str) -> Abb | None:
        return next((a for a in self.abbs if a.id == abb_id), None)

    def sbbs_for(self, abb_id: str) -> list[Sbb]:
        return sorted((s for s in self.sbbs if s.realises == abb_id), key=lambda s: s.id)
