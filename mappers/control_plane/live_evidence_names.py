"""Shared name matching for live alias verify."""

from __future__ import annotations

from mappers.canonical_codes import names_fit, person_league
from mappers.control_plane.gap_fix_name_bind import club_bind_name_ok
from mappers.px_name_bind import orientation_pair_ok


def name_ok(
    left: str,
    right: str,
    league: str,
    *,
    partner: str = "",
    optic_partner: str = "",
) -> bool:
    """True when the typed name (left) and live label (right) are one entity.

    ``partner`` is the other catalogue participant. ``optic_partner`` is that
    side's Optic spelling; it defaults to ``partner`` when both feeds agree.
    """
    player = person_league(league)
    if names_fit(left, right, player=player):
        return True
    cat_partner = partner.strip()
    opt_partner = (optic_partner or partner).strip()
    if player and cat_partner and opt_partner and orientation_pair_ok(
        right, cat_partner, left, opt_partner, player=True,
    ):
        return True
    return not player and club_bind_name_ok(left, right)
