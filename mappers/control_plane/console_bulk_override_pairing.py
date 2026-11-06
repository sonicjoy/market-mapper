"""Draft venue selection -> Optic selection pairs for a bulk override (pure; no I/O).

A pair is only ever a *proposal*: the operator confirms every row before
anything is published. Status vocabulary:

- ``confident`` - exactly one Optic selection whose name is the same team or
  person (``names_close``), and the line agrees when both sides carry one;
- ``review``    - exactly one candidate, but only on a looser name match
  (``names_fit`` legal-name extension, or every token of the shorter name
  inside the longer), or a 2-way No complement (valid only where the series
  cannot end in a draw - the mapper keeps an allowlist for that,
  ``mappers/kalshi_complement.py``);
- ``ambiguous`` - more than one Optic selection fits, or two venue selections
  landed on the same Optic selection;
- ``no_match``  - nothing fits.

Names come from the venue's own text (Kalshi ``yes_sub_title``) only. The
ticker is an opaque id: no code is read off it and no tip alias is consulted,
so a leg with no display name is left for the operator to pick by hand.

No sides follow the mapper's complement rules (``kalshi_complement.py``):
on a double-chance market "X No" is the selection that excludes X ("TIE No"
is "A Or B"); on a two-selection market it is the other selection.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from mappers.canonical_codes import names_close, names_fit, tokens

_MAX_ALTERNATIVES = 5
_LINE_EPS = 1e-6
_TIER_STATUS = {1: "confident", 2: "review", 3: "review"}
_OR_SPLIT = re.compile(r"\s+or\s+", re.IGNORECASE)


def _tokens_within(left: str, right: str) -> bool:
    """Every token of the shorter name appears in the longer (Miami -> Miami Florida)."""
    at = {t.upper() for t in tokens(left)}
    bt = {t.upper() for t in tokens(right)}
    if not at or not bt:
        return False
    shorter, longer = (at, bt) if len(at) <= len(bt) else (bt, at)
    return shorter <= longer


def _name_tier(name: str, optic_name: str, *, player: bool) -> int | None:
    """1 = same entity, 2 = legal-name extension, 3 = token containment, None = no fit."""
    if names_close(name, optic_name, player=player):
        return 1
    if names_fit(name, optic_name, player=player):
        return 2
    if _tokens_within(name, optic_name):
        return 3
    return None


def _optic_label(sel: dict[str, Any]) -> str:
    """The name an Optic selection is matched on (totals carry it in selection_line)."""
    return str(sel.get("selection") or sel.get("selection_line") or "").strip()


def _line_agrees(leg: dict[str, Any], sel: dict[str, Any]) -> bool:
    """False only when both sides carry a line and they differ."""
    raw = leg.get("line")
    if raw is None or raw == "":
        return True
    points = sel.get("points")
    if points is None:
        return True
    return abs(float(raw) - float(points)) < _LINE_EPS


_TIE_NAMES = ("Draw", "Tie")


def leg_names(leg: dict[str, Any]) -> list[str]:
    """The venue's own display name for the leg; a tie / draw name matches either word."""
    name = str(leg.get("name") or "").strip()
    if not name:
        return []
    if name.casefold() in {t.casefold() for t in _TIE_NAMES}:
        return [name, *(t for t in _TIE_NAMES if t.casefold() != name.casefold())]
    return [name]


def _candidates(
    names: list[str], selections: Iterable[dict[str, Any]], leg: dict[str, Any], *, player: bool
) -> list[tuple[int, dict[str, Any]]]:
    """(best tier, selection) for every Optic selection some leg name fits."""
    out: list[tuple[int, dict[str, Any]]] = []
    for sel in selections:
        label = _optic_label(sel)
        if not label or not _line_agrees(leg, sel):
            continue
        tiers = [t for t in (_name_tier(n, label, player=player) for n in names) if t is not None]
        if tiers:
            out.append((min(tiers), sel))
    return out


def _pair(
    leg: dict[str, Any], status: str, reason: str, target: dict[str, Any] | None, alternatives: list[dict[str, Any]]
) -> dict[str, Any]:
    """One draft row the UI renders and the operator confirms or edits."""
    return {
        "source_market_id": str(leg.get("source_market_id") or ""),
        "source_selection_id": str(leg.get("source_selection_id") or ""),
        "leg_name": str(leg.get("name") or leg.get("source_market_id") or ""),
        "status": status,
        "reason": reason,
        "target": target,
        "alternatives": alternatives[:_MAX_ALTERNATIVES],
    }


def _covers(label: str, names: list[str], *, player: bool) -> bool:
    """True when one side of an ``A Or B`` label is one of the leg's names."""
    return any(_name_tier(n, part, player=player) == 1 for part in _OR_SPLIT.split(label) for n in names)


def _draft_no(
    leg: dict[str, Any], names: list[str], selections: list[dict[str, Any]], *, player: bool
) -> dict[str, Any]:
    """X No: the double chance excluding X, or the other side of a two-way market."""
    labels = [(sel, _optic_label(sel)) for sel in selections]
    double = [(sel, lab) for sel, lab in labels if _OR_SPLIT.search(lab)]
    if double:
        excluding = [sel for sel, lab in double if not _covers(lab, names, player=player)]
        covering = len(double) - len(excluding)
        if len(excluding) == 1 and covering == len(double) - 1:
            return _pair(leg, "confident", "No = double chance on the other two outcomes", excluding[0], [])
        return _pair(
            leg,
            "ambiguous",
            f"{len(excluding)} double-chance selections exclude {names[0]}",
            None,
            excluding or selections,
        )
    others = [sel for sel, lab in labels if not any(_name_tier(n, lab, player=player) for n in names)]
    if len(selections) == 2 and len(others) == 1:
        return _pair(
            leg, "review", "No = the other side; only valid if this series cannot end in a draw", others[0], []
        )
    return _pair(leg, "review", "No side: pick the opposing outcome by hand", None, selections)


def _is_no(leg: dict[str, Any]) -> bool:
    """Venue selection is the No side of a binary contract."""
    return str(leg.get("source_selection_id") or "").strip().lower() == "no"


def draft_pair(
    leg: dict[str, Any],
    selections: list[dict[str, Any]],
    *,
    player: bool = False,
) -> dict[str, Any]:
    """Propose the Optic selection for one venue selection (selections = one Optic market)."""
    names = leg_names(leg)
    if _is_no(leg):
        if not names:
            return _pair(leg, "review", "No side with no known name: pick by hand", None, selections)
        return _draft_no(leg, names, selections, player=player)
    if not names:
        return _pair(leg, "no_match", "no display name: pick by hand", None, [])
    found = _candidates(names, selections, leg, player=player)
    if not found:
        return _pair(leg, "no_match", f"no Optic selection fits {', '.join(names)}", None, [])
    best = min(tier for tier, _ in found)
    top = [sel for tier, sel in found if tier == best]
    if len(top) > 1:
        return _pair(leg, "ambiguous", f"{len(top)} Optic selections fit {names[0]}", None, top)
    how = "same name" if best == 1 else "partial name match - check it"
    return _pair(leg, _TIER_STATUS[best], how, top[0], [])


def _target_key(target: dict[str, Any]) -> tuple[str, ...]:
    """Identity of an Optic selection inside one market."""
    return tuple(
        str(target.get(k) or "") for k in ("market_id", "selection", "selection_line", "points", "grouping_key")
    )


def draft_pairs(
    legs: list[dict[str, Any]],
    selections: list[dict[str, Any]],
    *,
    no_selections: list[dict[str, Any]] | None = None,
    player: bool = False,
) -> list[dict[str, Any]]:
    """Draft every leg; two same-side legs on one Optic selection both drop to ambiguous.

    ``selections`` is the Optic market Yes sides land on (e.g. moneyline_3way);
    ``no_selections`` the one No sides land on (e.g. double_chance), defaulting
    to the same market.
    """
    no_market = selections if no_selections is None else no_selections
    pairs = [draft_pair(leg, no_market if _is_no(leg) else selections, player=player) for leg in legs]
    # A No complement legitimately shares its Optic odd with the other side's
    # Yes (the mapper's satellite rows do the same), so clash only within a side.
    taken = Counter((_is_no(leg), _target_key(p["target"])) for leg, p in zip(legs, pairs, strict=True) if p["target"])
    for leg, pair in zip(legs, pairs, strict=True):
        if pair["target"] and taken[(_is_no(leg), _target_key(pair["target"]))] > 1:
            pair["alternatives"] = [pair["target"]]
            pair["target"] = None
            pair["status"] = "ambiguous"
            pair["reason"] = "another venue selection chose the same Optic selection"
    return pairs


def status_counts(pairs: list[dict[str, Any]]) -> dict[str, int]:
    """Headline counts for the pairing table."""
    counts = Counter(str(p.get("status") or "") for p in pairs)
    return {s: counts.get(s, 0) for s in ("confident", "review", "ambiguous", "no_match")}
