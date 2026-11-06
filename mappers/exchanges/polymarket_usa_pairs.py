"""Doubles pairs: bind a venue pair name to Optic's folded pair, member by member."""

from __future__ import annotations

import re
from collections.abc import Callable


def pair_fits(name: str, optic_name: str, member_fits: Callable[[str, str], bool]) -> bool:
    """Doubles: each venue member fits exactly one distinct Optic member.

    Optic's folded pair is "Gabriela Dabrowski / Luisa Stefani" (``//`` raw);
    the venue writes "Dabrowski G / Stefani L" or "Pietri - Scaglia", in
    either order. ``member_fits`` is the single-person rule, never a looser one.
    """
    ours = [m.strip() for m in re.split(r"\s*/\s*|\s+-\s+", name) if m.strip()]
    theirs = [m.strip() for m in re.split(r"/+", optic_name) if m.strip()]
    if len(ours) != 2 or len(theirs) != 2:
        return False
    fits = [{i for i, t in enumerate(theirs) if member_fits(o, t)} for o in ours]
    return all(len(f) == 1 for f in fits) and fits[0] != fits[1]
