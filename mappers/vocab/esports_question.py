"""Polymarket esports title grammar shared by live classify and gap harvest."""

from __future__ import annotations

import re

from mappers.handicap_name_crumb import is_esports_map_winner

# League of Legends question form. Verified live 2026-07-28 against 14 poly
# LoL markets resolved from the gamma API by clob_token_id (the token ids the
# optic feed carries in source_ids.selection_id): EVERY question is
#   "LoL: <A> vs <B> (BO<n>) - <Tournament>"
# and every slug starts "lol-" (BO1/BO3/BO5 all observed; tournament segment
# varies freely — LCK/LFL/NLC/CBLOL/LPLOL/Prime League/Arabian League/...).
#
# Shape-identical to UFC's "UFC <Event>: <A> vs. <B> (<...>)": a prefix before
# the colon plus a trailing parenthetical, so group 2 is anchored on the
# literal "(" rather than end-of-string. mlb_moneyline_rule CANNOT be reused —
# it rejects any question containing ":" — and tennis_moneyline_rule takes the
# names after the LAST colon, which would mangle a tournament containing one.
#
# The leading alternation is the ONLY esports-title-specific part of this
# module: CS2 "Counter-Strike:", Dota 2 "Dota 2:", plus Honor of Kings /
# Mobile Legends / Valorant / Rainbow Six Siege (live bridge 2026-09-02).
# `.*?` is lazy, so
# for a bare "LoL: ..." it consumes nothing and the colon matched is still
# the first one.
_Q_ESPORTS_MONEYLINE = re.compile(
    r"^(?:LoL|Counter-Strike|Dota 2|Honor of Kings|"
    r"Mobile Legends(?: Bang Bang)?|Valorant|Rainbow Six(?: Siege)?)"
    r".*?:\s*(.+?)\s+vs\.?\s+(.+?)\s*\(",
    re.I,
)
# Retained alias — leagues/lol.py referenced this name in the LoL-only era.
_Q_LOL_MONEYLINE = _Q_ESPORTS_MONEYLINE


def esports_series_sides(question: str) -> tuple[str, str] | None:
    """Raw team names from a series moneyline title, else None.

    Same grammar as esports_moneyline_rule: map/game winners are not series
    markets; names stop at the ``(BO<n>)`` parenthetical.
    """
    q = (question or "").strip()
    if not q or is_esports_map_winner(q):
        return None
    match = _Q_ESPORTS_MONEYLINE.match(q)
    if match is None:
        return None
    left, right = match.group(1).strip(), match.group(2).strip()
    if not left or not right:
        return None
    return left, right
