"""Underdog / DKEX / Novig RFQ gaps draft a league when Optic has it and the tip does not."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mappers.control_plane import gap_fix_listed_onboard as onboard
from mappers.control_plane.gap_fix import _merge_harvest_jobs
from mappers.control_plane.gap_fix_listed_onboard import harvest_listed_rfq_onboard
from mappers.control_plane.gap_fix_onboard import try_onboard_league_pin
from mappers.control_plane.gap_fix_walk import ALIASES_COMPLETE, pin_harvest_pairs
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow


def _row(league: str, sport: str, optic: str, exchanges: list[dict[str, Any]]) -> LeagueRow:
    return LeagueRow(
        league=league, sport=sport, optic_league_id=optic, extra_optic_league_ids=[],
        fixture_source="api", fixture_horizon_hours=96.0, enabled=True, output_order=[],
        exchanges=exchanges,
    )


_KALSHI_NFL = {
    "sportsbook": "kalshi", "enabled": True, "parser_profile": "kalshi_generic_v1",
    "source_league_id": "KXNFLGAME", "settings": {},
}


class _Store:
    current_rule_set_id = "tip"

    def __init__(
        self,
        rows: list[LeagueRow],
        entities: list[EntityRow] | None = None,
        rules: list[MarketRuleRow] | None = None,
    ) -> None:
        self.rows = rows
        self.entities = entities or []
        self.rules = rules or []

    def leagues_for(self, _rid: str) -> list[LeagueRow]:
        return self.rows

    def entities_for(self, _rid: str) -> list[EntityRow]:
        return self.entities

    def market_rules_for(self, _rid: str) -> list[MarketRuleRow]:
        return self.rules


def _run(
    book: str,
    items: list[RfqGapItem],
    rows: list[LeagueRow],
    entities: list[EntityRow] | None = None,
    rules: list[MarketRuleRow] | None = None,
) -> tuple[list[Any], list[Any]]:
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    harvest_listed_rfq_onboard(_Store(rows, entities, rules), book, items, pins, skipped, rows)
    return pins, skipped


@pytest.fixture(autouse=True)
def _onboard_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PIPELINE_GAP_ONBOARD", "1")


def test_underdog_nfl_gap_enables_underdog_on_the_nfl_row() -> None:
    nfl = _row("nfl", "football", "nfl", [_KALSHI_NFL])
    items = [
        RfqGapItem("underdog", "UDXNFLGAMEWIN_BUFMIA26SEP281300_BUF", 9),
        RfqGapItem("underdog", "UDXNFLGAMEWIN_KCLV26SEP281300_KC", 4),
    ]
    pins, skipped = _run("underdog", items, [nfl])
    assert len(pins) == 1
    pin = pins[0]
    assert pin["kind"] == "mapping_league" and pin["league"] == "nfl"
    underdog = next(ex for ex in pin["exchanges"] if ex["sportsbook"] == "underdog")
    assert underdog["source_league_id"] == "NFL"
    assert underdog["settings"]["league"] == "NFL"
    assert any(ex["sportsbook"] == "kalshi" for ex in pin["exchanges"])
    assert pin["harvest_key"] == items[0].key
    assert skipped == [{"book": "underdog", "key": items[1].key, "reason": "needs_code"}]


def test_underdog_already_wired_needs_a_tip_owner_for_a_catalog_code() -> None:
    nfl = _row("nfl", "football", "nfl", [
        _KALSHI_NFL,
        {"sportsbook": "underdog", "enabled": True, "source_league_id": "NFL"},
    ])
    key = "UDXNFLGAMEWIN_BUFMIA26SEP281300_BUF"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 9)], [nfl])
    assert pins == []
    assert skipped == [{"book": "underdog", "key": key, "reason": "needs_code"}]


def test_underdog_catalog_code_pins_the_tip_entity() -> None:
    nfl = _row("nfl", "football", "nfl", [
        _KALSHI_NFL,
        {"sportsbook": "underdog", "enabled": True, "source_league_id": "NFL"},
    ])
    bills = EntityRow(
        league="nfl", entity_type="team", canonical_key="buf",
        canonical_name="Buffalo Bills", aliases=[],
    )
    key = "UDXNFLGAMEWIN_BUFMIA26SEP281300_BUF"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 9)], [nfl], [bills])
    assert skipped == []
    assert pins[0]["harvest_key"] == key
    assert pins[0]["canonical_key"] == "buf"
    assert pins[0]["aliases"][0]["alias_value"] == "BUF"


def test_underdog_optic_abbreviation_pins_one_side(monkeypatch: pytest.MonkeyPatch) -> None:
    nfl = _row("nfl", "football", "nfl", [
        _KALSHI_NFL,
        {"sportsbook": "underdog", "enabled": True, "source_league_id": "NFL"},
    ])
    side = EntityRow(
        league="nfl", entity_type="team", canonical_key="oid-zzx",
        canonical_name="Example", aliases=[],
    )
    game = {"home_competitors": [{"abbreviation": "ZZX", "id": "oid-zzx", "name": "Example"}]}
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_underdog_rfq.cached_optic_fixtures",
        lambda _oid: [game],
    )
    key = "UDXNFLGAMEWIN_ZZXMIA26SEP281300_ZZX"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 3)], [nfl], [side])
    assert skipped == []
    assert pins[0]["harvest_key"] == key
    assert pins[0]["canonical_key"] == "oid-zzx"


def test_underdog_total_pins_both_optic_abbreviations(monkeypatch: pytest.MonkeyPatch) -> None:
    nhl = _row("nhl", "hockey", "nhl", [
        {"sportsbook": "underdog", "enabled": True, "source_league_id": "NHL"},
    ])
    fla = EntityRow(
        league="nhl", entity_type="team", canonical_key="oid-fla",
        canonical_name="Florida Panthers", aliases=[],
    )
    car = EntityRow(
        league="nhl", entity_type="team", canonical_key="oid-car",
        canonical_name="Carolina Hurricanes", aliases=[],
    )
    game = {
        "home_competitors": [{"abbreviation": "FLA", "id": "oid-fla", "name": "Florida Panthers"}],
        "away_competitors": [{"abbreviation": "CAR", "id": "oid-car", "name": "Carolina Hurricanes"}],
    }
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_underdog_rfq.cached_optic_fixtures",
        lambda _oid: [game],
    )
    key = "UDXNHLTOTAL_FLACAR26SEP291700_6.5"
    other = "UDXNHLTOTAL_FLACAR26SEP291700_5.5"
    pins, skipped = _run(
        "underdog",
        [RfqGapItem("underdog", key, 8), RfqGapItem("underdog", other, 4)],
        [nhl],
        [fla, car],
    )
    assert skipped == []
    assert {pin["canonical_key"] for pin in pins} == {"oid-fla", "oid-car"}
    covered: set[str] = set()
    for pin in pins:
        covered.add(str(pin.get("harvest_key") or ""))
        covered.update(str(item) for item in (pin.get("harvest_keys") or []))
    assert covered == {key, other}


def test_underdog_two_optic_ids_are_not_auto_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    nfl = _row("nfl", "football", "nfl", [
        _KALSHI_NFL,
        {"sportsbook": "underdog", "enabled": True, "source_league_id": "NFL"},
    ])
    games = [
        {"home_competitors": [{"abbreviation": "ZZX", "id": "oid-a", "name": "One"}]},
        {"home_competitors": [{"abbreviation": "ZZX", "id": "oid-b", "name": "Two"}]},
    ]
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_underdog_rfq.cached_optic_fixtures",
        lambda _oid: games,
    )
    key = "UDXNFLGAMEWIN_ZZXMIA26SEP281300_ZZX"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 3)], [nfl])
    assert pins == []
    assert skipped == [{"book": "underdog", "key": key, "reason": "no_unique_optic"}]


def test_underdog_league_not_on_tip_is_proposed_from_optic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboard, "spine_optic_league_id", lambda slug: "atp" if slug == "atp" else "")
    monkeypatch.setattr(onboard, "cached_optic_fixtures", lambda _oid: [{"sport": {"id": "tennis"}}])
    wta = _row("wta", "tennis", "wta", [])
    key = "UDXATPMATCHWIN_SINALC26SEP281300_SIN"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 5)], [wta])
    assert skipped == []
    assert [(p["league"], p["optic_league_id"], p["sport"]) for p in pins] == [("atp", "atp", "tennis")]
    assert {ex["sportsbook"] for ex in pins[0]["exchanges"]} == {"optic", "underdog"}


def test_unknown_underdog_venue_has_no_source_league() -> None:
    key = "UDXZZZMATCHWIN_AABB26SEP281300_AA"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 5)], [])
    assert pins == []
    assert skipped == [{"book": "underdog", "key": key, "reason": "no_source_league"}]


def test_optic_sport_unknown_is_needs_league_not_soccer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboard, "spine_optic_league_id", lambda _slug: "atp")
    monkeypatch.setattr(onboard, "cached_optic_fixtures", lambda _oid: [])
    key = "UDXATPMATCHWIN_SINALC26SEP281300_SIN"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 5)], [])
    assert pins == []
    assert skipped == [{"book": "underdog", "key": key, "reason": "needs_league"}]


def test_novig_uses_its_optic_league_to_propose() -> None:
    nhl_clone = _row("ahl", "hockey", "ahl", [])
    nhl = _row("nhl", "hockey", "nhl", [])
    item = RfqGapItem("novig", "uuid-1", 7, {"league_token": "NHL", "optic_league_id": "nhl"})
    pins, skipped = _run("novig", [item], [nhl_clone, nhl])
    assert skipped == []
    novig = next(ex for ex in pins[0]["exchanges"] if ex["sportsbook"] == "novig")
    assert pins[0]["league"] == "nhl"
    assert novig["settings"]["league"] == "NHL"


def _wired_novig(league: str, sport: str, token: str) -> LeagueRow:
    return _row(league, sport, league, [{
        "sportsbook": "novig",
        "enabled": True,
        "source_league_id": token,
        "settings": {"league": token},
    }])


def test_wired_novig_game_is_already_mapped() -> None:
    item = RfqGapItem("novig", "uuid-money", 4, {
        "league_token": "NHL",
        "optic_league_id": "nhl",
        "market_type": "MONEY",
        "optic_entity_id": "oid-1",
    })
    pins, skipped = _run("novig", [item], [_wired_novig("nhl", "hockey", "NHL")])
    assert pins == []
    assert skipped == [{"book": "novig", "key": "uuid-money", "reason": "already_mapped"}]


def test_wired_novig_player_without_an_optic_id_is_missing_optic() -> None:
    item = RfqGapItem("novig", "uuid-pts", 2, {
        "league_token": "NBA",
        "optic_league_id": "nba",
        "market_type": "POINTS",
    })
    pins, skipped = _run("novig", [item], [_wired_novig("nba", "basketball", "NBA")])
    assert pins == []
    assert skipped == [{"book": "novig", "key": "uuid-pts", "reason": "missing_optic"}]


def test_wired_novig_ignored_type_is_out_of_scope() -> None:
    item = RfqGapItem("novig", "uuid-draw", 2, {
        "league_token": "UFC",
        "optic_league_id": "ufc",
        "market_type": "DRAW",
        "optic_entity_id": "oid-1",
    })
    pins, skipped = _run("novig", [item], [_wired_novig("ufc", "mma", "UFC")])
    assert pins == []
    assert skipped == [{"book": "novig", "key": "uuid-draw", "reason": "out_of_scope"}]


def _ignore(league: str, key: str) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id="r1", league=league, sportsbook="novig", rule_kind="taxonomy",
        source_key_type="market_type", source_key=key, action="ignore",
        canonical_market_type=None, priority=0, enabled=True, confidence="high",
    )


def test_wired_novig_nhl_unknown_type_needs_a_tip_rule() -> None:
    """A type missing from the Python table stays needs_code until the tip ignores it."""
    nhl = _wired_novig("nhl", "hockey", "NHL")
    shots = RfqGapItem("novig", "01a0f0ea-913b-7671-9937-c0dbccde6e11", 3, {
        "league_token": "NHL", "optic_league_id": "nhl",
        "market_type": "PENALTY_MINUTES", "optic_entity_id": "oid-necas",
    })
    _, skipped = _run("novig", [shots], [nhl])
    assert skipped == [{"book": "novig", "key": shots.key, "reason": "needs_code"}]


def test_wired_novig_unknown_type_needs_a_rule() -> None:
    item = RfqGapItem("novig", "uuid-new", 2, {
        "league_token": "NBA",
        "optic_league_id": "nba",
        "market_type": "ZZTYPE",
        "optic_entity_id": "oid-1",
    })
    pins, skipped = _run("novig", [item], [_wired_novig("nba", "basketball", "NBA")])
    assert pins == []
    assert skipped == [{"book": "novig", "key": "uuid-new", "reason": "needs_code"}]


def test_novig_without_lookup_has_no_source_league() -> None:
    pins, skipped = _run("novig", [RfqGapItem("novig", "uuid-1", 7)], [])
    assert pins == []
    assert skipped == [{"book": "novig", "key": "uuid-1", "reason": "no_source_league"}]


def test_dkex_ambiguous_cfb_is_not_guessed(tmp_path, monkeypatch) -> None:
    """CFB maps to both ncaaf and cfb, so there is no single league to propose."""
    key = "CFB-ML-FG-ABCDEFGHIJ"
    # The league token comes from the typed catalogue row (subTopic NCAAF -> CFB).
    (tmp_path / "dkex_markets.jsonl").write_text(
        json.dumps({"symbol": key, "sub_topic": "NCAAF"}) + "\n")
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    pins, skipped = _run("dkex", [RfqGapItem("dkex", key, 5)], [])
    assert pins == []
    assert skipped == [{"book": "dkex", "key": key, "reason": "needs_league"}]


def test_owner_row_never_rewrites_an_enabled_token() -> None:
    """A Kalshi series whose Optic league is already wired under another prefix is left alone."""
    nfl = _row("nfl", "football", "nfl", [_KALSHI_NFL])
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    pinned = try_onboard_league_pin(
        _Store([nfl]), optic_id="nfl", sport="football", source_token="KXNFLSPREAD",
        book="kalshi", pins=pins, skipped=skipped, seen=set(), rows=[nfl], fixtures={},
        gap_key="KXNFLSPREAD-1", harvest_book="kalshi",
    )
    assert pinned is False
    assert pins == []
    assert skipped == [{"book": "kalshi", "key": "KXNFLSPREAD-1", "reason": "book_token_conflict"}]


def test_two_books_enabling_one_league_share_one_pin() -> None:
    class _Done:
        def __init__(self, value: Any) -> None:
            self.value = value

        def result(self) -> Any:
            return self.value

    def league_pin(book: str) -> dict[str, Any]:
        return {
            "kind": "mapping_league", "league": "nhl", "optic_league_id": "nhl",
            "exchanges": [{"sportsbook": "optic"}, {"sportsbook": book}],
        }

    jobs = {_Done(([league_pin("underdog")], [])): "underdog", _Done(([league_pin("novig")], [])): "novig"}
    pins: list[dict[str, Any]] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("mappers.control_plane.gap_fix.as_completed", lambda fs: list(fs))
        _merge_harvest_jobs(jobs, pins, [], set())
    assert len(pins) == 1
    assert [ex["sportsbook"] for ex in pins[0]["exchanges"]] == ["optic", "underdog", "novig"]


def test_second_book_keeps_underdog_total_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Kalshi pin for the same team must not drop the Underdog lines folded onto it."""

    class _Done:
        def __init__(self, value: Any) -> None:
            self.value = value

        def result(self) -> Any:
            return self.value

    def code_pin(book: str, key: str) -> dict[str, Any]:
        return {
            "kind": "entity_alias",
            "league": "nhl",
            "canonical_key": "oid-chi",
            "canonical_name": "Chicago",
            "entity_type": "team",
            "aliases": [{"sportsbook": book, "alias_kind": "code", "alias_value": "CHI"}],
            "harvest_book": book,
            "harvest_key": key,
        }

    later = "UDXNHLTOTAL_CHIVGK26SEP292230_7.5"
    underdog = code_pin("underdog", "UDXNHLTOTAL_CHIVGK26SEP292230_6.5")
    underdog["harvest_keys"] = [underdog["harvest_key"], later]
    jobs = {
        _Done(([code_pin("kalshi", "KXNHLGAME-26SEP29CHIVGK")], [])): "kalshi",
        _Done(([underdog], [])): "underdog",
    }
    pins: list[dict[str, Any]] = []
    monkeypatch.setattr("mappers.control_plane.gap_fix.as_completed", lambda fs: list(fs))
    _merge_harvest_jobs(jobs, pins, [], set())
    assert len(pins) == 1
    covered = pin_harvest_pairs(pins[0])
    assert ("kalshi", "KXNHLGAME-26SEP29CHIVGK") in covered
    assert ("underdog", "UDXNHLTOTAL_CHIVGK26SEP292230_6.5") in covered
    assert ("underdog", later) in covered
    assert {alias["sportsbook"] for alias in pins[0]["aliases"]} == {"kalshi", "underdog"}


def test_underdog_probe_that_drafts_nothing_records_aliases_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nhl = _row("nhl", "hockey", "nhl", [
        {"sportsbook": "underdog", "enabled": True, "source_league_id": "NHL"},
    ])
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_listed_onboard.probe_wired_underdog",
        lambda *_args, **_kwargs: None,
    )
    key = "UDXNHLTOTAL_CHIVGK26SEP292230_6.5"
    pins, skipped = _run("underdog", [RfqGapItem("underdog", key, 8)], [nhl], [])
    assert pins == []
    assert skipped == [{"book": "underdog", "key": key, "reason": ALIASES_COMPLETE}]
