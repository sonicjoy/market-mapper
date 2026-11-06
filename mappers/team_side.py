"""Map a venue's named team onto one Optic fixture side.

Every exchange stamps a moneyline, spread, or three-way through here.
Listing order and the words home and away are not inputs. A claim that
fits both sides, or neither, is unnamed and the caller drops the market.
"""

from __future__ import annotations

from mappers.canonical_codes import names_fit


def team_side(
    claimed: str,
    *,
    home: str,
    away: str,
    home_name: str = "",
    away_name: str = "",
    player: bool = False,
) -> str | None:
    """``home`` or ``away`` when ``claimed`` names exactly one of them."""
    text = (claimed or "").strip()
    if not text:
        return None
    hits = [
        side for side, name in ((home, home_name), (away, away_name))
        if side and _names_side(text, side, name, player=player)
    ]
    unique = list(dict.fromkeys(hits))
    return unique[0] if len(unique) == 1 else None


def _names_side(claimed: str, side: str, name: str, *, player: bool) -> bool:
    token = claimed.casefold()
    if token == side.casefold() or (name and token == name.casefold()):
        return True
    return bool(name) and names_fit(claimed, name, player=player)
