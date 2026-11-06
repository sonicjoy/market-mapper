"""Unit tests for review-detail snapshot change groups."""

from __future__ import annotations

from mappers.control_plane.change_view import (
    change_headline,
    headline_from_mapping_rows,
    payload_change_groups,
    refresh_alias_lines,
    snapshot_change_groups,
    totals_from_groups,
)
from mappers.control_plane.cow_diff import snapshot_change_counts
from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ExchangePin,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow


def _league(name: str) -> LeagueRow:
    return LeagueRow(
        league=name,
        sport="soccer",
        optic_league_id=name,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96,
        enabled=True,
        output_order=[],
        exchanges=[],
    )


def _rule(league: str, source_key: str, *, action: str = "map", canonical: str | None = "moneyline") -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"{league}-{source_key}",
        league=league,
        sportsbook="kalshi",
        rule_kind="taxonomy",
        source_key_type="ticker_type",
        source_key=source_key,
        action=action,
        canonical_market_type=canonical,
        priority=100,
        enabled=True,
        confidence="manual",
    )


def test_snapshot_change_counts_include_leagues_and_rules() -> None:
    parent_lg = [_league("lol")]
    child_lg = [_league("lol"), _league("demo_a"), _league("demo_b")]
    child_mr = [_rule("demo_a", "KXDEMOA-ML")]
    counts = snapshot_change_counts([], [], parent_lg, child_lg, [], child_mr)
    assert counts == {"added_count": 3, "removed_count": 0, "modified_count": 0}


def test_snapshot_change_groups_lines_for_league_batch() -> None:
    parent_ent = [
        EntityRow("lol", "team", "T1", "T1", [], enabled=True),
    ]
    child_ent = parent_ent
    parent_lg = [_league("lol")]
    child_lg = [_league("lol"), _league("demo_a")]
    child_mr = [_rule("demo_a", "KXDEMOA-ML")]
    groups = snapshot_change_groups(parent_ent, child_ent, parent_lg, child_lg, [], child_mr)
    assert groups["aliases"]["added_count"] == 0
    assert groups["leagues"]["lines"] == ["+ Demo A (demo_a)"]
    assert groups["market_rules"]["added_count"] == 1
    assert "KXDEMOA-ML" in groups["market_rules"]["lines"][0]
    assert totals_from_groups(groups)["added_count"] == 2


def test_snapshot_change_groups_market_rule_ignore_to_map() -> None:
    parent = [_rule("la_liga", "1HBTTS", action="ignore", canonical=None)]
    child = [_rule("la_liga", "1HBTTS", action="map", canonical="1h_btts")]
    groups = snapshot_change_groups([], [], [], [], parent, child)
    assert groups["market_rules"]["modified_count"] == 1
    assert groups["market_rules"]["lines"] == [
        "~ Enable Kalshi 1HBTTS on La Liga: ignored → mapped as 1h_btts",
    ]
    assert change_headline(groups) == (
        "Enable 1 ignored market rule so they start mapping."
    )


def test_snapshot_change_groups_league_update_enables_books() -> None:
    parent = [
        LeagueRow(
            league="saudi_pro_league",
            sport="soccer",
            optic_league_id="saudi_arabia_-_saudi_league",
            extra_optic_league_ids=[],
            fixture_source="api",
            fixture_horizon_hours=96,
            enabled=True,
            output_order=[],
            exchanges=[{"sportsbook": "optic", "enabled": True, "parser_profile": "optic_standard_v1"}],
        )
    ]
    child = [
        LeagueRow(
            league="saudi_pro_league",
            sport="soccer",
            optic_league_id="saudi_arabia_-_saudi_league",
            extra_optic_league_ids=[],
            fixture_source="api",
            fixture_horizon_hours=96,
            enabled=True,
            output_order=[],
            exchanges=[
                {"sportsbook": "optic", "enabled": True, "parser_profile": "optic_standard_v1"},
                {
                    "sportsbook": "kalshi",
                    "enabled": True,
                    "parser_profile": "kalshi_generic_v1",
                    "source_league_id": "KXSPL",
                },
            ],
        )
    ]
    groups = snapshot_change_groups([], [], parent, child, [], [])
    assert groups["leagues"]["added_count"] == 0
    assert groups["leagues"]["modified_count"] == 1
    line = groups["leagues"]["lines"][0]
    assert line.startswith("~ Enable Kalshi (KXSPL) on Saudi Pro League")
    assert "Optic already on" in line
    assert change_headline(groups) == "Update 1 league."


def test_snapshot_change_groups_league_prefix_only() -> None:
    parent = [
        LeagueRow(
            league="poland_ekstraklasa",
            sport="soccer",
            optic_league_id="poland_-_ekstraklasa",
            extra_optic_league_ids=[],
            fixture_source="api",
            fixture_horizon_hours=96,
            enabled=True,
            output_order=[],
            exchanges=[
                {
                    "sportsbook": "optic",
                    "enabled": True,
                    "parser_profile": "optic_standard_v1",
                    "source_league_id": "poland_-_ekstraklasa",
                },
                {
                    "sportsbook": "polymarket",
                    "enabled": True,
                    "parser_profile": "poly_generic_v1",
                    "source_league_id": "poland_-_ekstraklasa",
                },
            ],
        )
    ]
    child = [
        LeagueRow(
            league="poland_ekstraklasa",
            sport="soccer",
            optic_league_id="poland_-_ekstraklasa",
            extra_optic_league_ids=[],
            fixture_source="api",
            fixture_horizon_hours=96,
            enabled=True,
            output_order=[],
            exchanges=[
                {
                    "sportsbook": "optic",
                    "enabled": True,
                    "parser_profile": "optic_standard_v1",
                    "source_league_id": "poland_-_ekstraklasa",
                },
                {
                    "sportsbook": "polymarket",
                    "enabled": True,
                    "parser_profile": "poly_generic_v1",
                    "source_league_id": "poland_-_ekstraklasa",
                    "settings": {"slug_prefix": "pol"},
                },
            ],
        )
    ]
    groups = snapshot_change_groups([], [], parent, child, [], [])
    line = groups["leagues"]["lines"][0]
    assert "prefix pol" in line
    assert line.startswith("~ change Polymarket")
    assert "Update Poland" not in line
    assert "Optic already on" in line
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="la_liga",
                canonical_key="VAL",
                canonical_name="Valencia",
                aliases=[
                    AliasPin(
                        sportsbook="optic",
                        alias_kind="external_id",
                        alias_value="oid-val",
                    )
                ],
            )
        ],
        leagues=[
            MappingLeaguePayload(
                league="demo_a",
                sport="soccer",
                optic_league_id="demo-a",
                exchanges=[],
            )
        ],
        market_rules=[
            MappingMarketRulesPayload(
                league="demo_a",
                rules=[
                    MarketRulePin(
                        sportsbook="kalshi",
                        rule_kind="taxonomy",
                        source_key_type="series_ticker",
                        source_key="KXDEMOA-ML",
                        action="map",
                        canonical_market_type="moneyline",
                    )
                ],
            )
        ],
    )
    groups = payload_change_groups(payload)
    assert groups["aliases"]["added_count"] == 1
    line = groups["aliases"]["lines"][0]
    assert "oid-val" in line
    assert "VAL Valencia" in line
    assert groups["leagues"]["added_count"] == 1
    assert "demo_a" in groups["leagues"]["lines"][0]
    assert groups["market_rules"]["added_count"] == 1
    assert "KXDEMOA-ML" in groups["market_rules"]["lines"][0]


def test_payload_change_groups_update_when_league_on_tip() -> None:
    tip = [_league("lol")]
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="lol",
                sport="esports",
                optic_league_id="league-of-legends",
                exchanges=[
                    ExchangePin(sportsbook="optic", parser_profile="optic_standard_v1"),
                ],
            )
        ],
    )
    groups = payload_change_groups(payload, tip_leagues=tip)
    assert groups["leagues"]["added_count"] == 0
    assert groups["leagues"]["modified_count"] == 1
    assert "Enable Optic" in groups["leagues"]["lines"][0]
    assert change_headline(groups) == "Update 1 league."


def test_alias_line_includes_canonical_key_when_name_differs() -> None:
    child = [
        EntityRow(
            "itf_men",
            "team",
            "MES2",
            "Marko Mesarovic",
            [{"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "936A"}],
            enabled=True,
        )
    ]
    groups = snapshot_change_groups([], child, [], [], [], [])
    assert groups["aliases"]["lines"] == [
        "+ Map Optic 936A (Marko Mesarovic) → MES2 Marko Mesarovic (Itf Men)",
    ]


def test_refresh_alias_lines_uses_payload_canonical_key() -> None:
    stored = {
        "aliases": {
            "added_count": 1,
            "modified_count": 0,
            "removed_count": 0,
            "lines": ["+ Map Optic 936A → Marko Mesarovic (Itf Men)"],
        },
        "leagues": {"added_count": 0, "modified_count": 0, "removed_count": 0, "lines": []},
        "market_rules": {
            "added_count": 0,
            "modified_count": 0,
            "removed_count": 0,
            "lines": [],
        },
    }
    payload = EntityAliasPayload(
        league="itf_men",
        canonical_key="MES2",
        canonical_name="Marko Mesarovic",
        aliases=[
            AliasPin(
                sportsbook="optic",
                alias_kind="external_id",
                alias_value="936A",
            )
        ],
    )
    groups = refresh_alias_lines(stored, payload)
    assert groups["aliases"]["added_count"] == 1
    assert groups["aliases"]["lines"] == [
        "+ Map Optic 936A (Marko Mesarovic) → MES2 Marko Mesarovic (Itf Men)",
    ]


def test_alias_line_names_opaque_source_ids() -> None:
    payload = EntityAliasPayload(
        league="atp",
        canonical_key="UBG9",
        canonical_name="Ugo Blanchet",
        aliases=[
            AliasPin(
                sportsbook="crypto.com",
                alias_kind="external_id",
                alias_value="814825",
            ),
            AliasPin(
                sportsbook="optic",
                alias_kind="external_id",
                alias_value="245B95767109",
            ),
        ],
    )
    groups = payload_change_groups(payload)
    assert groups["aliases"]["lines"] == [
        "+ Map crypto.com 814825, "
        "Optic 245B95767109 (Ugo Blanchet) → UBG9 Ugo Blanchet (Atp)",
    ]


def test_alias_line_names_polymarket_usa_code() -> None:
    payload = EntityAliasPayload(
        league="cs2",
        canonical_key="BAI5",
        canonical_name="BIG Academy",
        aliases=[
            AliasPin(sportsbook="optic", alias_kind="external_id", alias_value="3971145542B7"),
            AliasPin(sportsbook="polymarket_usa", alias_kind="code", alias_value="biga"),
        ],
        evidence_refs=["polymarket_usa:name:BIG Academy"],
    )
    groups = payload_change_groups(payload)
    assert groups["aliases"]["lines"] == [
        "+ Map Optic 3971145542B7 (BIG Academy), "
            "Polymarket US biga (BIG Academy) → BAI5 BIG Academy (Cs2)",
    ]


def test_payload_change_groups_remove_alias() -> None:
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="atp",
                canonical_key="SVA2",
                canonical_name="Trevor Svajda",
                aliases=[
                    AliasPin(
                        sportsbook="kalshi",
                        alias_kind="code",
                        alias_value="SVA",
                        remove=True,
                    )
                ],
            )
        ]
    )
    groups = payload_change_groups(payload)
    assert groups["aliases"]["added_count"] == 0
    assert groups["aliases"]["removed_count"] == 1
    assert groups["aliases"]["lines"] == [
        "- Remove Kalshi SVA from SVA2 Trevor Svajda (Atp)",
    ]
    assert "Remove 1 alias" in change_headline(groups)


def test_headline_from_mapping_rows_matches_card_counts() -> None:
    rows = [
        {"kind": "alias", "action": "add"},
        {"kind": "alias", "action": "add"},
        {"kind": "alias", "action": "add"},
        {"kind": "alias", "action": "update"},
        {"kind": "alias", "action": "update"},
        {"kind": "alias", "action": "update"},
        {"kind": "market_rule", "action": "add"},
        {"kind": "market_rule", "action": "add"},
        {"kind": "market_rule", "action": "add"},
    ]
    assert headline_from_mapping_rows(rows) == (
        "Add 3 aliases; update 3 aliases; add 3 market rules."
    )
