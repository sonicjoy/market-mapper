"""Optic-to-Optic proposed rows keep identity refs only."""

from __future__ import annotations

from typing import Any

_IDENTITY_MIDS = frozenset({"competitor", "name", "fixture", "abbr", "id"})


def is_optic_book(sportsbook: str) -> bool:
    return sportsbook.strip().lower() == "optic"


def optic_identity_refs(refs: list[str]) -> list[str]:
    """Competitor, name, fixture, abbr, id — not questions or slugs."""
    return [ref for ref in refs if _identity_mid(ref)]


def optic_refs_for_pin(own: list[str], extra: list[str], code: str, name: str) -> list[str]:
    """Identity refs for one Optic pin; ignore exchange questions."""
    code_l = code.strip().lower()
    name_l = name.strip().lower()
    out: list[str] = []
    for ref in dict.fromkeys([*own, *extra]):
        if _owned_identity(ref, code_l, name_l):
            out.append(ref)
    for ref in own:
        if ref.startswith("optic:abbr:") and ref not in out:
            out.append(ref)
    return out


def apply_optic_abbr(row: dict[str, Any], refs: list[str]) -> None:
    """Copy optic:abbr onto source/target when harvest stored one."""
    if not is_optic_book(str(row.get("sportsbook") or "")):
        return
    abbr = ""
    prefix = "optic:abbr:"
    for ref in refs:
        if ref.startswith(prefix):
            shown = ref[len(prefix) :].strip()
            if shown:
                abbr = shown
                break
    if not abbr:
        return
    for key in ("source", "target"):
        side = row.get(key)
        if isinstance(side, dict):
            side["abbr"] = abbr


def _owned_identity(ref: str, code_l: str, name_l: str) -> bool:
    """True when this identity ref names this competitor or their fixture."""
    if not _identity_mid(ref):
        return False
    parts = ref.split(":", 2)
    mid = parts[1].lower()
    rest = parts[2] if len(parts) > 2 else ""
    if mid == "competitor":
        cid, _, shown = rest.partition(":")
        if code_l and cid.lower() == code_l:
            return True
        return bool(name_l) and shown.strip().lower() == name_l
    if mid == "name":
        return bool(name_l) and rest.strip().lower() == name_l
    if mid == "fixture":
        return bool(name_l) and name_l in rest.lower()
    return False


def _identity_mid(ref: str) -> bool:
    parts = ref.split(":", 2)
    if len(parts) < 2:
        return False
    return parts[0].lower() == "optic" and parts[1].lower() in _IDENTITY_MIDS
