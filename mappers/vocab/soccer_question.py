"""Polymarket soccer title grammar shared by live classify and gap harvest."""

from __future__ import annotations

import re

# 3-way ML -- draw: "Will <A> vs. <B> end in a draw?" (byte-exact per
# .superpowers/sdd/wave-4-probe-findings.md section C). Unlike every other
# two-team soccer form, the market phrase trails team B with NO colon, so a
# generic "<A> vs. <B>" capture folds "end in a draw" into the away name --
# whose bind key then becomes "draw", which matches no Optic competitor.
# Lives here, not in soccer_markets.py, so gap harvest reads the same grammar
# without importing the live matcher (same reason esports_question.py exists).
_Q_SOCCER_ML_DRAW = re.compile(
    r"^will\s+(.+?)\s+vs\.?\s+(.+?)\s+end in a draw\?\s*$", re.I
)


def soccer_draw_sides(question: str) -> tuple[str, str] | None:
    """Raw team names from a 3-way draw title, else None.

    Same grammar as soccer_ml_draw_rule; names are returned unnormalized so
    each caller applies its own ``_norm_name`` style.
    """
    match = _Q_SOCCER_ML_DRAW.match((question or "").strip())
    if match is None:
        return None
    left, right = match.group(1).strip(), match.group(2).strip()
    if not left or not right:
        return None
    return left, right
