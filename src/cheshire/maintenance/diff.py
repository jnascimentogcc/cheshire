"""Readable differences between two versions of a catalog item (no I/O).

Works on the item's open-format mapping (`catalog.transfer.item_to_raw`), so the diff
speaks the same language as the YAML view. Every change is a sentence: colour is never
the only carrier of meaning.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

ChangeKind = Literal["added", "removed", "changed"]


class Change(BaseModel):
    path: str
    kind: ChangeKind
    before: Any = None
    after: Any = None
    text: str


def _show(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_show(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_show(v)}" for k, v in value.items()) + "}"
    if isinstance(value, str):
        return repr(value) if len(value) <= 80 else repr(value[:77] + "...")
    return str(value)


def _scalar_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str | int | float | bool) for v in value)


def diff_items(before: dict[str, Any], after: dict[str, Any], prefix: str = "") -> list[Change]:
    """Changes needed to go from `before` to `after`, in a stable order."""
    changes: list[Change] = []
    for key in [*before, *(k for k in after if k not in before)]:
        path = f"{prefix}{key}"
        if key not in after:
            changes.append(
                Change(
                    path=path,
                    kind="removed",
                    before=before[key],
                    text=f"{path} removed (was {_show(before[key])})",
                )
            )
        elif key not in before:
            changes.append(
                Change(
                    path=path,
                    kind="added",
                    after=after[key],
                    text=f"{path} added: {_show(after[key])}",
                )
            )
        elif before[key] != after[key]:
            b, a = before[key], after[key]
            if isinstance(b, dict) and isinstance(a, dict):
                changes += diff_items(b, a, f"{path}.")
            elif _scalar_list(b) and _scalar_list(a):
                gone = [v for v in b if v not in a]
                new = [v for v in a if v not in b]
                parts = []
                if new:
                    parts.append("added " + ", ".join(_show(v) for v in new))
                if gone:
                    parts.append("removed " + ", ".join(_show(v) for v in gone))
                if not parts:  # same members, different order
                    parts.append("reordered")
                changes.append(
                    Change(
                        path=path,
                        kind="changed",
                        before=b,
                        after=a,
                        text=f"{path}: " + "; ".join(parts),
                    )
                )
            else:
                changes.append(
                    Change(
                        path=path,
                        kind="changed",
                        before=b,
                        after=a,
                        text=f"{path} changed from {_show(b)} to {_show(a)}",
                    )
                )
    return changes
