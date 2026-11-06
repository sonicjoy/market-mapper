"""STX in the tick: stamp onto Optic rows, what lands in market_mapping, the tie-pays-half flag the maker refuses on.

Fixture: the GB v CAR game of the 2026-10-28 capture with synthetic Optic odds (``test_stx_pass._optic_game``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from BigQuery.load_mappings import KEY_COLUMNS, _row_merge_key, _source_identity_sql, flatten_rows
from mappers.exchanges import optic, stx_attach
from mappers.exchanges.stx_pass import StxContext, run_pass
from mappers.pipeline import ScheduleEntry, canonical_row_to_json, row_key
from mappers.vocab.football_markets import FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES
from mappers.vocab.stx_markets import TIE_PAYS_HALF
from tests.mappers import _stx_capture as cap
from tests.mappers.test_stx_pass import _optic_game

WINNER = "0a0b4f52-d056-4be2-9632-f8a33cb938ff"  # home_winner GB
SPREAD = "8e833e5c-ba98-4105-8ffe-8a1684be25c2"  # spread -2.5
TOTAL = "846559f6-455b-4e8c-ac23-09e752fd31aa"  # over_under 46.5
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def _catalogue_rows(market_ids: set[str]) -> list[dict]:
    from fetch.stx import load_markets_list, normalize

    rows = load_markets_list(cap.DIR / "stx_open_markets_identity_2026-10-28.json.gz")
    return [normalize(r) for r in rows if r["market_id"] in market_ids]


def _away_winner_id() -> str:
    return next(m.market_id for m in cap.markets() if m.event_id == cap.GB_CAR_EVENT and m.rules == "away_winner")


def _tick(tmp_path, market_ids: set[str]):
    """Optic rows for the game, the STX files in a data dir, then the league pass. Returns (rows, all_rows, tally)."""
    cfg = optic.OpticConfig(league_id="nfl", table_types=FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES)
    ((fx,),) = optic.load_fixtures([json.dumps(_optic_game())], cfg).values()
    rows, odd_lookup, ref_lookup = optic.build_rows(fx.start_date, fx.home, fx.away, fx, cfg, league="nfl")
    (tmp_path / stx_attach.MARKETS_FILE).write_text(
        "".join(json.dumps(r) + "\n" for r in _catalogue_rows(market_ids)), encoding="utf-8"
    )
    index = {row_key(r): r for r in rows}
    all_rows = list(rows)
    tally = stx_attach.run_league(
        "nfl", [ScheduleEntry(fx)], index, all_rows, tmp_path, key_of=row_key, as_of=cap.AS_OF
    )
    assert tally is not None
    return all_rows, odd_lookup, ref_lookup, tally


def _loaded(all_rows, odd_lookup, ref_lookup) -> list[dict]:
    """The ``market_mapping`` rows ``load_mappings`` would write for these canonical rows (STX only)."""
    out = []
    for r in all_rows:
        rec = canonical_row_to_json(r, odd_lookup, ref_lookup)
        out += [x for x in flatten_rows(rec, NOW.isoformat()) if x["sportsbook"] == "STX"]
    return out


def test_nfl_winner_rows_carry_tie_pays_half_in_source_ids(tmp_path):
    away = _away_winner_id()
    all_rows, odd, ref, tally = _tick(tmp_path, {WINNER, away})
    assert tally["stamped"] + tally["satellite"] == 4  # YES+NO of both winner markets
    rows = _loaded(all_rows, odd, ref)
    assert len(rows) == 4
    for r in rows:
        assert r["source_ids"]["tie_pays_half"] is True  # the column the maker reads: source_ids.tie_pays_half
        assert set(r["source_ids"]) == {"market_id", "selection_id", "event_id", "tie_pays_half"}
        assert r["fixture_id"] == cap.GB_CAR_FIXTURE and r["market_id"] == "moneyline"
    by = {(r["source_ids"]["market_id"], r["source_ids"]["selection_id"]): r["side"] for r in rows}
    assert by == {(WINNER, "yes"): "GB", (WINNER, "no"): "CAR", (away, "yes"): "CAR", (away, "no"): "GB"}


def test_spread_and_total_rows_are_never_flagged(tmp_path):
    """Half-number lines cannot end level (``concepts__market-shape.md:346-347``): only the 2-way winner pushes."""
    all_rows, odd, ref, _ = _tick(tmp_path, {SPREAD, TOTAL})
    rows = _loaded(all_rows, odd, ref)
    assert len(rows) == 4
    assert {r["source_ids"]["tie_pays_half"] for r in rows} == {False}


def test_two_markets_on_one_bet_each_keep_a_row(tmp_path):
    """YES home_winner and NO away_winner are both GB: one stamps, one is a satellite, the MERGE keys differ."""
    away = _away_winner_id()
    all_rows, odd, ref, tally = _tick(tmp_path, {WINNER, away})
    assert tally["satellite"] == 2 and tally["stamped"] == 2
    rows = _loaded(all_rows, odd, ref)
    assert len({_row_merge_key(r) for r in rows}) == 4
    assert all(r["sportsbook"] == "STX" for r in rows)
    assert "'STX'" in _source_identity_sql("t")
    assert set(KEY_COLUMNS) <= set(rows[0])


@pytest.mark.parametrize(
    ("competition", "flagged"),
    [("NFL", True), ("NBA", True), ("NCAAF", False), ("NHL", False)],
)
def test_flag_per_competition_with_the_venue_text_behind_it(competition, flagged):
    """NFL: tie pays half. NBA: venue template allows a push on a draw (flagged, conservative). NCAAF cannot tie
    ("played to a winner"); NHL decides in overtime / shootout."""
    from mappers.vocab.stx_markets import TIE_PAYS_HALF_COMPETITIONS

    assert (competition in TIE_PAYS_HALF_COMPETITIONS) is flagged


def test_every_flagged_leg_is_a_two_way_winner_and_nothing_else():
    """No mapped side outside the winner family, and no 3-way, carries the flag across the whole capture."""
    ctx = StxContext(
        fixtures=list(cap.fixtures()), as_of=cap.AS_OF, rosters=cap.rosters(), optic_players=cap.optic_players()
    )
    sides, _ = run_pass(cap.markets(), ctx)
    flagged = [s for s in sides if s.mapped and s.rule and TIE_PAYS_HALF in s.rule.flags]
    assert flagged
    assert {s.market.rules for s in flagged} <= {"home_winner", "away_winner"}
    assert {s.market.competition for s in flagged} <= {"NFL", "NBA"}
    # every mapped NFL / NBA 2-way winner side IS flagged (fail closed)
    winners = [
        s
        for s in sides
        if s.mapped and s.market.rules in ("home_winner", "away_winner") and s.market.competition in ("NFL", "NBA")
    ]
    assert winners and all(TIE_PAYS_HALF in s.rule.flags for s in winners if s.rule)


def test_no_optic_row_drops_and_nothing_lands(tmp_path):
    """Optic does not price the line (spread -2.5 absent): the STX side is counted, never emitted."""
    cfg = optic.OpticConfig(league_id="nfl", table_types=FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES)
    ((fx,),) = optic.load_fixtures([json.dumps(_optic_game())], cfg).values()
    rows, odd, ref = optic.build_rows(fx.start_date, fx.home, fx.away, fx, cfg, league="nfl")
    kept = [r for r in rows if r.market_type != "point_spread"]
    (tmp_path / stx_attach.MARKETS_FILE).write_text(
        "".join(json.dumps(r) + "\n" for r in _catalogue_rows({SPREAD})), encoding="utf-8"
    )
    all_rows = list(kept)
    tally = stx_attach.run_league(
        "nfl", [ScheduleEntry(fx)], {row_key(r): r for r in kept}, all_rows, tmp_path, key_of=row_key, as_of=cap.AS_OF
    )
    assert tally is not None and tally["dropped_no_optic"] == 2 and tally["stamped"] == 0
    assert _loaded(all_rows, odd, ref) == []


def test_unmapped_sides_are_counted_by_reason_and_written(tmp_path, capsys):
    """A started event: every side refused ``event_started``, listed in ``stx_unmapped.<league>.jsonl``."""
    cfg = optic.OpticConfig(league_id="nfl", table_types=FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES)
    ((fx,),) = optic.load_fixtures([json.dumps(_optic_game())], cfg).values()
    (tmp_path / stx_attach.MARKETS_FILE).write_text(
        "".join(json.dumps(r) + "\n" for r in _catalogue_rows({WINNER})), encoding="utf-8"
    )
    late = datetime(2026, 10, 31, tzinfo=UTC)
    tally = stx_attach.run_league("nfl", [ScheduleEntry(fx)], {}, [], tmp_path, key_of=row_key, as_of=late)
    assert tally is not None and tally["unmapped:event_started"] == 2
    lines = (tmp_path / "stx_unmapped.nfl.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["reason"].startswith("event_started")
    assert "unmapped by reason: event_started 2" in capsys.readouterr().err


def test_a_league_with_no_stx_competition_or_no_file_is_a_noop(tmp_path):
    assert stx_attach.run_league("epl", [], {}, [], tmp_path, key_of=row_key) is None
    assert stx_attach.run_league("nfl", [], {}, [], tmp_path, key_of=row_key) is None  # no stx_markets.jsonl


def test_head_to_head_odds_do_not_make_a_player_ambiguous():
    """``player_rebounds_h2h_*`` odds carry ``"A,B,B"`` as player_id; indexing them gave one NBA player 3 ids."""
    from types import SimpleNamespace

    odds = [
        SimpleNamespace(player_id="57BE8F52D963", selection="Onyeka Okongwu"),
        SimpleNamespace(player_id="57A9D1B7F567,57BE8F52D963,57BE8F52D963", selection="Onyeka Okongwu"),
        SimpleNamespace(player_id=None, selection="Atlanta Hawks"),
    ]
    idx = stx_attach.optic_players([SimpleNamespace(fixture=SimpleNamespace(fixture_id="F1", odds=odds))])
    assert idx == {"F1": {"onyeka okongwu": {"57BE8F52D963": "Onyeka Okongwu"}}}
