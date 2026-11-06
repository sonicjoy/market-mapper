"""Underdog fixture CSV harvest kernel."""

from __future__ import annotations

from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.underdog_fixture_classify import (
    _parse_team_ticker,
    harvest_underdog_gaps,
)
from mappers.control_plane.underdog_fixture_harvest import (
    CsvMarketRow,
    harvest_for_store,
    parse_udx_header,
)
from mappers.control_plane.underdog_legacy_ticker import udx_player_code


class _StubStore:
    current_rule_set_id = "rs-test"

    def __init__(
        self,
        *,
        entities: list[EntityRow],
        rules: list[MarketRuleRow],
        leagues: list[LeagueRow],
    ) -> None:
        self._entities = entities
        self._rules = rules
        self._leagues = leagues

    def entities_for(self, _rid: str) -> list[EntityRow]:
        return self._entities

    def market_rules_for(self, _rid: str) -> list[MarketRuleRow]:
        return self._rules

    def leagues_for(self, _rid: str) -> list[LeagueRow]:
        return self._leagues


def _nfl_league(*, underdog: bool = True) -> LeagueRow:
    exchanges = [
        {
            "sportsbook": "optic",
            "enabled": True,
            "parser_profile": "optic_standard_v1",
        },
    ]
    if underdog:
        exchanges.append({
            "sportsbook": "underdog",
            "enabled": True,
            "parser_profile": "underdog_generic_v1",
            "source_league_id": "NFL",
            "settings": {"league": "NFL"},
        })
    return LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={},
        exchanges=exchanges,
    )


def _atp_league() -> LeagueRow:
    return LeagueRow(
        league="atp_challenger",
        sport="tennis",
        optic_league_id="atp_challenger",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        settings={"entity_type": "player"},
        exchanges=[
            {
                "sportsbook": "underdog",
                "enabled": True,
                "parser_profile": "underdog_generic_v1",
                "source_league_id": "ATPCHL",
                "settings": {"league": "ATPCHL"},
            },
        ],
    )


def test_parse_udx_header_tennis() -> None:
    parsed = parse_udx_header(
        "UDXATPCHLMATCHWIN_ABOANG26SEP241700_JANGELO",
    )
    assert parsed is not None
    assert parsed.venue == "ATPCHL"
    assert parsed.product == "MATCHWIN"
    assert parsed.selection == "JANGELO"


def test_team_parse_needs_catalogue_codes() -> None:
    """UFC BARJR + RJR would split BA/RJR; without team codes there is no split to trust."""
    catalog = {"nfl": {"BAL": "Baltimore Ravens", "DAL": "Dallas Cowboys"}}
    assert _parse_team_ticker("UDXUFCFIGHTWIN_BARJR26SEP262120_RJR", "ufc", catalog) is None
    nfl = _parse_team_ticker("UDXNFLGAMEWIN_BALDAL26SEP271625_BAL", "nfl", catalog)
    assert nfl is not None
    assert (nfl.away, nfl.home) == ("BAL", "DAL")


def test_udx_player_code_truncation() -> None:
    assert udx_player_code("Jaime Faria") == "JFARIA"
    assert udx_player_code("Jan Angelo") == "JANGELO"


def test_harvest_team_alias_already_pinned() -> None:
    entity = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="ARI",
        canonical_name="Arizona Cardinals",
        aliases=[
            {
                "sportsbook": "underdog",
                "alias_kind": "code",
                "alias_value": "ARI",
            },
        ],
    )
    store = _StubStore(
        entities=[entity],
        rules=[],
        leagues=[_nfl_league()],
    )
    csv_rows = [
        CsvMarketRow(
            ticker="UDXNFLGAMEWIN_ARINYG26OCT041300_ARI",
            fixture_id="fx1",
        ),
    ]
    fixtures = {
        "fx1": {
            "fixture_id": "fx1",
            "home": "New York Giants",
            "away": "Arizona Cardinals",
        },
    }
    report = harvest_for_store(
        store,
        csv_rows,
        environment="test",
        fixtures_by_id=fixtures,
    )
    assert len(report.aliases) == 1
    assert report.aliases[0].status == "already_pinned"


def test_harvest_team_alias_uses_fixture_display_name() -> None:
    entity = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="optic-ari",
        canonical_name="Arizona Cardinals",
        aliases=[],
    )
    store = _StubStore(entities=[entity], rules=[], leagues=[_nfl_league()])
    report = harvest_for_store(
        store,
        [CsvMarketRow(ticker="UDXNFLGAMEWIN_ARINYG26OCT041300_ARI", fixture_id="fx1")],
        environment="test",
        fixtures_by_id={"fx1": {"home": "New York Giants", "away": "Arizona Cardinals"}},
    )
    assert report.aliases[0].status == "propose"
    assert report.aliases[0].canonical_key == "optic-ari"


def test_gap_proposer_drafts_underdog_with_empty_inventory() -> None:
    entity = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="KC",
        canonical_name="Kansas City Chiefs",
        aliases=[],
    )
    store = _StubStore(
        entities=[entity],
        rules=[],
        leagues=[_nfl_league(underdog=False)],
    )
    pins: list[dict] = []
    skipped: list[dict] = []
    harvest_underdog_gaps(store, pins, skipped, set())
    kinds = {str(pin.get("kind")) for pin in pins}
    assert "mapping_league" in kinds
    assert "mapping_market_rules" in kinds
    assert "entity_alias" in kinds


def test_wrong_owner_is_not_already_pinned() -> None:
    wrong = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="NYG",
        canonical_name="New York Giants",
        aliases=[{
            "sportsbook": "underdog",
            "alias_kind": "code",
            "alias_value": "ARI",
        }],
    )
    right = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="optic-ari",
        canonical_name="Arizona Cardinals",
        aliases=[],
    )
    store = _StubStore(entities=[wrong, right], rules=[], leagues=[_nfl_league()])
    report = harvest_for_store(
        store,
        [CsvMarketRow(ticker="UDXNFLGAMEWIN_ARINYG26OCT041300_ARI", fixture_id="fx1")],
        environment="test",
        fixtures_by_id={"fx1": {"home": "New York Giants", "away": "Arizona Cardinals"}},
    )
    assert report.aliases[0].status == "skip"
    assert report.aliases[0].reason == "code owned elsewhere"
    assert report.aliases[0].canonical_key == ""


def test_harvest_team_alias_missing_pin() -> None:
    entity = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="ARI",
        canonical_name="Arizona Cardinals",
        aliases=[],
    )
    store = _StubStore(
        entities=[entity],
        rules=[],
        leagues=[_nfl_league()],
    )
    report = harvest_for_store(
        store,
        [
            CsvMarketRow(
                ticker="UDXNFLGAMEWIN_ARINYG26OCT041300_ARI",
                fixture_id="fx1",
            ),
        ],
        environment="test",
        fixtures_by_id={
            "fx1": {"home": "New York Giants", "away": "Arizona Cardinals"},
        },
    )
    assert report.aliases[0].status == "propose"
    assert report.aliases[0].code == "ARI"


def test_harvest_reversed_blob_pins_code_on_named_team() -> None:
    """NYGARI lists the Giants first while Optic has them home: NYG is still the Giants."""
    ari = EntityRow(
        league="nfl", entity_type="team", canonical_key="ARI",
        canonical_name="Arizona Cardinals", aliases=[],
    )
    nyg = EntityRow(
        league="nfl", entity_type="team", canonical_key="NYG",
        canonical_name="New York Giants", aliases=[],
    )
    store = _StubStore(entities=[ari, nyg], rules=[], leagues=[_nfl_league()])
    report = harvest_for_store(
        store,
        [CsvMarketRow(ticker="UDXNFLGAMEWIN_NYGARI26OCT041300_NYG", fixture_id="fx1")],
        environment="test",
        fixtures_by_id={"fx1": {"home": "New York Giants", "away": "Arizona Cardinals"}},
    )
    assert [(a.code, a.status, a.canonical_key) for a in report.aliases] == [
        ("NYG", "propose", "NYG"),
    ]


def test_harvest_player_alias_missing_pin() -> None:
    entity = EntityRow(
        league="atp_challenger",
        entity_type="team",
        canonical_key="jan-angelo",
        canonical_name="Jan Angelo",
        aliases=[],
    )
    store = _StubStore(
        entities=[entity],
        rules=[],
        leagues=[_atp_league()],
    )
    report = harvest_for_store(
        store,
        [
            CsvMarketRow(
                ticker="UDXATPCHLMATCHWIN_ABOANG26SEP241700_JANGELO",
                fixture_id="fx-tennis",
            ),
        ],
        environment="test",
        fixtures_by_id={
            "fx-tennis": {"home": "Jan Angelo", "away": "Victor Aboian"},
        },
    )
    assert report.aliases[0].status == "propose"
    assert report.aliases[0].code == "JANGELO"
    assert report.aliases[0].entity_type == "team"


def test_harvest_player_alias_ambiguous_skip() -> None:
    entities = [
        EntityRow(
            league="atp_challenger",
            entity_type="team",
            canonical_key="jan-angelo",
            canonical_name="Jan Angelo",
            aliases=[],
        ),
        EntityRow(
            league="atp_challenger",
            entity_type="team",
            canonical_key="joe-angelo",
            canonical_name="Joe Angelo",
            aliases=[],
        ),
    ]
    store = _StubStore(entities=entities, rules=[], leagues=[_atp_league()])
    report = harvest_for_store(
        store,
        [
            CsvMarketRow(
                ticker="UDXATPCHLMATCHWIN_ABOANG26SEP241700_JANGELO",
                fixture_id="fx-tennis",
            ),
        ],
        environment="test",
        fixtures_by_id={
            "fx-tennis": {"home": "Jan Angelo", "away": "Joe Angelo"},
        },
    )
    assert report.aliases[0].status == "skip"
    assert report.aliases[0].reason == "unresolvable entity"


def test_harvest_market_rule_propose_vs_ruled() -> None:
    ruled = MarketRuleRow(
        rule_id="r1",
        league="nfl",
        sportsbook="underdog",
        rule_kind="taxonomy",
        source_key_type="product_period",
        source_key="GAMEWIN",
        action="map",
        canonical_market_type="moneyline",
        priority=100,
        enabled=True,
        confidence="manual",
    )
    store = _StubStore(entities=[], rules=[ruled], leagues=[_nfl_league()])
    report = harvest_for_store(
        store,
        [
            CsvMarketRow(
                ticker="UDXNFLGAMEWIN_ARINYG26OCT041300_ARI",
                fixture_id="fx1",
            ),
            CsvMarketRow(
                ticker="UDXNFLSPREAD_ARINYG26OCT041300_NYG2.5",
                fixture_id="fx1",
            ),
        ],
        environment="test",
        fixtures_by_id={"fx1": {"home": "Giants", "away": "Cardinals"}},
    )
    by_key = {item.source_key: item.status for item in report.market_rules}
    assert by_key["GAMEWIN"] == "already_ruled"
    assert by_key["SPREAD"] == "propose"
