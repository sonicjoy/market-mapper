"""A Kalshi player market Optic does not stamp takes its sibling's name.

Real shape (UCL 2026-10-13, ATM v MUN): Kalshi lists Lee Kang-in's 1+,
2+ and 3+ goal markets under one typed ``custom_strike.soccer_player``
id.  Optic stamps the Kalshi ticker only on its player_goals 0.5 row
("Kang-In Lee"); its 1.5 / 2.5 rows carry no Kalshi source_id.  The 2+
and 3+ rows must still land on Optic's entity, not on Kalshi's label
("lee_kang-in").
"""

from __future__ import annotations

from mappers.exchanges.kalshi import KalshiConfig, Market, build_rows
from mappers.sport import Sport

_SOCCER = KalshiConfig(sport=Sport.SOCCER)
_ET = "KXUCLGOAL-26OCT13ATMMUN"
_LEE = "169d41a8-4794-4295-8688-5a74df4c22fe"
_ATM = "2f51845c-cdac-431c-9f0f-1ee7c8878331"


def _goal(ticker: str, title: str, floor: float, player: str = _LEE) -> Market:
    return Market(
        event_ticker=_ET, ticker=ticker, title=title,
        strike_type="greater", floor_strike=floor,
        custom_strike={"soccer_player": player, "soccer_team": _ATM},
        competition_scope="Goalscorer", series_scope="Goalscorer",
    )


def _entities(
    markets: list[Market], optic: dict[str, str],
) -> dict[float | None, set[str | None]]:
    rows = build_rows("2026-10-13", "ATM", "MUN", markets, _SOCCER,
                      league="ucl", optic_player_names=optic)
    out: dict[float | None, set[str | None]] = {}
    for r in rows:
        out.setdefault(r.line, set()).add(r.entity)
    return out


def test_unstamped_lines_take_the_stamped_siblings_optic_name():
    markets = [
        _goal(f"{_ET}-ATMLKANG19-1", "Lee Kang-in: 1+ goals", 0.5),
        _goal(f"{_ET}-ATMLKANG19-2", "Lee Kang-in: 2+ goals", 1.5),
        _goal(f"{_ET}-ATMLKANG19-3", "Lee Kang-in: 3+ goals", 2.5),
    ]
    got = _entities(markets, {f"{_ET}-ATMLKANG19-1": "Kang-In Lee"})
    assert got == {None: {"kang-in_lee"}, 0.5: {"kang-in_lee"}, 1.5: {"kang-in_lee"}, 2.5: {"kang-in_lee"}}


def test_two_optic_names_for_one_player_id_borrow_neither():
    a, b = f"{_ET}-X-1", f"{_ET}-X-2"
    markets = [
        _goal(a, "Lee Kang-in: 1+ goals", 0.5),
        _goal(b, "Lee Kang-in: 2+ goals", 1.5),
        _goal(f"{_ET}-X-3", "Lee Kang-in: 3+ goals", 2.5),
    ]
    got = _entities(markets, {a: "Kang-In Lee", b: "Someone Else"})
    # Each stamped ticker keeps its own Optic name; the unstamped one
    # falls back to Kalshi's label rather than picking between them.
    assert got == {None: {"kang-in_lee"}, 0.5: {"kang-in_lee"}, 1.5: {"someone_else"}, 2.5: {"lee_kang-in"}}


def test_no_player_id_no_borrowing():
    stamped = _goal(f"{_ET}-Y-1", "Lee Kang-in: 1+ goals", 0.5)
    bare = Market(
        event_ticker=_ET, ticker=f"{_ET}-Y-2", title="Lee Kang-in: 2+ goals",
        strike_type="greater", floor_strike=1.5,
        competition_scope="Goalscorer", series_scope="Goalscorer",
    )
    got = _entities([stamped, bare], {f"{_ET}-Y-1": "Kang-In Lee"})
    assert got == {None: {"kang-in_lee"}, 0.5: {"kang-in_lee"}, 1.5: {"lee_kang-in"}}
