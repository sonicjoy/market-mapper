"""Tip-enabled Polymarket US inner codes."""

from __future__ import annotations

from mappers.seed.poly_usa_exchange import POLY_USA_BOOK
from mappers.seed.poly_usa_tip_inners import enabled_us_inners_from_tip


def _league_row(*, enabled: bool = True, usa_code: str = "eflch") -> dict:
    return {
        "league": "england_championship",
        "enabled": enabled,
        "tombstone": False,
        "exchanges": [{
            "sportsbook": POLY_USA_BOOK,
            "enabled": True,
            "source_league_id": usa_code,
        }],
    }


class _Row:
    def __init__(self, payload: dict) -> None:
        self.league = payload["league"]
        self.enabled = payload["enabled"]
        self.tombstone = payload["tombstone"]
        self.exchanges = payload["exchanges"]


def test_enabled_us_inners_from_tip():
    rows = [_Row(_league_row()), _Row(_league_row(usa_code="epl"))]
    assert enabled_us_inners_from_tip(rows) == ["eflch", "epl"]


def test_enabled_us_inners_skips_disabled_and_tombstoned():
    rows = [
        _Row(_league_row(enabled=False)),
        _Row({**_league_row(), "tombstone": True}),
    ]
    assert enabled_us_inners_from_tip(rows) == []
