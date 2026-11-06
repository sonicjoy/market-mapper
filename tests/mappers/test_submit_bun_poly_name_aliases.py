"""Bundesliga official Poly question-name overlay pins."""

from __future__ import annotations

from mappers.control_plane.rows import EntityRow
from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType
from mappers.pipeline import _match_poly_fixture
from mappers.seed.sot import poly_team_name_aliases
from scripts.submit_bun_poly_name_aliases import (
    _TEAMS,
    LEAGUE,
    _evidence,
    build_payload,
)


class _FX:
    def __init__(self, home_name: str, away_name: str, start_date: str) -> None:
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def _game_parsed(team_a: str, team_b: str, date: str) -> pm.ParsedMarket:
    return pm.ParsedMarket(
        market_type=MarketType.GAME_TOTAL,
        team_a=pm._norm_name(team_a, "mlb_suffix"),
        team_b=pm._norm_name(team_b, "mlb_suffix"),
        side_mode=pm.SideMode.OVER_UNDER,
        line=2.5,
        date=date,
    )


def test_pins_rbl_and_bmg_question_names() -> None:
    payload = build_payload()
    by_key = {row.canonical_key: row for row in payload.entity_aliases}
    assert set(by_key) == {"RBL", "BMG"}
    for key, optic_name, poly_name, oid in _TEAMS:
        row = by_key[key]
        assert row.league == LEAGUE
        assert row.canonical_name == optic_name
        assert row.entity_type == "team"
        assert len(row.aliases) == 1
        pin = row.aliases[0]
        assert pin.sportsbook == "polymarket"
        assert pin.alias_kind == "name"
        assert pin.alias_value == poly_name
        joined = " ".join(_evidence())
        assert oid in joined
        assert poly_name in joined


def test_evidence_includes_live_slug_and_fixture() -> None:
    refs = _evidence()
    assert "gap:bun-lei-moe-2026-08-29-total-2pt5" in refs
    assert any(ref.startswith("optic:fixture:2026082905E0734E") for ref in refs)
    assert "optic:competitor:23643B23434A:RasenBallsport Leipzig" in refs
    assert "optic:competitor:153911A72568:Borussia VfL Mönchengladbach" in refs


def test_overlay_matches_lei_moe_fixture() -> None:
    payload = build_payload()
    ents = [
        EntityRow(
            league=row.league,
            entity_type=row.entity_type,
            canonical_key=row.canonical_key,
            canonical_name=row.canonical_name,
            aliases=[
                {
                    "sportsbook": pin.sportsbook,
                    "alias_kind": pin.alias_kind,
                    "alias_value": pin.alias_value,
                    "enabled": True,
                }
                for pin in row.aliases
            ],
        )
        for row in payload.entity_aliases
    ]
    overlay = poly_team_name_aliases(ents, league=LEAGUE)
    fixtures = [
        _FX(
            "RasenBallsport Leipzig",
            "Borussia VfL Mönchengladbach",
            "2026-08-29T13:30:00Z",
        )
    ]
    parsed = _game_parsed(
        "RB Leipzig", "Borussia Mönchengladbach", "2026-08-29",
    )
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None
    with pm.team_alias_scope(overlay):
        fx = _match_poly_fixture(parsed, fixtures, "mlb_suffix")
    assert fx is fixtures[0]
