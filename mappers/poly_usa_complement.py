"""Complete one-sided Polymarket US symbols with their NO-side Optic row.

A US symbol is one binary instrument: the maker quotes BOTH venue sides,
and the SELL side prices the Optic selection that pays when the YES side
does not.  ``_usa_complement_key`` already names that selection, and the
pass assumes Optic hangs the symbol on both listings — but on prod
2026-09-25 (``markets_us.market_mapping``, start_date >= now-30h) 8,038
symbols carried only ONE: 6,331 ``astatc`` over-only props, 557
yes-only (``btts``, ``gtd-yes``), 510 one-team spreads, 494 over-only
totals, 146 under-only props.  The maker (mmpolymarketusrfq
``symbol_sides``) cannot price the missing side, and a yes-only market
resolves NEITHER side there — a ``Yes`` row is witnessed as the YES only
when the ``No`` row sits beside it.  ``astatc-unl-ita-bel-…-btts`` alone
was 30.7k unmapped legs in 6 h.

The complement is stamped only where it is provably the whole NO side:

* yes/no — two outcomes by construction;
* over/under and team spreads — only at a half line (``x.5``), which
  cannot push; an integer or quarter line can, so its NO is not one row;
* moneylines are never completed here (``_usa_complement_key`` is None):
  a draw-capable NO is two selections, and ``aec`` already stamps both —
  except a two-outcome per-team market (``TWO_WAY_OUTCOME_TYPES``: tennis
  set, esports map / first blood), whose NO is the other team outright;
* per-outcome Yes-only types (``poly_usa_smt.YES_ONLY_TYPES``: method of
  victory / finish, exact score) never: their NO is every other outcome.

Missing > wrong: a complement row that already carries a US symbol, has
no Optic odd, or is absent is left alone.

Soccer per-outcome moneylines (``atc``: one symbol per home / away / draw)
are completed separately by :func:`stamp_usa_double_chance`: the NO of one
outcome is the double chance on the other two, the Kalshi GAME / 1H rule
(``kalshi_complement.attach_kalshi_double_chance_complements``).  The maker
cannot infer that side from the rows, so those rows alone carry
``polymarket_usa_side = "no"``.

Soccer "no team scores first" (the team-less first-team-to-score member)
is the period's total goals under 0.5. Where Optic prices no first-team-
to-score draw for the fixture, :func:`usa_no_goal_satellites` prices the
symbol off that under row instead. The under row usually carries the
venue's own total 0.5 symbol already, so the no-goal symbol goes on a
satellite keyed as the first-team-to-score tie — a different canonical
key, so it never shares the under row's MERGE key.

Its NO ("a team scores first") is that total's over 0.5, whether the YES
sits on Optic's own first-team-to-score draw or on the under fallback.
Optic prices no single "either team scores first" selection, so the NO
is a satellite too, keyed as the first-team-to-score ``HOME/AWAY`` side.

Off unless ``MAPPING_POLYUS_NO_GOAL_UNDER=1``: a maker that still reads
YES = Over off a row with no selection (mmpolymarketusrfq before #75)
would sell this symbol at its own YES price.
"""

from __future__ import annotations

import os
from typing import Any

from mappers.exchanges.polymarket_usa_bind import usa_market_id
from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE, CanonicalRow, double_chance_side
from mappers.vocab.poly_usa_smt import TWO_WAY_OUTCOME_TYPES, YES_ONLY_TYPES

_USA_BOOK = "Polymarket (USA)"
_FLIP = {"yes": "no", "no": "yes"}

# Soccer 3-way winner → the Optic double chance its outcome No lands on.
# Only the halves Optic prices a double chance for: no 2H, quarter, inning
# or F5 double chance exists, so those stay Yes-only.
# Soccer first team to score → the same period's total goals: its tie
# ("no team scores") settles exactly as that total's under 0.5.
_TOTAL_FOR_FIRST_TO_SCORE = {
    MarketType.FIRST_TEAM_TO_SCORE.value: MarketType.GAME_TOTAL.value,
    MarketType.FIRST_HALF_FIRST_TEAM_TO_SCORE.value: MarketType.FIRST_HALF_TOTAL.value,
    MarketType.SECOND_HALF_FIRST_TEAM_TO_SCORE.value: MarketType.SECOND_HALF_TOTAL.value,
}

_DOUBLE_CHANCE_FOR_3WAY = {
    MarketType.MONEYLINE_3WAY.value: MarketType.DOUBLE_CHANCE.value,
    MarketType.FIRST_HALF_WINNER_3WAY.value: MarketType.FIRST_HALF_DOUBLE_CHANCE.value,
}


def _pipeline_keys() -> tuple[Any, Any]:
    """``(row_key, _usa_complement_key)`` from the pipeline."""
    # Deferred: mappers.pipeline imports this module (cycle).
    from mappers.pipeline import _usa_complement_key, row_key

    return row_key, _usa_complement_key


def _row_symbol(row: CanonicalRow, odd_lookup: dict) -> str:
    """The US symbol this row carries (Path 2 stamp or Optic passthrough)."""
    if row.polymarket_usa_market_id:
        return row.polymarket_usa_market_id.casefold()
    odd = odd_lookup.get(row.optic_id) if row.optic_id else None
    if odd is None:
        return ""
    return usa_market_id((odd.source_ids or {}).get(_USA_BOOK))


def _is_exhaustive_pair(side: str, line: float | None) -> bool:
    """True when the complement listing is the ENTIRE NO side."""
    if side in ("yes", "no"):
        return True
    return line is not None and abs(float(line)) % 1 == 0.5


def _symbols_by_row(
    row_index: dict[tuple, CanonicalRow], odd_lookup: dict,
) -> dict[str, list[tuple]]:
    """{US symbol -> row keys carrying it} across Path 2 and passthrough."""
    carried: dict[str, list[tuple]] = {}
    for key, row in row_index.items():
        symbol = _row_symbol(row, odd_lookup)
        if symbol:
            carried.setdefault(symbol, []).append(key)
    return carried


def other_team_key(key: tuple) -> tuple | None:
    """Row key of the other team on a two-outcome per-team market."""
    league, start, home, away, mt, entity, line, side, grouping_key = key
    if entity is not None or line is not None or side not in (home, away) or home == away:
        return None
    other = away if side == home else home
    return (league, start, home, away, mt, entity, line, other, grouping_key)


def stamp_usa_complements(
    row_index: dict[tuple, CanonicalRow], odd_lookup: dict,
) -> dict[str, int]:
    """Stamp each one-sided US symbol onto its complement row; return stats."""
    _, complement_key = _pipeline_keys()
    stats = {"stamped": 0, "no_optic": 0, "claimed": 0, "not_exhaustive": 0}
    for symbol, keys in _symbols_by_row(row_index, odd_lookup).items():
        if len(keys) != 1:
            continue
        row = row_index[keys[0]]
        if row.market_type in YES_ONLY_TYPES:
            continue
        two_way = row.market_type in TWO_WAY_OUTCOME_TYPES
        if two_way and row.polymarket_usa_side != "yes":
            continue  # its team is not known to be the YES: missing > wrong
        other_key = other_team_key(keys[0]) if two_way else complement_key(keys[0])
        if other_key is None:
            continue
        if not two_way and not _is_exhaustive_pair(row.side, row.line):
            stats["not_exhaustive"] += 1
            continue
        other = row_index.get(other_key)
        if other is None or other.optic_id is None:
            stats["no_optic"] += 1
            continue
        if _row_symbol(other, odd_lookup):
            stats["claimed"] += 1
            continue
        other.polymarket_usa_market_id = symbol
        other.polymarket_usa_side = _FLIP.get(row.polymarket_usa_side or "")
        stats["stamped"] += 1
    return stats


def _double_chance_key(key: tuple, dc_type: str) -> tuple | None:
    """Row key of the double chance that excludes this outcome, else None."""
    league, start, home, away, _mt, entity, line, side, grouping_key = key
    outcomes = {home, away, TIE_SIDE}
    if entity is not None or line is not None or grouping_key is not None:
        return None
    if side not in outcomes or len(outcomes) != 3:
        return None
    dc_side = double_chance_side(outcomes - {side}, home, away)
    return (league, start, home, away, dc_type, None, None, dc_side, None)


def stamp_usa_double_chance(
    row_index: dict[tuple, CanonicalRow],
    odd_lookup: dict,
    *,
    soccer: bool,
) -> dict[str, int]:
    """Stamp each soccer outcome symbol's NO onto its double chance; return stats.

    A symbol qualifies only when one row carries it and that row is a
    full-game soccer 3-way outcome: then the symbol IS that outcome, and its
    NO is exactly the other two.
    """
    stats = {"stamped": 0, "no_optic": 0, "claimed": 0, "not_one_outcome": 0}
    if not soccer:
        return stats
    for symbol, keys in _symbols_by_row(row_index, odd_lookup).items():
        outcome_keys = [k for k in keys if row_index[k].market_type in _DOUBLE_CHANCE_FOR_3WAY]
        if not outcome_keys:
            continue
        if len(keys) != 1:
            stats["not_one_outcome"] += 1
            continue
        key = keys[0]
        dc_key = _double_chance_key(key, _DOUBLE_CHANCE_FOR_3WAY[row_index[key].market_type])
        if dc_key is None:
            stats["not_one_outcome"] += 1
            continue
        target = row_index.get(dc_key)
        if target is None or target.optic_id is None:
            stats["no_optic"] += 1
            continue
        if _row_symbol(target, odd_lookup):
            stats["claimed"] += 1
            continue
        target.polymarket_usa_market_id = symbol
        target.polymarket_usa_side = "no"
        stats["stamped"] += 1
    return stats


def no_goal_under_enabled() -> bool:
    """``MAPPING_POLYUS_NO_GOAL_UNDER=1`` turns the under 0.5 fallback on."""
    return os.environ.get("MAPPING_POLYUS_NO_GOAL_UNDER", "").strip() == "1"


def _total_half_goal(row_index: dict, key: tuple, total_type: str, side: str) -> CanonicalRow | None:
    """The fixture's ``total_type`` row at 0.5 on ``side``, when Optic prices it."""
    league, start, home, away, *_ = key
    row = row_index.get((league, start, home, away, total_type, None, 0.5, side, None))
    return row if row is not None and row.optic_id is not None else None


def _no_goal_no(yes: CanonicalRow, symbol: str, over: CanonicalRow) -> CanonicalRow:
    """The NO satellite of a no-goal symbol: "a team scores first" = over 0.5."""
    return yes.model_copy(update={
        "side": double_chance_side({yes.home, yes.away}, yes.home, yes.away),
        "optic_id": over.optic_id,
        "polymarket_usa_market_id": symbol,
        "polymarket_usa_side": "no",
        "polymarket_usa_satellite": True,
    })


def usa_no_goal_satellites(
    row_index: dict[tuple, CanonicalRow],
    dropped: list[CanonicalRow],
    *,
    soccer: bool,
    odd_lookup: dict | None = None,
) -> tuple[list[CanonicalRow], dict[str, int]]:
    """Satellites completing each soccer "no team scores" symbol off total 0.5.

    YES: a ``dropped`` first-team-to-score tie (a derived US row no Optic
    row took) is priced off the period's under 0.5. NO: every no-goal
    symbol with a known YES and no NO — the under fallback's, or one Path 2
    stamped on Optic's own draw — is priced off the over 0.5. Load emits
    each satellite as Polymarket (USA) only, so the total rows' other books
    are not copied.
    """
    stats = {"stamped": 0, "no_optic": 0, "no_stamped": 0, "no_no_optic": 0}
    if not soccer or not no_goal_under_enabled():
        return [], stats
    out = _under_yeses(row_index, dropped, stats)
    yeses = out + _stamped_yeses(row_index, odd_lookup or {})
    out.extend(_no_goal_nos(row_index, yeses, stats))
    return out, stats


def _under_yeses(
    row_index: dict[tuple, CanonicalRow],
    dropped: list[CanonicalRow],
    stats: dict[str, int],
) -> list[CanonicalRow]:
    """Dropped first-team-to-score ties priced off the period's under 0.5."""
    row_key, _ = _pipeline_keys()
    out: list[CanonicalRow] = []
    seen: set[tuple] = set()
    for ur in dropped:
        total_type = _TOTAL_FOR_FIRST_TO_SCORE.get(ur.market_type)
        if total_type is None or ur.side != TIE_SIDE or ur.line is not None:
            continue
        key = row_key(ur)
        if key in row_index or key in seen:
            continue
        under = _total_half_goal(row_index, key, total_type, "under")
        if under is None:
            stats["no_optic"] += 1
            continue
        ur.optic_id = under.optic_id
        ur.polymarket_usa_satellite = True
        seen.add(key)
        out.append(ur)
        stats["stamped"] += 1
    return out


def _stamped_yeses(row_index: dict[tuple, CanonicalRow], odd_lookup: dict) -> list[CanonicalRow]:
    """No-goal YES rows Path 2 stamped on Optic's own draw, one row per symbol."""
    carried = _symbols_by_row(row_index, odd_lookup)
    return [
        row for row in row_index.values()
        if row.market_type in _TOTAL_FOR_FIRST_TO_SCORE and row.side == TIE_SIDE
        and row.polymarket_usa_market_id and row.polymarket_usa_side == "yes"
        and len(carried.get(row.polymarket_usa_market_id.casefold(), [])) == 1
    ]


def _no_goal_nos(
    row_index: dict[tuple, CanonicalRow],
    yeses: list[CanonicalRow],
    stats: dict[str, int],
) -> list[CanonicalRow]:
    """The NO of each known no-goal YES, priced off the over 0.5."""
    row_key, _ = _pipeline_keys()
    out: list[CanonicalRow] = []
    for yes in yeses:
        symbol = yes.polymarket_usa_market_id
        if yes.polymarket_usa_side != "yes" or not symbol:
            continue
        over = _total_half_goal(
            row_index, row_key(yes), _TOTAL_FOR_FIRST_TO_SCORE[yes.market_type], "over")
        if over is None:
            stats["no_no_optic"] += 1
            continue
        out.append(_no_goal_no(yes, symbol, over))
        stats["no_stamped"] += 1
    return out
