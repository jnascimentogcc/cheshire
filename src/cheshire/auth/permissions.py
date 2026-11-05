"""Permission layer, separate from domain logic: each action names the minimum role."""

from __future__ import annotations

from typing import Literal

Role = Literal["user", "architect", "admin"]
Permission = Literal[
    "consult",
    "catalog.read",
    "catalog.write",
    "catalog.validate",
    "catalog.import",
    "catalog.export",
    "users.manage",
]

_RANK: dict[str, int] = {"user": 0, "architect": 1, "admin": 2}  # admin includes architect

MINIMUM_ROLE: dict[Permission, Role] = {
    "consult": "user",
    "catalog.read": "user",
    "catalog.write": "architect",
    "catalog.validate": "architect",  # an architect may validate their own change (D28)
    "catalog.import": "architect",
    "catalog.export": "architect",
    "users.manage": "admin",
}


def allowed(role: str, permission: Permission) -> bool:
    return _RANK[role] >= _RANK[MINIMUM_ROLE[permission]]
