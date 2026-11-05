"""Load `catalog/*.yaml` into a `Catalog`. The file format is the public interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cheshire.catalog.models import Catalog

# file name -> top-level key (same as the `Catalog` field)
CATALOG_FILES: dict[str, str] = {
    "attributes.yaml": "attributes",
    "characteristics.yaml": "characteristics",
    "lenses.yaml": "lenses",
    "abbs.yaml": "abbs",
    "sbbs.yaml": "sbbs",
    "rules.yaml": "rules",
}


class CatalogLoadError(Exception):
    """The files could not be read or do not match the catalog schema."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def _read_yaml(path: Path, key: str) -> Any:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogLoadError([f"{path.name}: cannot read file ({exc.strerror})"]) from exc
    except yaml.YAMLError as exc:
        raise CatalogLoadError([f"{path.name}: invalid YAML: {exc}"]) from exc
    if not isinstance(data, dict) or set(data) != {key}:
        raise CatalogLoadError([f"{path.name}: expected a single top-level key {key!r}"])
    return data[key] or []


def load_catalog(directory: Path) -> Catalog:
    """Read the six catalog files from `directory`; schema errors list every problem."""
    raw: dict[str, Any] = {}
    for filename, key in CATALOG_FILES.items():
        raw[key] = _read_yaml(directory / filename, key)
    return catalog_from_dict(raw)


def catalog_from_dict(raw: dict[str, Any]) -> Catalog:
    """Build a `Catalog` from already-parsed data (YAML or JSON import)."""
    try:
        return Catalog.model_validate(raw)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        raise CatalogLoadError(problems) from exc
