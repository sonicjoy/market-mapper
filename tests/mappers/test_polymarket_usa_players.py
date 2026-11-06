"""Polymarket US player-prop binding onto Optic player entities.

The gateway's typed ``metadata.playerName`` is the only key; there is no
compact name code.
"""

from __future__ import annotations

from mappers.exchanges.polymarket_usa_players import (
    bind_player_entities,
    build_player_index,
)
from mappers.market_types import MarketType
from mappers.pipeline import row_key
from mappers.shared import CanonicalRow

_HOME, _AWAY = "SEA", "KC"
_DATE = "2026-09-09T00:00:00Z"
_YARDS = MarketType.PLAYER_PASSING_YARDS.value


def _player(entity: str, market_type: str = _YARDS) -> CanonicalRow:
    return CanonicalRow(
        league="nfl", start_date=_DATE, home=_HOME, away=_AWAY,
        market_type=market_type, entity=entity, line=224.5, side="over",
    )


def _bind(name: str, *rows: CanonicalRow) -> list:
    index = build_player_index({row_key(r): r for r in rows}, "nfl")
    return bind_player_entities([(_YARDS, name, 224.5, "over")], index, _DATE, _HOME, _AWAY)


def test_player_name_binds_the_one_optic_entity():
    assert _bind("Aaron Rodgers", _player("aaron_rodgers")) == [
        (_YARDS, "aaron_rodgers", 224.5, "over"),
    ]


def test_compact_name_code_no_longer_binds():
    assert _bind("aarrod", _player("aaron_rodgers")) == []


def test_exact_name_wins_over_a_second_fit():
    rows = (_player("josh_allen"), _player("josh_hines-allen"))
    assert _bind("Josh Allen", *rows) == [(_YARDS, "josh_allen", 224.5, "over")]


def test_two_fits_and_no_exact_name_drop_the_bet():
    rows = (_player("aaron_rodgers_sr"), _player("aaron_rodgers_jr"))
    assert _bind("Aaron Rodgers", *rows) == []


def test_bind_player_ignores_team_scope_rows():
    team_row = CanonicalRow(
        league="nfl", start_date=_DATE, home=_HOME, away=_AWAY,
        market_type=MarketType.TEAM_TOTAL.value,
        entity="SEA", line=10.5, side="over",
    )
    assert _bind("Aaron Rodgers", team_row, _player("aaron_rodgers")) == [
        (_YARDS, "aaron_rodgers", 224.5, "over"),
    ]
