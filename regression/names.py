"""Independent name matching for the mapping invariants.

The invariants ask one question of a mapped contract: does the name the
VENUE prints on it agree with the Optic selection it was mapped to, or
with that selection's opponent?  Answering it with the engine's own
matcher (``mappers.canonical_codes.names_fit``, ``mappers.px_name_bind``)
would make the check blind to exactly the bugs it exists to catch — the
2026-09-29 side flip lived in ``px_name_bind.pair_fits``.  So this module
is a second, deliberately simple transcription that owes nothing to
``mappers/`` (README design rule: ``regression/`` never imports it).

Simple is the point.  The verdict that fails a gate is not "the names do
not match" (feeds disagree on spelling, abbreviations and ring names all
the time) but "the venue's label fits the OPPONENT and not the side it
was mapped to" — positive evidence of a swap, which a crude matcher can
only produce when the names really are the other way round.
"""

from __future__ import annotations

import re
import unicodedata

# Words venues wrap around a competitor name ("Court McGee to win",
# "Yes - Court McGee", "Dodgers (-1.5)").  Dropped before comparing.
_NOISE = frozenset(
    {
        "to",
        "win",
        "wins",
        "winner",
        "yes",
        "no",
        "the",
        "fc",
        "sc",
        "cf",
        "vs",
        "v",
        "at",
        "moneyline",
        "ml",
        "match",
        "fight",
        "game",
        "and",
        "or",
        "draw",
        "by",
        "of",
        "de",
    }
)
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(name: str | None) -> list[str]:
    """Accent-folded, lower-case alphanumeric tokens minus venue noise."""
    if not name:
        return []
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [t for t in _TOKEN.findall(folded.casefold()) if t not in _NOISE]


def fits(label: str | None, name: str | None) -> bool:
    """True when ``label`` plausibly names ``name``.

    Either every token of the shorter side appears in the longer, or the
    two share their last token (a person's surname, a club's nickname)
    and that token is not a one- or two-letter initial.
    """
    a, b = tokens(label), tokens(name)
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if set(short) <= set(long_):
        return True
    return a[-1] == b[-1] and len(a[-1]) > 2


def side_verdict(label: str | None, own: str | None, opponent: str | None) -> str:
    """Classify a venue label against the mapped side and its opponent.

    ``agrees``   fits the mapped side and not the opponent
    ``swapped``  fits the opponent and not the mapped side  (gate FAIL)
    ``unclear``  fits both, or neither — no evidence either way
    """
    own_fit, opp_fit = fits(label, own), fits(label, opponent)
    if own_fit and not opp_fit:
        return "agrees"
    if opp_fit and not own_fit:
        return "swapped"
    return "unclear"
