"""Resolver slots: Poly US books, football league, entity names."""

from __future__ import annotations

from mappers.control_plane.chat_catalog import named_sportsbooks
from mappers.control_plane.chat_intent import wants_league_onboard
from mappers.control_plane.chat_resolve import (
    HEX,
    KALSHI,
    NUMERIC,
    NX,
    OPTIC_HEX,
    POLY_CID,
    POLY_SLUG,
    US_SYMBOL,
    UUID,
    entity_name_from_message,
    is_entity_query,
    kalshi_ids,
    league_from_market_ids,
    nx_ids,
    other_probe_id,
    poly_usa_llm_prompt_fragment,
    poly_usa_parser_gaps,
    resolve_query,
)
from tests.conftest import us_gateway_market


def test_named_sportsbooks_poly_us_is_polymarket_usa() -> None:
    assert named_sportsbooks("Poly US") == ["polymarket_usa"]
    assert named_sportsbooks("enable these markets for Poly US") == ["polymarket_usa"]
    assert named_sportsbooks("polymarket us") == ["polymarket_usa"]
    assert named_sportsbooks("enable poly") == []


def test_football_player_props_default_to_nfl() -> None:
    ids = resolve_query(
        "enable player_passing_yards first_touchdown_scorer for Poly US"
    ).market_ids
    assert "player_passing_yards" in ids
    assert league_from_market_ids(ids) == "nfl"
    assert resolve_query(
        "enable player_passing_yards for Poly US"
    ).league == "nfl"


def test_add_raphinha_is_entity_not_league_onboard() -> None:
    assert wants_league_onboard("add raphinha") is False
    assert wants_league_onboard("entity raphinha") is False
    resolved = resolve_query("add raphinha")
    assert resolved.entity_name.lower() == "raphinha"
    assert is_entity_query("add raphinha", resolved)
    assert entity_name_from_message("entity raphinha") == "raphinha"


def test_entity_lead_does_not_swallow_optic_id_or_league_onboard() -> None:
    assert entity_name_from_message("what entity is E0133F3BCA247846") == ""
    valorant = "please map esport valorant league"
    assert is_entity_query(valorant, resolve_query(valorant)) is False
    assert wants_league_onboard(valorant) is True
    wta = "can we add wta for polymarket and map game"
    assert is_entity_query(wta, resolve_query(wta)) is False
    assert wants_league_onboard(wta) is True


def test_source_ids_classify_exchange_and_catalogue_tokens(us_gateway: dict[str, dict]) -> None:
    kalshi_msg = "gap on KXEPLGAME-26AUG131000EXRBW for epl"
    resolved = resolve_query(kalshi_msg)
    assert resolved.source_ids[0].kind == KALSHI
    assert kalshi_ids(resolved) == ("KXEPLGAME-26AUG131000EXRBW",)

    nx_msg = "why NX.F.OPT.FIFA-123-260910-M.O.1.2 unmapped"
    nx_resolved = resolve_query(nx_msg)
    assert nx_resolved.source_ids[0].kind == NX
    assert nx_ids(nx_resolved)[0].startswith("NX.F.OPT.")

    optic = resolve_query("what entity is E0133F3BCA247846")
    assert any(s.kind == OPTIC_HEX and s.value == "E0133F3BCA247846" for s in optic.source_ids)

    vs_fixture = resolve_query("Jannik Sinner vs Carlos Alcaraz")
    assert vs_fixture.has_fixture_vs is True
    assert vs_fixture.source_ids == ()

    poly_cid = "0x" + "ab" * 32
    cid_resolved = resolve_query(poly_cid)
    assert any(s.kind == POLY_CID and s.value == poly_cid for s in cid_resolved.source_ids)

    px_resolved = resolve_query("730003207")
    assert any(s.kind == NUMERIC and s.value == "730003207" for s in px_resolved.source_ids)

    novig = resolve_query("01a03c33-d23f-7040-90cb-d64c165ae185")
    assert any(s.kind == UUID for s in novig.source_ids)

    ticker = "aec-atp-benbon-botzan-2026-08-27"
    shaped = resolve_query(ticker)
    assert not any(s.kind == US_SYMBOL for s in shaped.source_ids), "shape is not identity"
    us_gateway['aec-atp-benbon-botzan-2026-08-27'] = us_gateway_market(
        'aec-atp-benbon-botzan-2026-08-27', league="atp", smt="tennis_match_winner",
        teams=(("benbon", "Benjamin Bonzi"), ("botzan", "Botic van de Zandschulp")),
        start="2026-08-27T10:00:00Z",
    )
    us_resolved = resolve_query(ticker)
    assert any(s.kind == US_SYMBOL and s.value == ticker for s in us_resolved.source_ids)

    slug = "bun-stu-koe-2026-09-04-exact-score-0-0"
    slug_resolved = resolve_query(slug)
    assert any(s.kind == POLY_SLUG and s.value == slug for s in slug_resolved.source_ids)

    long_hex = "ab" * 32
    hex_resolved = resolve_query(long_hex)
    assert any(s.kind == HEX and s.value == long_hex for s in hex_resolved.source_ids)
    assert other_probe_id(slug) == slug


def test_poly_usa_llm_prompt_lists_registry_kinds() -> None:
    fragment = poly_usa_llm_prompt_fragment()
    assert "football_player_passing_yards" in fragment
    assert "tennis_match_winner" in fragment
    assert "unrelated to Polymarket" in fragment
    assert "needs_code" in fragment


def test_poly_usa_parser_gaps_skip_full_game_lines() -> None:
    ids = (
        "moneyline",
        "point_spread",
        "total_points",
        "team_total",
        "player_passing_yards",
        "player_passing_attempts",
        "team_total_touchdowns",
        "player_rushing_+_receiving_yards",
        "team_total_sacks",
        "football_game_overtime",
        "football_player_passing_yards",
        "player_sacks",
    )
    assert poly_usa_parser_gaps(ids) == ("player_sacks",)
