"""Starter packs: a ready-made catalog an instance can import (decision D5).

A pack is a directory of the six `catalog/*.yaml` files. The one shipped with the project is
the fictional example catalog; importing it uses the normal import path, so it lands as
`proposed`, after a dry-run diff, and nothing is ever silently validated.
"""

from __future__ import annotations

from pathlib import Path

from cheshire.catalog.loader import load_catalog
from cheshire.catalog.models import Catalog
from cheshire.settings import Settings

_EXAMPLE = "example"


def pack_root(settings: Settings) -> Path:
    if settings.starter_pack_dir:
        return Path(settings.starter_pack_dir)
    return Path(__file__).resolve().parents[3] / "catalog"


def available(settings: Settings) -> list[dict[str, object]]:
    root = pack_root(settings)
    if not (root / "abbs.yaml").exists():
        return []
    catalog = load_catalog(root)
    return [
        {
            "name": _EXAMPLE,
            "title": "Example catalog (fictional)",
            "description": (
                "A small invented catalog of notification and reporting building blocks, "
                "useful to try Cheshire out or to see the file format."
            ),
            "counts": {
                "abbs": len(catalog.abbs),
                "sbbs": len(catalog.sbbs),
                "rules": len(catalog.rules),
                "attributes": len(catalog.attributes),
            },
        }
    ]


def load(settings: Settings, name: str) -> Catalog | None:
    if name != _EXAMPLE or not available(settings):
        return None
    return load_catalog(pack_root(settings))
