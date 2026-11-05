"""Catalog import/export documents in open formats (YAML and JSON).

A *document* is the same shape as the six `catalog/*.yaml` files merged into one
mapping with the top-level keys `attributes`, `characteristics`, `lenses`, `abbs`,
`sbbs`, `rules`. Any of them may be missing in an import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from cheshire.catalog.loader import CATALOG_FILES, CatalogLoadError, catalog_from_dict
from cheshire.catalog.models import Catalog, Condition

Format = Literal["yaml", "json"]
_CONDITION_FIELDS = ("when", "applies_when", "not_applies_when", "ask_if")
_ALWAYS_STATUS = ("abbs", "sbbs", "rules")  # the example files state `status` explicitly


def item_to_raw(item: BaseModel, always_status: bool = True) -> dict[str, Any]:
    raw: dict[str, Any] = item.model_dump(exclude_defaults=True, exclude=set(_CONDITION_FIELDS))
    if always_status:
        raw["status"] = getattr(item, "status")  # noqa: B009
    for name in _CONDITION_FIELDS:
        cond = getattr(item, name, None)
        if isinstance(cond, Condition) and not cond.is_empty():
            raw[name] = cond.to_raw()
    return raw


def catalog_to_raw(catalog: Catalog) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [item_to_raw(item, key in _ALWAYS_STATUS) for item in getattr(catalog, key)]
        for key in CATALOG_FILES.values()
    }


def dump_document(catalog: Catalog, fmt: Format) -> str:
    raw = catalog_to_raw(catalog)
    if fmt == "json":
        return json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100)


def dump_files(catalog: Catalog, directory: Path) -> None:
    """Write the six `catalog/*.yaml` files."""
    directory.mkdir(parents=True, exist_ok=True)
    raw = catalog_to_raw(catalog)
    for filename, key in CATALOG_FILES.items():
        text = yaml.safe_dump({key: raw[key]}, sort_keys=False, allow_unicode=True, width=100)
        (directory / filename).write_text(text, encoding="utf-8")


def parse_document(text: str, fmt: Format) -> Catalog:
    try:
        data: Any = json.loads(text) if fmt == "json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise CatalogLoadError([f"invalid {fmt}: {exc}"]) from exc
    if not isinstance(data, dict):
        raise CatalogLoadError(["the document must be a mapping with catalog sections"])
    unknown = set(data) - set(CATALOG_FILES.values())
    if unknown:
        raise CatalogLoadError([f"unknown top-level keys: {sorted(unknown)}"])
    return catalog_from_dict({key: data.get(key) or [] for key in CATALOG_FILES.values()})
