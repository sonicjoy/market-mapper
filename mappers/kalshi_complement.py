"""Kalshi moneyline No complement satellites.

Game-winner markets are one per outcome; only Yes is stamped in
build_rows.  The No side is mapped here as a satellite row: another
Optic odd carrying that ticker with kalshi_side=no.

2-way (attach_kalshi_moneyline_complements): "A No ≡ B Yes", so A's No
lands on B's Optic moneyline.  That only holds where a draw cannot
strand both Yes contracts at $0: no draw in the sport (basketball, tennis,
esports) or a league whose rules were read (MLB extra innings, NHL OT/SO,
NFL/CFL/UFC ties pay $0.50 on each Yes).  A league nobody has read the
rules for gets no complements.

3-way soccer (attach_kalshi_double_chance_complements): a game-winner market
settles on the same 90-minute result as Optic's moneyline_3way and
double_chance (a 1st-half winner on the half-time result, as 1h_winner_3way and
1h_double_chance do), so "A No" is the double chance on the other two
outcomes and "TIE No" is home-or-away.  No allowlist is needed: the Yes
row being 3-way is what makes the equivalence hold.
"""

from __future__ import annotations

from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE, CanonicalRow, double_chance_side
from mappers.sport import Sport

# Sports with no draw on a game-winner market.
_NO_DRAW_SPORTS = frozenset({Sport.BASKETBALL, Sport.TENNIS, Sport.ESPORTS})

# Leagues whose settlement rules were checked against the rule above.
# Deliberately absent, and not to be added without reading that league's
# rules: ncaaf (game rules omit ties), soccer (3-way — No is double
# chance), cricket (ties and rain no-results), npb / kbo (games are tied
# after 12 innings), boxing (draws are routine), hockey leagues other
# than the NHL (regulation 3-way or no shootout).
_RULES_READ_LEAGUES = frozenset({
    "nfl", "cfl",                          # tie pays $0.50 on each Yes
    "ufc",                                 # tie / no-contest likewise
    "mlb",                                 # extra innings, no draw
    "nhl",                                 # OT / shootout, no draw
})

# Every non-Kalshi book stamp on CanonicalRow.  The satellite shares the
# parent's MERGE key for all of them, so carrying one would duplicate the
# parent's row rather than map a second source.  A new book added to
# CanonicalRow must land here — test_complement_carries_no_other_book_stamp
# fails until it does.  Bools in this space are routing flags
# (crypto_satellite), not stamps, and must keep their False default.
_OTHER_BOOK_PREFIXES = (
    "px_", "crypto_", "polymarket_", "novig_", "huddle_", "runshop_",
)
_CLEARED_FIELDS = tuple(
    name for name, field in CanonicalRow.model_fields.items()
    if name.startswith(_OTHER_BOOK_PREFIXES) and field.annotation is not bool
)


def _kalshi_yes_ml(row: CanonicalRow) -> bool:
    return row.kalshi_ticker is not None and row.kalshi_side == "yes"


def complements_hold(league: str, sport: Sport) -> bool:
    """Whether "A No ≡ B Yes" holds for this league's game winner."""
    return sport in _NO_DRAW_SPORTS or league in _RULES_READ_LEAGUES


def _complement_row(target: CanonicalRow, yes_row: CanonicalRow) -> CanonicalRow:
    """Target's Optic identity carrying yes_row's ticker, No side.

    Every non-Kalshi stamp is cleared: the satellite shares the parent's
    MERGE key, so a PX / crypto / Poly / Runshop stamp here would be a
    duplicate of the parent's row, not a second mapping.
    """
    return target.model_copy(update={
        **dict.fromkeys(_CLEARED_FIELDS),
        "kalshi_ticker": yes_row.kalshi_ticker,
        "kalshi_scope": yes_row.kalshi_scope,
        "kalshi_title": yes_row.kalshi_title,
        "kalshi_yes_sub_title": yes_row.kalshi_yes_sub_title,
        "kalshi_side": "no",
        "kalshi_complement": True,
    })


def attach_kalshi_moneyline_complements(
    row_index: dict[tuple, CanonicalRow],
    *,
    league: str,
    sport: Sport,
) -> list[CanonicalRow]:
    """Return satellite rows; caller appends to all_rows only (not row_index)."""
    if not complements_hold(league, sport):
        return []
    by_fixture: dict[tuple, dict[str, CanonicalRow]] = {}
    for row in row_index.values():
        # Full-game 2-way moneyline only: entity/line/grouping_key are all
        # None there, so one (side -> row) slot per fixture cannot collide.
        if row.market_type != MarketType.MONEYLINE.value:
            continue
        if row.entity is not None or row.line is not None:
            continue
        if row.optic_id is None or row.grouping_key is not None:
            continue
        if not _kalshi_yes_ml(row):
            continue
        key = (row.league, row.start_date, row.home, row.away)
        by_fixture.setdefault(key, {})[row.side] = row

    out: list[CanonicalRow] = []
    for (_league, _start, home, away), sides in by_fixture.items():
        home_row = sides.get(home)
        away_row = sides.get(away)
        if home_row is None or away_row is None:
            continue
        out.append(_complement_row(home_row, away_row))
        out.append(_complement_row(away_row, home_row))
    return out


# 3-way market type → the double chance market its No sides land on.
_DOUBLE_CHANCE_FOR_3WAY: dict[str, str] = {
    MarketType.MONEYLINE_3WAY.value: MarketType.DOUBLE_CHANCE.value,
    MarketType.FIRST_HALF_WINNER_3WAY.value: MarketType.FIRST_HALF_DOUBLE_CHANCE.value,
}
_DOUBLE_CHANCE_TYPES = frozenset(_DOUBLE_CHANCE_FOR_3WAY.values())


def _full_game(row: CanonicalRow) -> bool:
    return row.entity is None and row.line is None and row.grouping_key is None


def attach_kalshi_double_chance_complements(
    row_index: dict[tuple, CanonicalRow],
) -> list[CanonicalRow]:
    """Soccer GAME / 1H No → Optic double chance satellites.

    Each Yes ticker maps on its own: X No lands on the double chance that
    excludes X.  Return satellite rows; caller appends to all_rows only.
    """
    yes_by_game: dict[tuple, list[CanonicalRow]] = {}
    dc_by_game: dict[tuple, dict[str, CanonicalRow]] = {}
    for row in row_index.values():
        if not _full_game(row):
            continue
        fixture = (row.league, row.start_date, row.home, row.away)
        if row.market_type in _DOUBLE_CHANCE_TYPES:
            if row.optic_id is not None and row.kalshi_ticker is None:
                dc_by_game.setdefault(
                    (*fixture, row.market_type), {})[row.side] = row
            continue
        dc_type = _DOUBLE_CHANCE_FOR_3WAY.get(row.market_type)
        if (
            dc_type is not None
            and row.kalshi_ticker is not None
            and row.kalshi_side == "yes"
        ):
            yes_by_game.setdefault((*fixture, dc_type), []).append(row)

    out: list[CanonicalRow] = []
    for key, yes_rows in yes_by_game.items():
        targets = dc_by_game.get(key)
        if not targets:
            continue
        _league, _start, home, away, _dc_type = key
        outcomes = {home, away, TIE_SIDE}
        for yes_row in yes_rows:
            if yes_row.side not in outcomes:
                continue
            side = double_chance_side(outcomes - {yes_row.side}, home, away)
            target = targets.get(side)
            if target is not None:
                out.append(_complement_row(target, yes_row))
    return out
