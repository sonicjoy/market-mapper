"""Filter/sort/pagination for GET /console/rules."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.console_rules_query import CANONICAL_NONE
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import InMemoryStore


def _alias(book: str, code: str) -> dict[str, str | bool]:
    return {"sportsbook": book, "alias_kind": "code", "alias_value": code, "enabled": True}


def _entity(league: str, key: str, name: str, *aliases: dict[str, str | bool]) -> EntityRow:
    return EntityRow(
        league=league,
        entity_type="team",
        canonical_key=key,
        canonical_name=name,
        aliases=list(aliases),
    )


def _league(slug: str, *books: str) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport="soccer" if slug != "nba" else "basketball",
        optic_league_id=slug,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96,
        enabled=slug != "nba",
        output_order=["moneyline"],
        exchanges=[{"sportsbook": b, "parser_profile": "x"} for b in books],
    )


def _rule(
    league: str,
    book: str,
    key: str,
    *,
    action: str = "map",
    canonical: str | None = "moneyline",
    source_key_type: str = "market_name",
) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"{league}-{book}-{key}",
        league=league,
        sportsbook=book,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=key,
        action=action,
        canonical_market_type=canonical,
        priority=100,
        enabled=True,
        confidence="manual",
    )


def _svc() -> ProposalService:
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_rules_query",
        entities=[
            _entity("epl", "M05", "Mainz", _alias("px", "M05"), _alias("optic", "oid-m05")),
            _entity("nba", "LAL", "Lakers", _alias("px", "LAL")),
            _entity("epl", "ARS", "Arsenal", _alias("polymarket", "Arsenal")),
        ],
        leagues=[
            _league("epl", "px", "optic"),
            _league("nba", "px"),
            _league("serie_a", "polymarket"),
        ],
        market_rules=[
            _rule("epl", "px", "GAME", canonical="moneyline_3way"),
            _rule("epl", "px", "BTTS", action="ignore", canonical=None),
            _rule("epl", "optic", "ml", canonical="moneyline"),
            _rule("nba", "px", "SPREAD", canonical="point_spread"),
            _rule("nba", "optic", "total", action="ignore", canonical=None),
        ],
        activate=True,
    )
    return ProposalService(store)


def test_market_rules_and_filters_and_none_canonical():
    svc = _svc()
    out = svc.human_rules(
        kind="market_rules",
        league=["epl"],
        sportsbook=["px"],
        canonical=[CANONICAL_NONE],
        action=["ignore"],
    )
    assert out["count"] == 1
    row = out["market_rules"][0]
    assert row["source_key"] == "BTTS"
    assert row["canonical_market_type"] is None


def test_market_rules_or_within_field():
    svc = _svc()
    out = svc.human_rules(kind="market_rules", sportsbook=["px", "optic"], league=["nba"])
    keys = {r["source_key"] for r in out["market_rules"]}
    assert keys == {"SPREAD", "total"}


def test_market_rules_sort_and_pagination():
    svc = _svc()
    all_rows = svc.human_rules(kind="market_rules", sort="source_key", sort_dir="asc", limit=500)
    keys = [r["source_key"] for r in all_rows["market_rules"]]
    assert keys == sorted(keys, key=str.lower)
    page0 = svc.human_rules(kind="market_rules", sort="source_key", sort_dir="asc", limit=2, offset=0)
    page1 = svc.human_rules(kind="market_rules", sort="source_key", sort_dir="asc", limit=2, offset=2)
    assert page0["count"] == 5
    assert [r["source_key"] for r in page0["market_rules"]] == keys[:2]
    assert [r["source_key"] for r in page1["market_rules"]] == keys[2:4]
    desc = svc.human_rules(kind="market_rules", sort="source_key", sort_dir="desc")
    assert [r["source_key"] for r in desc["market_rules"]] == list(reversed(keys))


def test_q_and_filters_together():
    svc = _svc()
    out = svc.human_rules(kind="market_rules", q="px", action=["map"])
    keys = {r["source_key"] for r in out["market_rules"]}
    assert keys == {"GAME", "SPREAD"}


def test_entities_multi_filters():
    svc = _svc()
    out = svc.human_rules(kind="entities", league=["epl"], sportsbook=["px", "polymarket"])
    by_key = {r["canonical_key"]: r for r in out["entities"]}
    assert set(by_key) == {"M05", "ARS"}
    assert {p["sportsbook"] for p in by_key["M05"]["aliases"]} == {"px", "optic"}
    assert {p["code"] for p in by_key["ARS"]["aliases"]} == {"Arsenal"}
    names = [
        r["entity_name"]
        for r in svc.human_rules(kind="entities", sort="entity", sort_dir="desc")["entities"]
    ]
    assert names == sorted(names, reverse=True)


def test_entities_sportsbook_filter_keeps_sibling_aliases():
    svc = _svc()
    out = svc.human_rules(kind="entities", sportsbook=["px"])
    by_key = {r["canonical_key"]: r for r in out["entities"]}
    assert set(by_key) == {"M05", "LAL"}
    assert {p["sportsbook"] for p in by_key["M05"]["aliases"]} == {"px", "optic"}
    assert {p["code"] for p in by_key["M05"]["aliases"]} == {"M05", "oid-m05"}


def test_leagues_sportsbook_and_sort():
    svc = _svc()
    optic = svc.human_rules(kind="leagues", sportsbook=["optic"])
    assert {r["league"] for r in optic["leagues"]} == {"epl"}
    by_sport = svc.human_rules(kind="leagues", sort="sport", sort_dir="asc")
    sports = [r["sport"] for r in by_sport["leagues"]]
    assert sports == sorted(sports)


def test_market_rules_polymarket_usa_is_own_rows():
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_poly_usa_rules",
        entities=[],
        leagues=[
            LeagueRow(
                league="serie_a",
                sport="soccer",
                optic_league_id="serie_a",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {"sportsbook": "polymarket", "parser_profile": "poly_generic_v1"},
                    {
                        "sportsbook": "polymarket_usa",
                        "parser_profile": "poly_usa_generic_v1",
                        "source_league_id": "seriea",
                        "enabled": True,
                    },
                ],
            ),
            _league("epl", "px", "optic"),
        ],
        market_rules=[
            _rule(
                "serie_a", "polymarket", "moneyline",
                canonical="moneyline", source_key_type="kind",
            ),
            _rule(
                "serie_a", "polymarket_usa", "moneyline",
                canonical="moneyline", source_key_type="kind",
            ),
            _rule("epl", "px", "GAME", canonical="moneyline_3way"),
        ],
        activate=True,
    )
    svc = ProposalService(store)
    out = svc.human_rules(kind="market_rules", sportsbook=["polymarket_usa"])
    assert out["count"] == 1
    row = out["market_rules"][0]
    assert row["league"] == "serie_a"
    assert row["source_key"] == "moneyline"
    assert row["sportsbook"] == "polymarket_usa"


def test_entities_polymarket_usa_is_own_codes():
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_poly_usa_entities",
        entities=[
            EntityRow(
                league="serie_a",
                entity_type="team",
                canonical_key="JUV",
                canonical_name="Juventus",
                aliases=[
                    {
                        "sportsbook": "polymarket",
                        "alias_kind": "name",
                        "alias_value": "Juventus",
                        "enabled": True,
                    },
                    {
                        "sportsbook": "px",
                        "alias_kind": "code",
                        "alias_value": "JUV",
                        "enabled": True,
                    },
                ],
            ),
            EntityRow(
                league="serie_a",
                entity_type="team",
                canonical_key="INT",
                canonical_name="Inter",
                aliases=[
                    {
                        "sportsbook": "polymarket_usa",
                        "alias_kind": "code",
                        "alias_value": "int",
                        "enabled": True,
                    },
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league="serie_a",
                sport="soccer",
                optic_league_id="serie_a",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {"sportsbook": "polymarket", "parser_profile": "poly_generic_v1"},
                    {
                        "sportsbook": "polymarket_usa",
                        "parser_profile": "poly_usa_generic_v1",
                        "source_league_id": "seriea",
                        "enabled": True,
                    },
                ],
            ),
        ],
        market_rules=[],
        activate=True,
    )
    svc = ProposalService(store)
    out = svc.human_rules(kind="entities", sportsbook=["polymarket_usa"])
    assert out["count"] == 1
    row = out["entities"][0]
    pins = row["aliases"]
    assert len(pins) == 1
    assert pins[0]["sportsbook"] == "polymarket_usa"
    assert pins[0]["code"] == "int"


def test_comma_separated_query_values():
    svc = _svc()
    out = svc.human_rules(kind="market_rules", league=["epl,nba"], action=["ignore"])
    assert {r["source_key"] for r in out["market_rules"]} == {"BTTS", "total"}


def test_http_repeated_filter_params():
    control = _svc()
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
    )
    try:
        client = TestClient(app)
        resp = client.get(
            "/console/rules",
            params={
                "kind": "market_rules",
                "league": ["epl", "nba"],
                "action": "ignore",
                "sort": "source_key",
                "dir": "desc",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        keys = [row["source_key"] for row in body["market_rules"]]
        assert keys == ["total", "BTTS"]
    finally:
        app.dependency_overrides.clear()
