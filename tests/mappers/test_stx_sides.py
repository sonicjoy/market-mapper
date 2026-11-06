"""STX YES / NO sides from typed fields, checked against each market's own question text (765 / 765, 2026-10-28).

The mapper never reads question text; this test does, to prove the typed derivation says what STX's text says.
"""

from __future__ import annotations

from collections import Counter

import pytest

from mappers.exchanges.stx import (
    AWAY,
    HOME,
    StxMarket,
    StxOutcome,
    StxParticipant,
    market_from_row,
    no_outcome,
    yes_outcome,
)
from mappers.vocab.stx_markets import (
    _OPTIC_TABLES,
    GAME_LINE_MARKETS,
    PLAYER_STAT_MARKETS,
    TEAM_STAT_MARKETS,
)
from tests.mappers import _stx_capture as cap

#: The families the trial checked (``side_checks.json``): game lines, team totals, 3-way and its 1st half.
CHECKED_RULES = frozenset(
    {
        "home_winner",
        "away_winner",
        "spread",
        "over_under",
        "participant_stat_line",
        "home_winner_regulation_3way",
        "away_winner_regulation_3way",
        "draw_regulation_3way",
        "home_winner_regulation_3way_r1",
        "away_winner_regulation_3way_r1",
        "draw_regulation_3way_r1",
    }
)


def _n(x: float | None) -> str:
    assert x is not None
    return f"{x:g}"


def _says(m: StxMarket, yes: StxOutcome | None, q: str) -> bool:
    h, a = m.participant(HOME), m.participant(AWAY)
    assert yes is not None and h is not None and a is not None
    home, away, line = h.name, a.name, yes.line
    if yes.kind == "draw":
        return "end in a draw" in q
    if m.rules == "spread":
        if line is not None and line < 0:
            return q.startswith(f"Will the {home} defeat the {away} by more than {_n(-line)} ")
        return q.startswith(f"Will the {home} win or lose to the {away} by less than {_n(line)} ")
    if m.rules == "over_under":
        return yes.kind == "over" and f"combine to score more than {_n(line)} " in q
    if m.rules == "participant_stat_line":
        team = home if yes.role == HOME else away
        return yes.kind == "over" and q.startswith(f"Will {team} have more than {_n(line)} ")
    team, other = (home, away) if yes.role == HOME else (away, home)
    return q.startswith(f"Will the {team} ") and f"the {other}" in q


def test_765_of_765_game_line_yes_sides_agree_with_their_text():
    checked = [m for m in cap.markets() if m.rules in CHECKED_RULES]
    assert len(checked) == 765
    q = cap.questions()
    bad = [m.market_id for m in checked if not _says(m, yes_outcome(m), q[m.market_id])]
    assert bad == []
    by_sport = Counter(m.sport for m in checked)
    assert by_sport == Counter(
        {"Football": 527, "Soccer": 102, "Cricket": 54, "Hockey": 44, "Basketball": 24, "Baseball": 14}
    )


def _m(rules: str, specifier: str | None = None, **stat) -> StxMarket:
    row = {
        "market_id": "m",
        "event_id": "e",
        "event_start": "2026-11-01T00:00:00Z",
        "rules": rules,
        "specifier": specifier,
        "event_type": "football_game",
        "sport": "Football",
        "competition": "NFL",
        "participants": [{"name": "Away Team", "role": "away"}, {"name": "Home Team", "role": "home"}],
        "stat_detail": stat or None,
    }
    m = market_from_row(row)
    assert m is not None
    return m


@pytest.mark.parametrize(
    ("market", "yes", "no"),
    [
        (_m("home_winner"), StxOutcome("team", HOME), StxOutcome("team", AWAY)),
        (_m("away_winner"), StxOutcome("team", AWAY), StxOutcome("team", HOME)),
        # spread is signed from the HOME side; NO is the away team at minus the line
        (_m("spread", "-2.5"), StxOutcome("team", HOME, -2.5), StxOutcome("team", AWAY, 2.5)),
        (_m("spread", "3.5"), StxOutcome("team", HOME, 3.5), StxOutcome("team", AWAY, -3.5)),
        # a total is the OVER; NO is the under of the SAME line, never another market
        (_m("over_under", "46.5"), StxOutcome("over", line=46.5), StxOutcome("under", line=46.5)),
        (
            _m(
                "participant_stat_line",
                "away|TOUCHDOWNS|2.5",
                participant="away",
                stat="TOUCHDOWNS",
                line=2.5,
                prop_type="ou",
            ),
            StxOutcome("over", AWAY, 2.5),
            StxOutcome("under", AWAY, 2.5),
        ),
        (
            _m(
                "player_stat_line",
                "Jordan Love|242729|PASS_YDS|260.5",
                player="Jordan Love",
                stat="PASS_YDS",
                line=260.5,
                prop_type="ou",
            ),
            StxOutcome("over", line=260.5, player="Jordan Love"),
            StxOutcome("under", line=260.5, player="Jordan Love"),
        ),
        # NO on a 3-way leg is a double chance: not one selection
        (_m("draw_regulation_3way"), StxOutcome("draw"), None),
        (_m("home_winner_regulation_3way"), StxOutcome("team", HOME), None),
    ],
)
def test_yes_and_no(market, yes, no):
    assert yes_outcome(market) == yes
    assert no_outcome(market) == no


def test_unread_shapes_have_no_side():
    assert (
        yes_outcome(_m("event_stat_line", "both|OVERTIME|NA", participant="both", stat="OVERTIME", prop_type="yn"))
        is None
    )
    assert yes_outcome(_m("spread", "pk")) is None
    assert yes_outcome(_m("superbowl_champion", "TEN")) is None


def test_participant_lookup_refuses_a_duplicated_role():
    m = _m("home_winner")
    twice = StxMarket(**{**m.__dict__, "participants": (StxParticipant("A", HOME), StxParticipant("B", HOME))})
    assert twice.participant(HOME) is None


def test_every_optic_id_in_the_vocab_is_one_mmmapper_maps_for_that_sport():
    tables = [GAME_LINE_MARKETS, TEAM_STAT_MARKETS, PLAYER_STAT_MARKETS]
    missing = [
        (sport, oid)
        for t in tables
        for sport, ids in t.items()
        for oid in ids.values()
        if oid not in _OPTIC_TABLES[sport]
    ]
    assert missing == []
