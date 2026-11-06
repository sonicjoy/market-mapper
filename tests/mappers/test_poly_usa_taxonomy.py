"""Copy official Polymarket kinds and Kalshi codes onto polymarket_usa."""

from __future__ import annotations

import pytest

from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK
from mappers.seed.poly_usa_taxonomy import build_usa_taxonomy_payload


def _league() -> LeagueRow:
    return LeagueRow(
        league="serie_a",
        sport="soccer",
        optic_league_id="serie_a",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={},
        exchanges=[
            {"sportsbook": "polymarket", "enabled": True, "parser_profile": "poly_generic_v1"},
            {
                "sportsbook": POLY_USA_BOOK,
                "enabled": True,
                "parser_profile": "poly_usa_generic_v1",
                "source_league_id": "seriea",
            },
        ],
    )


def _rule(book: str, key: str, *, league: str = "serie_a") -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"{league}-{book}-{key}",
        league=league,
        sportsbook=book,
        rule_kind="taxonomy",
        source_key_type="kind",
        source_key=key,
        action="map",
        canonical_market_type="moneyline",
        priority=100,
        enabled=True,
        confidence="manual",
    )


def test_copies_unique_kalshi_codes_and_never_polymarket_kinds() -> None:
    entities = [
        EntityRow(
            league="serie_a",
            entity_type="team",
            canonical_key="JUV",
            canonical_name="Juventus",
            aliases=[
                {"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "JUV"},
                {"sportsbook": "polymarket", "alias_kind": "name", "alias_value": "juventus"},
            ],
        ),
        EntityRow(
            league="serie_a",
            entity_type="team",
            canonical_key="INT",
            canonical_name="Inter",
            aliases=[
                {"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "INT"},
                {"sportsbook": POLY_USA_BOOK, "alias_kind": "code", "alias_value": "INT"},
            ],
        ),
        EntityRow(
            league="serie_a",
            entity_type="team",
            canonical_key="MIL",
            canonical_name="Milan",
            aliases=[
                {"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "ACM"},
            ],
        ),
        EntityRow(
            league="serie_a",
            entity_type="team",
            canonical_key="INT2",
            canonical_name="Inter II",
            aliases=[
                {"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "ACM"},
            ],
        ),
    ]
    payload = build_usa_taxonomy_payload(
        [_league()],
        entities,
        [_rule("polymarket", "moneyline"), _rule("kalshi", "GAME", league="epl")],
    )
    # Poly US is unrelated to Polymarket: no kind rule is ever copied.
    assert payload.market_rules == []
    keys = {(p.canonical_key, p.aliases[0].alias_value) for p in payload.entity_aliases}
    assert keys == {("JUV", "JUV")}


def test_noop_when_already_copied() -> None:
    entities = [
        EntityRow(
            league="serie_a",
            entity_type="team",
            canonical_key="JUV",
            canonical_name="Juventus",
            aliases=[
                {"sportsbook": "kalshi", "alias_kind": "code", "alias_value": "JUV"},
                {"sportsbook": POLY_USA_BOOK, "alias_kind": "code", "alias_value": "JUV"},
            ],
        ),
    ]
    with pytest.raises(RuntimeError, match="already copied"):
        build_usa_taxonomy_payload(
            [_league()],
            entities,
            [_rule(POLY_USA_BOOK, "moneyline")],
        )
