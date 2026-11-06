"""Cart-aware market-rule verify + spine/Optic suggestions (no LLM)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mappers.control_plane.app import app, service
from mappers.control_plane.entry import NullLiveLookup
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.store import InMemoryStore
from mappers.control_plane.suggest_aliases import (
    build_alias_suggestions,
    filter_existing_aliases,
    suggest_aliases_from_optic,
)
from mappers.control_plane.suggest_markets import (
    _parse_spine_key,
    filter_existing_market_suggestions,
    suggest_market_rules,
)


def _seed_with_league() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_test_baseline",
        entities=[],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "optic",
                        "enabled": True,
                        "parser_profile": "optic_standard_v1",
                    }
                ],
            )
        ],
        activate=True,
    )
    return store


def _client(store: InMemoryStore) -> TestClient:
    control = ProposalService(store, live=NullLiveLookup())
    app.dependency_overrides[service] = lambda: control
    app.dependency_overrides[get_settings] = lambda: Settings(
        gcp_project="marketmaking-test",
    )
    return TestClient(app)


def _iap(email: str) -> dict[str, str]:
    return {"X-Goog-Authenticated-User-Email": f"accounts.google.com:{email}"}


def test_market_rule_verify_accepts_pending_cart_league():
    client = _client(_seed_with_league())
    resp = client.post(
        "/entry/market-rule/verify",
        json={
            "league": "brand_new_lg",
            "sportsbook": "optic",
            "source_key_type": "market_id",
            "source_key": "moneyline",
            "action": "map",
            "canonical_market_type": "moneyline",
            "acknowledge_shadow": True,
            "pending_league_slugs": ["brand_new_lg"],
        },
        headers=_iap("alice@wsd.com"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["pending_league"] is True
    assert any("staging cart" in w for w in body["warnings"])


def test_market_rule_submit_tags_the_editor_note() -> None:
    client = _client(_seed_with_league())
    sentence = "Yes side is unset"
    resp = client.post(
        "/entry/market-rule/submit",
        json={
            "league": "atp",
            "sportsbook": "optic",
            "source_key_type": "market_id",
            "source_key": "moneyline",
            "action": "map",
            "canonical_market_type": "moneyline",
            "notes": sentence,
            "note": sentence,
            "acknowledge_shadow": True,
        },
        headers=_iap("alice@wsd.com"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert f"note:{sentence}" in body["evidence"]
    assert sentence not in body["evidence"]
    row = body["mappings"][0]
    assert row["notes"] == sentence
    assert sentence not in row["evidence"]


def test_market_rule_submit_alone_blocks_pending_only_league():
    client = _client(_seed_with_league())
    resp = client.post(
        "/entry/market-rule/submit",
        json={
            "league": "brand_new_lg",
            "sportsbook": "optic",
            "source_key_type": "market_id",
            "source_key": "moneyline",
            "action": "map",
            "canonical_market_type": "moneyline",
            "acknowledge_shadow": True,
            "pending_league_slugs": ["brand_new_lg"],
        },
        headers=_iap("alice@wsd.com"),
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["reason_code"] == "league_not_on_tip"


def test_suggest_markets_from_spine_optic_id():
    out = suggest_market_rules(
        league="atp_new",
        optic_league_id="atp",
        sport="tennis",
        sportsbooks=["optic", "kalshi"],
    )
    assert out["ok"] is True
    assert out["source"] == "optic_league_id"
    assert any(s["pin"]["sportsbook"] == "optic" for s in out["suggestions"])


def test_suggest_markets_novig_uses_market_type():
    from mappers.control_plane.suggest_markets import _BOOK_COLUMNS, _book_suggestions

    assert _BOOK_COLUMNS["novig"] == ("market_type", "novig_market_types")
    rows = [{"canonical_market_type": "moneyline", "novig_market_types": "MONEYLINE"}]
    suggestions, warning = _book_suggestions(
        "novig",
        rows,
        league="atp_copy",
        source="test",
    )
    assert warning is None
    assert suggestions[0]["pin"]["source_key_type"] == "market_type"
    assert suggestions[0]["pin"]["sportsbook"] == "novig"


def test_suggest_markets_polymarket_usa_uses_kind():
    out = suggest_market_rules(
        league="epl_copy",
        optic_league_id="england_-_premier_league",
        sport="soccer",
        sportsbooks=["polymarket_usa"],
    )
    assert out["ok"] is True
    assert out["suggestions"]
    pin = out["suggestions"][0]["pin"]
    assert pin["sportsbook"] == "polymarket_usa"
    assert pin["source_key_type"] == "kind"


def test_parse_spine_key_px_strips_exact_and_suffix_prefixes():
    assert _parse_spine_key("exact:Moneyline", book="px") == ("Moneyline", "exact")
    assert _parse_spine_key("exact:Total Points", book="px") == ("Total Points", "exact")
    assert _parse_spine_key("suffix: Total Points", book="px") == ("Total Points", "suffix")
    assert _parse_spine_key("suffix:: Team Total Points", book="px") == (
        ": Team Total Points",
        "suffix",
    )


def test_suggest_markets_novig_from_spine_for_nfl():
    from mappers.control_plane.suggest_markets import _load_spine

    _load_spine.cache_clear()
    out = suggest_market_rules(
        league="nfl",
        optic_league_id="nfl",
        sport="football",
        sportsbooks=["novig"],
    )
    assert out["ok"] is True
    pins = {s["pin"]["source_key"]: s["pin"] for s in out["suggestions"]}
    assert pins["MONEY"]["canonical_market_type"] == "moneyline"
    assert pins["PASSING_YARDS"]["canonical_market_type"] == "player_passing_yards"
    assert pins["RECEIVING_YARDS"]["canonical_market_type"] == "player_receiving_yards"
    assert pins["TOUCHDOWNS"]["canonical_market_type"] == "player_touchdowns"
    assert pins["SPREAD_1H"]["canonical_market_type"] == "1h_point_spread"
    assert "MONEY_1H" not in pins


def test_suggest_markets_px_strips_exact_prefix_from_nfl_game_lines():
    out = suggest_market_rules(
        league="nfl",
        optic_league_id="nfl",
        sport="football",
        sportsbooks=["px"],
    )
    assert out["ok"] is True
    pins = {s["pin"]["source_key"]: s["pin"] for s in out["suggestions"]}
    assert "exact:" not in "".join(pins)
    assert pins["Moneyline"]["canonical_market_type"] == "moneyline"
    assert pins["Moneyline"]["match_operator"] == "exact"
    assert pins["Spread"]["canonical_market_type"] == "point_spread"
    assert pins["Total Points"]["canonical_market_type"] == "game_total"


def test_suggest_markets_px_suffix_operator_for_team_total():
    out = suggest_market_rules(
        league="nba",
        optic_league_id="nba",
        sport="basketball",
        sportsbooks=["px"],
    )
    assert out["ok"] is True
    team_total = next(
        s["pin"] for s in out["suggestions"] if s["pin"]["canonical_market_type"] == "team_total"
    )
    assert team_total["source_key"] == ": Team Total Points"
    assert team_total["match_operator"] == "suffix"


def test_suggest_markets_splits_semicolon_keys():
    out = suggest_market_rules(
        league="epl_copy",
        optic_league_id="england_-_premier_league",
        sport="soccer",
        sportsbooks=["crypto.com"],
    )
    assert out["ok"] is True
    keys = {s["pin"]["source_key"] for s in out["suggestions"]}
    assert any(";" not in k for k in keys)
    assert any("Goal" in k or "Saves" in k or "Shots" in k for k in keys)


def test_suggest_markets_http():
    client = _client(_seed_with_league())
    resp = client.post(
        "/entry/market-rule/suggest",
        json={
            "league": "atp_copy",
            "optic_league_id": "atp",
            "sport": "tennis",
            "sportsbooks": ["optic"],
        },
        headers=_iap("alice@wsd.com"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["suggestions"]


def test_build_alias_suggestions_from_competitors():
    out = build_alias_suggestions(
        league="demo_lg",
        sport="soccer",
        competitors=[
            {"optic_id": "abc-1", "name": "Alpha FC", "abbreviation": "ALP"},
            {"optic_id": "abc-2", "name": "Beta United", "abbreviation": ""},
        ],
    )
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["suggestions"][0]["payload"]["aliases"][0]["alias_kind"] == "external_id"
    assert out["entity_type"] == "team"
    keys = {s["payload"]["canonical_key"] for s in out["suggestions"]}
    assert "ALP" in keys


def test_build_alias_suggestions_tennis_is_team() -> None:
    out = build_alias_suggestions(
        league="itf_women",
        sport="tennis",
        competitors=[
            {"optic_id": "OID1OID1OID1OID1", "name": "Teodora Vlajic", "abbreviation": ""},
        ],
    )
    assert out["entity_type"] == "team"
    assert out["suggestions"][0]["payload"]["entity_type"] == "team"


def test_filter_existing_aliases_skips_tip_ids():
    built = build_alias_suggestions(
        league="demo_lg",
        sport="soccer",
        competitors=[
            {"optic_id": "abc-1", "name": "Alpha FC", "abbreviation": "ALP"},
            {"optic_id": "abc-2", "name": "Beta United", "abbreviation": "BET"},
        ],
    )
    kept, skipped = filter_existing_aliases(
        built["suggestions"],
        existing_optic_ids={"abc-1"},
    )
    assert skipped == 1
    assert len(kept) == 1
    assert kept[0]["id"] == "optic|abc-2"


def test_filter_existing_market_suggestions_skips_tip_rules():
    out = suggest_market_rules(
        league="atp_copy",
        optic_league_id="atp",
        sport="tennis",
        sportsbooks=["optic"],
    )
    sample = out["suggestions"][0]
    rules = [
        MarketRuleRow(
            rule_id="mr-optic-ml",
            league="atp_copy",
            sportsbook="optic",
            rule_kind="taxonomy",
            source_key_type=str(sample["pin"]["source_key_type"]),
            source_key=str(sample["pin"]["source_key"]),
            action="map",
            canonical_market_type=str(sample["pin"]["canonical_market_type"]),
            priority=100,
            enabled=True,
            confidence="manual",
        )
    ]
    kept, skipped = filter_existing_market_suggestions(
        out["suggestions"],
        rules,
        league="atp_copy",
    )
    assert skipped == 1
    assert len(kept) == len(out["suggestions"]) - 1
    assert sample["id"] not in {item["id"] for item in kept}


def test_suggest_market_rules_filters_tip_rules():
    store = _seed_with_league()
    out = suggest_market_rules(
        league="atp",
        optic_league_id="atp",
        sport="tennis",
        sportsbooks=["optic"],
        store=store,
    )
    assert out["ok"] is True
    sample = out["suggestions"][0]
    store.seed_rule_set(
        rule_set_id="S1_rules",
        entities=[],
        leagues=store.leagues_for("S0_test_baseline"),
        market_rules=[
            MarketRuleRow(
                rule_id="mr-optic-ml",
                league="atp",
                sportsbook="optic",
                rule_kind="taxonomy",
                source_key_type=str(sample["pin"]["source_key_type"]),
                source_key=str(sample["pin"]["source_key"]),
                action="map",
                canonical_market_type=str(sample["pin"]["canonical_market_type"]),
                priority=100,
                enabled=True,
                confidence="manual",
            )
        ],
        activate=True,
    )
    filtered = suggest_market_rules(
        league="atp",
        optic_league_id="atp",
        sport="tennis",
        sportsbooks=["optic"],
        store=store,
    )
    assert filtered["ok"] is True
    assert len(filtered["suggestions"]) == len(out["suggestions"]) - 1
    assert any("Skipped 1 market rule" in w for w in filtered["warnings"])


def test_suggest_aliases_from_optic_filters_tip():
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_alias",
        entities=[
            EntityRow(
                league="demo_lg",
                entity_type="team",
                canonical_key="ALP",
                canonical_name="Alpha FC",
                aliases=[
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": "abc-1",
                    }
                ],
            )
        ],
        leagues=[
            LeagueRow(
                league="demo_lg",
                sport="soccer",
                optic_league_id="demo-optic",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            )
        ],
        activate=True,
    )
    fixtures = [
        {
            "home_competitors": [
                {"id": "abc-1", "name": "Alpha FC", "abbreviation": "ALP"},
                {"id": "abc-2", "name": "Beta United", "abbreviation": "BET"},
            ],
            "away_competitors": [],
        }
    ]
    out = suggest_aliases_from_optic(
        league="demo_lg",
        sport="soccer",
        optic_league_id="demo-optic",
        fixtures=fixtures,
        store=store,
    )
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["suggestions"][0]["id"] == "optic|abc-2"
    assert any("Skipped 1 alias" in w for w in out["warnings"])


def test_dockerfile_includes_optic_spine():
    dockerfile = Path("deploy/Dockerfile").read_text(encoding="utf-8")
    assert "optic_spine.csv" in dockerfile


def test_dockerignore_allows_optic_spine():
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")
    assert "!docs/mapping-rules/optic_spine.csv" in dockerignore
