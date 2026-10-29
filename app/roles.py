"""Role definitions for ThronosEdu multi-tenant attendance service.

Four roles ordered by privilege level.  `has_at_least(user_role, minimum)`
returns True when the user's role is at or above the minimum.
"""
from __future__ import annotations

SUPER_ADMIN = "super_admin"
TENANT_DIRECTOR = "tenant_director"
TEACHER = "teacher"
STUDENT = "student"

_HIERARCHY: list[str] = [STUDENT, TEACHER, TENANT_DIRECTOR, SUPER_ADMIN]
_RANK: dict[str, int] = {role: idx for idx, role in enumerate(_HIERARCHY)}

ALL_ROLES = tuple(_HIERARCHY)


def has_at_least(user_role: str, minimum: str) -> bool:
    ur = _RANK.get(user_role)
    mr = _RANK.get(minimum)
    if ur is None or mr is None:
        return False
    return ur >= mr
