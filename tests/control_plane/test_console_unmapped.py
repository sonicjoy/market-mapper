"""Console unmapped inventory enrichment (no BQ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from mappers.control_plane.console_unmapped import (
    build_unmapped_tip_index,
    enrich_unmapped_row,
    list_unmapped_legs,
)
from mappers.control_plane.console_unmapped_fixes import (
    has_fixable_items,
    stage_unmapped_cart,
    summarize_mappable_items,
    why_unmapped_leg,
)
from mappers.control_plane.console_unmapped_markets import market_observation
from mappers.control_plane.console_unmapped_why_api import (
    stage_unmapped_console_leg,
    why_unmapped_console_leg,
)
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_unmapped",
        entities=[],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp-optic",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {
                        "sportsbook": "polymarket",
                        "enabled": True,
                        "settings": {"slug_prefix": "atp"},
                    },
                ],
            )
        ],
        market_rules=[],
        activate=True,
    )
    return store


def test_enrich_kalshi_kickoff_is_typed_never_read_off_the_ticker() -> None:
    """A Kalshi leg's kickoff is the milestone start the query joins in."""
    store = _store()
    index = build_unmapped_tip_index(store)
    row = enrich_unmapped_row(
        {"platform": "kalshi", "key": "KXATPMATCH-26SEP05SINNER", "demand": 3,
         "start_at": "2026-09-05T13:00:00Z"},
        index,
    )
    assert row["league"] is None
    assert row["sport"] is None
    assert row["start_date"].startswith("2026-09-05T13:00")
    assert row["ttko_hours"] is not None
    assert row["fixture"] == "KXATPMATCH-26SEP05SINNER"
    bare = enrich_unmapped_row(
        {"platform": "kalshi", "key": "KXATPMATCH-26SEP05SINNER", "demand": 3}, index)
    assert bare["start_date"] is None and bare["kickoff_day"] is None


def test_enrich_poly_bridge_kickoff_and_slug() -> None:
    store = _store()
    index = build_unmapped_tip_index(store)
    row = enrich_unmapped_row(
        {
            "platform": "polymarket",
            "key": "pos1",
            "slug": "atp-sinner-vs-alcaraz",
            "fixture": "Sinner vs Alcaraz",
            "start_at": "2026-09-05T14:30:00Z",
            "demand": 1,
        },
        index,
    )
    assert row["league"] == "atp"
    assert row["sport"] == "tennis"
    assert row["start_date"] == "2026-09-05T14:30:00+00:00"
    assert "slug" not in row


def test_enrich_crypto_sport_and_yymmdd() -> None:
    row = enrich_unmapped_row(
        {"platform": "crypto", "key": "NX.F.OPT.TENNIS-1-260905", "demand": 2},
        {"kalshi": [], "poly": {}},
    )
    assert row["sport"] == "tennis"
    assert row["start_date"] is not None
    assert row["start_date"].startswith("2026-09-05")


def test_list_unmapped_filters_sport_and_search() -> None:
    store = _store()
    today = datetime.now(UTC).strftime("%y%m%d")

    def query_fn(_params: dict) -> list[dict]:
        return [
            {"platform": "crypto", "key": f"NX.F.OPT.TENNIS-1-{today}", "demand": 9},
            {
                "platform": "polymarket",
                "key": "pos-juve",
                "slug": "epl-juve",
                "fixture": "Will Juventus FC win on 2026-09-02?",
                "platform_leg_description": "Will Juventus FC win on 2026-09-02? — No",
                "start_at": "2099-09-02T18:00:00Z",
                "demand": 4,
            },
        ]

    view = list_unmapped_legs(store=store, sport="tennis", phase="live", query_fn=query_fn)
    assert view["count"] == 1
    assert view["rows"][0]["key"] == f"NX.F.OPT.TENNIS-1-{today}"

    searched = list_unmapped_legs(store=store, q="juventus", phase="pre", query_fn=query_fn)
    assert searched["count"] == 1
    assert searched["rows"][0]["platform"] == "polymarket"


def test_list_unmapped_pre_tab_sorts_by_start() -> None:
    store = _store()

    def query_fn(_params: dict) -> list[dict]:
        return [
            {
                "platform": "polymarket",
                "key": "pos-late",
                "fixture": "Late match",
                "start_at": "2099-06-02T12:00:00Z",
                "demand": 1,
            },
            {
                "platform": "polymarket",
                "key": "pos-soon",
                "fixture": "Soon match",
                "start_at": "2099-06-01T12:00:00Z",
                "demand": 99,
            },
            {
                "platform": "polymarket",
                "key": "pos-old",
                "fixture": "Started match",
                "start_at": "2020-01-01T12:00:00Z",
                "demand": 50,
            },
        ]

    view = list_unmapped_legs(store=store, phase="pre", query_fn=query_fn)
    assert view["count"] == 2
    assert [row["key"] for row in view["rows"]] == ["pos-soon", "pos-late"]


def test_list_unmapped_live_tab_keeps_in_play() -> None:
    store = _store()
    started = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)

    def query_fn(_params: dict) -> list[dict]:
        return [
            {
                "platform": "polymarket",
                "key": "pos-live",
                "fixture": "Live match",
                "start_at": started.isoformat().replace("+00:00", "Z"),
                "demand": 3,
            },
            {
                "platform": "polymarket",
                "key": "pos-soon",
                "fixture": "Soon match",
                "start_at": "2099-06-01T12:00:00Z",
                "demand": 99,
            },
        ]

    view = list_unmapped_legs(store=store, phase="live", query_fn=query_fn)
    assert view["count"] == 1
    assert view["rows"][0]["key"] == "pos-live"


def test_list_unmapped_keeps_same_day_kalshi_and_crypto() -> None:
    store = _store()
    now = datetime.now(UTC)
    crypto_day = now.strftime("%y%m%d")
    started = (now - timedelta(minutes=30)).isoformat()

    def query_fn(_params: dict) -> list[dict]:
        return [
            {"platform": "kalshi", "key": "K-LIVE", "demand": 4, "start_at": started},
            {"platform": "crypto", "key": f"NX.F.OPT.ATP-1-{crypto_day}", "demand": 3},
            {"platform": "kalshi", "key": "K-OLD", "demand": 9,
             "start_at": "2020-01-01T12:00:00Z"},
        ]

    live = list_unmapped_legs(store=store, phase="live", query_fn=query_fn)
    live_keys = [row["key"] for row in live["rows"]]
    assert "K-LIVE" in live_keys
    assert f"NX.F.OPT.ATP-1-{crypto_day}" in live_keys
    assert "K-OLD" not in live_keys

    future = (now + timedelta(days=2)).isoformat()
    future_crypto = (now + timedelta(days=2)).strftime("%y%m%d")

    def future_query_fn(_params: dict) -> list[dict]:
        return [
            {"platform": "kalshi", "key": "K-PRE", "demand": 4, "start_at": future},
            {"platform": "crypto", "key": f"NX.F.OPT.ATP-1-{future_crypto}", "demand": 3},
        ]

    pre = list_unmapped_legs(store=store, phase="pre", query_fn=future_query_fn)
    pre_keys = [row["key"] for row in pre["rows"]]
    assert "K-PRE" in pre_keys
    assert f"NX.F.OPT.ATP-1-{future_crypto}" in pre_keys


def test_list_unmapped_omits_mappable_items() -> None:
    store = _store()
    started = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()

    def query_fn(_params: dict) -> list[dict]:
        return [{"platform": "kalshi", "key": "K-LIVE", "demand": 9, "start_at": started}]

    view = list_unmapped_legs(store=store, phase="live", query_fn=query_fn)
    assert view["rows"]
    assert "mappable_items" not in view["rows"][0]
    assert "has_fixes" not in view["rows"][0]


def test_unmapped_poly_team_name_is_cart_fixable_when_league_on_tip() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_poly_cs2",
        entities=[],
        leagues=[
            LeagueRow(
                league="cs2",
                sport="esports",
                optic_league_id="cs2",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {
                        "sportsbook": "polymarket",
                        "enabled": True,
                        "settings": {"slug_prefix": "cs2"},
                    }
                ],
            )
        ],
        market_rules=[],
        activate=True,
    )
    row = {
        "platform": "polymarket",
        "key": "533",
        "league": "cs2",
        "league_label": "Cs2",
        "platform_leg_description": ("Counter-Strike: BIG vs Nemiga - Map 1 Winner — BIG"),
        "demand": 1,
    }
    out = why_unmapped_leg(row, store)
    alias = next(item for item in out["mappable_items"] if item["kind"] == "alias" and item["label"] == "BIG")
    assert alias["fixable"]
    assert out["has_fixes"]
    assert any(reason["code"] == "missing_tip_fix" for reason in out["reasons"])
    assert not any(reason["code"] == "poly_needs_optic" for reason in out["reasons"])
    staged = stage_unmapped_cart(row, store, [alias["id"]])
    assert staged["ok"]
    pin = staged["cart_items"][0]
    assert pin["kind"] == "entity_alias"
    assert pin["payload"]["aliases"][0]["alias_kind"] == "name"
    assert pin["payload"]["aliases"][0]["alias_value"] == "BIG"


def test_poly_vs_title_does_not_glue_market_onto_team() -> None:
    store = _store()
    desc = "US Sassuolo Calcio vs Frosinone Calcio: Both Teams to Score in Second Half — No"
    row = {
        "platform": "polymarket",
        "key": "pos-btts",
        "league": "atp",
        "league_label": "ATP",
        "platform_leg_description": desc,
        "fixture": ("US Sassuolo Calcio vs Frosinone Calcio: Both Teams to Score in Second Half"),
        "demand": 4,
    }
    out = why_unmapped_leg(row, store)
    labels = [item["label"] for item in out["mappable_items"] if item["kind"] == "alias"]
    assert labels == ["US Sassuolo Calcio", "Frosinone Calcio"]
    assert any(reason["code"] == "yes_only_no" for reason in out["reasons"])


def test_unmapped_poly_totals_outcome_is_not_an_alias() -> None:
    store = _store()
    desc = "Athletics vs. Texas Rangers: O/U 11.5 — Over 11.5"
    row = {
        "platform": "polymarket",
        "key": "pos-ou",
        "league": "mlb",
        "league_label": "MLB",
        "platform_leg_description": desc,
        "fixture": "Athletics vs. Texas Rangers: O/U 11.5",
        "demand": 2,
    }
    out = why_unmapped_leg(row, store)
    labels = [item["label"] for item in out["mappable_items"] if item["kind"] == "alias"]
    assert "Over 11.5" not in labels
    assert "Under 11.5" not in labels
    assert labels == ["Athletics", "Texas Rangers"]


def test_unmapped_poly_first_to_score_is_not_an_alias() -> None:
    store = _store()
    desc = "Austin FC to score first vs. Seattle Sounders FC? — Yes"
    row = {
        "platform": "polymarket",
        "key": "pos-fts",
        "league": "mls",
        "league_label": "MLS",
        "platform_leg_description": desc,
        "fixture": "Austin FC to score first vs. Seattle Sounders FC?",
        "demand": 2,
    }
    out = why_unmapped_leg(row, store)
    labels = [item["label"] for item in out["mappable_items"] if item["kind"] == "alias"]
    assert all("to score" not in label.casefold() for label in labels)


def test_stage_poly_alias_uses_inventory_description() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_poly_stage",
        entities=[],
        leagues=[
            LeagueRow(
                league="cs2",
                sport="esports",
                optic_league_id="cs2",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {
                        "sportsbook": "polymarket",
                        "enabled": True,
                        "settings": {"slug_prefix": "cs2"},
                    }
                ],
            )
        ],
        market_rules=[],
        activate=True,
    )
    desc = "Counter-Strike: Rare Atom vs 5star - Map 1 Winner — Rare Atom"
    why = why_unmapped_console_leg(
        store,
        "polymarket",
        "533",
        description=desc,
        league="cs2",
    )
    alias = next(item for item in why["mappable_items"] if item["kind"] == "alias" and item["label"] == "Rare Atom")
    missed = stage_unmapped_console_leg(store, "polymarket", "533", [alias["id"]])
    assert not missed["ok"]
    staged = stage_unmapped_console_leg(
        store,
        "polymarket",
        "533",
        [alias["id"]],
        description=desc,
        league="cs2",
    )
    assert staged["ok"]
    assert staged["cart_items"][0]["payload"]["aliases"][0]["alias_value"] == "Rare Atom"


def test_unmapped_why_endpoint() -> None:
    store = _store()
    row = {
        "platform": "polymarket",
        "key": "pos-juve",
        "league": "epl",
        "league_label": "EPL",
        "platform_leg_description": "Will Juventus FC win on 2026-09-02? — No",
        "demand": 4,
    }
    out = why_unmapped_leg(row, store)
    assert out["mappable_items"]
    assert all(not item.get("fixable") for item in out["mappable_items"] if item["kind"] == "alias")
    assert any(item["kind"] == "alias" and "Juventus" in item["label"] for item in out["mappable_items"])
    assert any(reason["code"] == "yes_only_no" for reason in out["reasons"])


def test_unmapped_kalshi_game_no_is_not_poly_yes_only_no() -> None:
    store = _store()
    row = {
        "platform": "kalshi",
        "key": "KXNFLGAME-26SEP14DENKC-KC",
        "league": "nfl",
        "league_label": "NFL",
        "platform_leg_description": "Kansas City Chiefs vs Denver Broncos — Chiefs No",
        "demand": 3,
    }
    out = why_unmapped_leg(row, store)
    assert not any(reason["code"] == "yes_only_no" for reason in out["reasons"])


def test_unmapped_why_exact_score_no_is_residual() -> None:
    store = _store()
    desc = "Exact Score: Yunnan Yukun 0 - 3 Chongqing Tonglianglong FC? — No"
    row = {
        "platform": "polymarket",
        "key": "492",
        "league": "china_fa_cup",
        "league_label": "China Fa Cup",
        "platform_leg_description": desc,
        "fixture": "Exact Score: Yunnan Yukun 0 - 3 Chongqing Tonglianglong FC?",
        "sport": "soccer",
        "demand": 4,
    }
    out = why_unmapped_leg(row, store)
    codes = [reason["code"] for reason in out["reasons"]]
    assert "exact_score" in codes
    assert "league_not_on_tip" in codes
    assert not out["has_fixes"]
    assert all("optic fixture" not in reason["text"].casefold() for reason in out["reasons"])
    assert not any(item["kind"] == "alias" and str(item["label"]).casefold() == "no" for item in out["mappable_items"])
    via_http = why_unmapped_console_leg(
        store,
        "polymarket",
        "492",
        description=desc,
        league="china_fa_cup",
        fixture=row["fixture"],
        sport="soccer",
    )
    assert any(reason["code"] == "exact_score" for reason in via_http["reasons"])


def _odds_fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [{"id": "fx", "odds": [{"market_id": "moneyline"}]}]


def test_kalshi_leg_offers_no_alias_or_market_rule_badge() -> None:
    """Kalshi maps from its own typed fields: Why never stages a tip pin for it."""
    row = {
        "platform": "kalshi",
        "key": "KXATPMATCH-26SEP05SINALK",
        "market_ticker": "KXATPMATCH-26SEP05SINALK",
        "league": "atp",
        "league_label": "ATP",
        "demand": 3,
    }
    items = summarize_mappable_items(row, _store())
    assert [item["kind"] for item in items] == ["league"]
    assert not has_fixable_items(items)


def test_crypto_market_observation_uses_prop_source_key_types() -> None:
    store = _store()
    team = market_observation(
        {"contract_type": "Total Points", "market_group": "Team Prop", "key": "x"},
        store,
        "atp",
        "crypto.com",
    )
    assert team is not None
    assert team.get("source_key_type") == "team_prop_contract_type"
    game = market_observation(
        {
            "contract_type": "Both Teams To Score",
            "market_group": "Game Prop",
            "key": "y",
        },
        store,
        "atp",
        "crypto.com",
    )
    assert game is not None
    assert game.get("source_key_type") == "game_prop_contract_type"
    player = market_observation(
        {"contract_type": "Anytime Goal Scorer", "market_group": "Player Prop", "key": "z"},
        store,
        "atp",
        "crypto.com",
    )
    assert player is not None
    assert player.get("source_key_type") == "player_prop_contract_type"


def test_why_crypto_game_line_fixable(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.gap_market_bind.cached_optic_fixtures",
        _odds_fixtures,
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_crypto_gl",
        entities=[],
        leagues=[
            LeagueRow(
                league="nfl",
                sport="football",
                optic_league_id="nfl",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "NFL",
                        "settings": {
                            "league": "NFL",
                            "sport_grouping": "NFL",
                            "period_type": "Full Game",
                        },
                    },
                ],
            ),
        ],
        activate=True,
    )
    row = {
        "platform": "crypto",
        "key": "NX.F.OPT.NFL-1",
        "league": "nfl",
        "contract_type": "Moneyline",
        "market_group": "Game Line",
        "demand": 2,
    }
    items = summarize_mappable_items(row, store)
    rules = [item for item in items if item["kind"] == "market_rule"]
    assert len(rules) == 1
    assert rules[0]["fixable"]


def test_why_crypto_prop_not_fixable(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.gap_market_bind.cached_optic_fixtures",
        _odds_fixtures,
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_crypto_prop",
        entities=[],
        leagues=[
            LeagueRow(
                league="nfl",
                sport="football",
                optic_league_id="nfl",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "NFL",
                        "settings": {
                            "league": "NFL",
                            "sport_grouping": "NFL",
                            "period_type": "Full Game",
                        },
                    },
                ],
            ),
        ],
        activate=True,
    )
    row = {
        "platform": "crypto",
        "key": "NX.F.OPT.NFL-1",
        "league": "nfl",
        "contract_type": "Anytime TD",
        "market_group": "Player Prop",
        "demand": 2,
    }
    items = summarize_mappable_items(row, store)
    assert not [item for item in items if item["kind"] == "market_rule"]


def test_why_px_name_match_fixable(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.gap_market_bind.cached_optic_fixtures",
        _odds_fixtures,
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_px_mr",
        entities=[],
        leagues=[
            LeagueRow(
                league="nfl",
                sport="football",
                optic_league_id="nfl",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "px",
                        "enabled": True,
                        "parser_profile": "px_generic_v1",
                        "settings": {"tournament_id": "1"},
                    },
                ],
            ),
        ],
        activate=True,
    )
    row = {
        "platform": "prophetx",
        "key": "evt|line",
        "league": "nfl",
        "market_name": "Moneyline",
        "demand": 1,
    }
    items = summarize_mappable_items(row, store)
    rules = [item for item in items if item["kind"] == "market_rule"]
    assert len(rules) == 1
    assert rules[0]["fixable"]


def test_crypto_nx_without_crypto_ids_no_poly_alias_reason() -> None:
    symbol = "NX.F.OPT.CFB-00036-260926-M.O1.195.20270228"
    row = {
        "platform": "crypto",
        "key": symbol,
        "sport": "cfb",
        "league": "",
    }
    out = why_unmapped_leg(row, _store())
    codes = [reason["code"] for reason in out["reasons"]]
    assert "poly_needs_optic" not in codes
    assert "crypto_contract_no_league" in codes
    assert not any(item["kind"] == "alias" for item in out["mappable_items"])
    assert not out["has_fixes"]


def test_poly_unfixable_aliases_still_poly_needs_optic() -> None:
    store = _store()
    row = {
        "platform": "polymarket",
        "key": "pos-unknown",
        "league": "epl",
        "league_label": "EPL",
        "platform_leg_description": "Arsenal FC vs Chelsea FC — Arsenal FC",
        "fixture": "Arsenal FC vs Chelsea FC",
        "demand": 1,
    }
    out = why_unmapped_leg(row, store)
    assert any(reason["code"] == "missing_alias" for reason in out["reasons"])


def test_why_mapping_stack_fixture_alias_market(monkeypatch: Any) -> None:
    kick = datetime.now(UTC) + timedelta(hours=8)

    def _fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "optic-mlb-99",
                "start_date": kick.replace(microsecond=0).isoformat(),
                "home_competitors": [{"name": "Boston Red Sox", "id": "1001"}],
                "away_competitors": [{"name": "New York Yankees", "id": "2002"}],
            }
        ]

    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_crypto_gap.cached_optic_fixtures",
        _fixtures,
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_stack",
        entities=[
            EntityRow(
                league="mlb",
                canonical_key="BOS",
                canonical_name="Boston Red Sox",
                entity_type="team",
                aliases=[
                    {
                        "sportsbook": "crypto.com",
                        "alias_kind": "crypto_id",
                        "alias_value": "1001",
                    }
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league="mlb",
                sport="baseball",
                optic_league_id="mlb-optic",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "settings": {"league": "MLB"},
                    }
                ],
            )
        ],
        market_rules=[],
        activate=True,
    )
    row = {
        "platform": "crypto",
        "key": "NX.F.OPT.MLB-00006-260924-M.O.1.403.20261130",
        "league": "mlb",
        "fixture": "New York Yankees @ Boston Red Sox",
        "start_date": kick.replace(microsecond=0).isoformat(),
        "market_group": "Game Line",
        "contract_type": "Moneyline",
        "crypto_ids": ["1001", "2002"],
        "home_id": "1001",
        "away_id": "2002",
    }
    out = why_unmapped_leg(row, store)
    codes = [reason["code"] for reason in out["reasons"]]
    assert "optic_fixture_present" in codes
    assert "missing_alias" in codes
    assert any(code in codes for code in ("missing_market_rule", "market_rule_present"))


def test_crypto_crypto_ids_and_league_badges() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_crypto_ids",
        entities=[
            EntityRow(
                league="mlb",
                canonical_key="BOS",
                canonical_name="Boston Red Sox",
                entity_type="team",
                aliases=[
                    {
                        "sportsbook": "crypto.com",
                        "alias_kind": "crypto_id",
                        "alias_value": "1001",
                    }
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league="mlb",
                sport="baseball",
                optic_league_id="mlb-optic",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "settings": {"league": "MLB"},
                    }
                ],
            )
        ],
        market_rules=[],
        activate=True,
    )
    row = {
        "platform": "crypto",
        "key": "NX.F.OPT.MLB-00006-260924-M.O.1.403.20261130",
        "league": "mlb",
        "crypto_ids": ["1001", "2002"],
    }
    out = why_unmapped_leg(row, store)
    aliases = [item for item in out["mappable_items"] if item["kind"] == "alias"]
    by_label = {item["label"]: item for item in aliases}
    assert set(by_label) == {"1001", "2002"}
    assert by_label["1001"]["mapped"]
    assert not by_label["2002"]["mapped"]
    assert by_label["2002"]["fixable"]


def test_why_no_optic_market_rule_badge(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.gap_market_bind.cached_optic_fixtures",
        _odds_fixtures,
    )
    store = _store()
    row = {
        "platform": "optic",
        "key": "moneyline",
        "league": "atp",
        "demand": 1,
    }
    items = summarize_mappable_items(row, store)
    assert not [item for item in items if item["kind"] == "market_rule"]
