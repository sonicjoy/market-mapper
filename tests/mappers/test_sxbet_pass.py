"""SX pass: catalogue grouping, fixture matching (Optic link / kickoff + names), stamping, load emit.

Catalogue rows are real ``GET /markets/active`` rows (2026-10-13); the
Optic side is a minimal stand-in carrying only the fields the pass reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from BigQuery.load_mappings import flatten_rows
from mappers.exchanges import sxbet_leagues, sxbet_pass
from mappers.exchanges.sxbet import SxConfig, selection_id
from mappers.exchanges.sxbet_pass import SxEvent, SxTally
from mappers.pipeline import attach_sxbet_row, row_key
from mappers.shared import CanonicalRow

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sxbet" / "markets_active_2026-10-13.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))
LINES = [json.dumps(r) for r in RAW]

def _cfg(slug: str, sport: str) -> SxConfig:
    cfg = sxbet_leagues.config_for(slug, sport)
    if cfg is None:
        raise AssertionError(f"no SX config for {slug}")
    return cfg


UCL = _cfg("ucl", "soccer")
BUN = _cfg("germany_bundesliga", "soccer")
CFB = _cfg("ncaaf", "football")

GAL_BAR = "L20129630"
SVW_PAD = "L20254403"
TEN_ALA = "L19765258"


def _hash(o1: str, event: str | None = None) -> str:
    return next(r["marketHash"].lower() for r in RAW
                if r["outcomeOneName"] == o1 and event in (None, r["sportXeventId"]))


def _odd(ev: str | None = None, sel: str | None = None) -> SimpleNamespace:
    src = {} if ev is None else {"SX Bet": {"event_id": ev, "market_id": (sel or "|").split("|")[0],
                                            "selection_id": sel}}
    return SimpleNamespace(source_ids=src)


def _entry(fid: str, start: str, home: str, away: str, home_name: str, away_name: str, odds=None):
    return SimpleNamespace(fixture=SimpleNamespace(
        fixture_id=fid, start_date=start, home=home, away=away,
        home_name=home_name, away_name=away_name, odds=odds or [], team_map={},
    ))


GS_BAR = _entry("F1", "2026-10-13T19:00:00Z", "GS", "BAR", "Galatasaray Spor Kulübü", "FC Barcelona")
SVW_PAD_FX = _entry("F2", "2026-10-17T13:30:00Z", "SVW", "PAD", "SV Werder Bremen", "SC Paderborn 07")
TEN_ALA_FX = _entry("F3", "2026-10-17T19:30:00Z", "TENN", "ALA", "Tennessee", "Alabama")


def _events(slug: str) -> tuple[dict[str, SxEvent], SxTally]:
    tally = SxTally()
    return sxbet_pass.read_catalogue(LINES, slug, tally), tally


def _row(market_type: str, side: str, line, *, home="SVW", away="PAD", league="germany_bundesliga",
         start="2026-10-17T13:30:00Z", optic_id=None) -> CanonicalRow:
    return CanonicalRow(league=league, start_date=start, home=home, away=away,
                        market_type=market_type, line=line, side=side, optic_id=optic_id)


# === Catalogue ===

def test_catalogue_keeps_this_leagues_open_markets_grouped_by_event() -> None:
    events, tally = _events("germany_bundesliga")
    assert set(events) == {SVW_PAD}
    ev = events[SVW_PAD]
    assert ev.teams == {"SV Werder Bremen", "SC Paderborn 07"}
    assert ev.starts == {"2026-10-17T13:30"}
    assert len(ev.markets) == 12
    assert tally.unreadable == 0


def test_catalogue_counts_unreadable_and_closed_rows() -> None:
    closed = dict(RAW[0], status="SETTLED")
    tally = SxTally()
    events = sxbet_pass.read_catalogue(["not json", json.dumps({"x": 1}), json.dumps(closed)], "ucl", tally)
    assert events == {}
    assert (tally.unreadable, tally.not_open) == (2, 1)


# === Optic links and the id bridge ===

def test_optic_event_links_and_an_event_on_two_fixtures_is_trusted_nowhere() -> None:
    a = _entry("A", "2026-10-13T19:00:00Z", "GS", "BAR", "x", "y", [_odd(GAL_BAR, "0xa|one")])
    b = _entry("B", "2026-10-13T19:00:00Z", "GS", "BAR", "x", "y", [_odd(GAL_BAR, "0xb|one"), _odd("E2", "0xc|one")])
    links = sxbet_pass.optic_event_links([a, b])
    assert set(links) == {"E2"}
    assert links["E2"] is b


def test_learned_sides_read_the_team_off_optics_own_ids() -> None:
    """NCAAF: SX "Tennessee Volunteers" never fits Optic "Tennessee" by name rule here -- the ids decide."""
    events, _ = _events("ncaaf")
    ev = events[TEN_ALA]
    h = _hash("Tennessee Volunteers +4.5")
    optic_sides = {selection_id(h, 1): "TENN", selection_id(h, 2): "ALA"}
    learned = sxbet_pass.learned_sides(ev, optic_sides, TEN_ALA_FX.fixture)
    assert learned == {"Tennessee Volunteers": "TENN", "Alabama Crimson Tide": "ALA"}


def test_learned_sides_drop_a_name_optic_puts_on_both_sides() -> None:
    events, _ = _events("ncaaf")
    ev = events[TEN_ALA]
    h1, h2 = _hash("Tennessee Volunteers +4.5"), _hash("Tennessee Volunteers +5.5")
    optic_sides = {selection_id(h1, 1): "TENN", selection_id(h2, 1): "ALA"}
    assert "Tennessee Volunteers" not in sxbet_pass.learned_sides(ev, optic_sides, TEN_ALA_FX.fixture)


# === Fixture matching ===

def test_a_linked_event_matches_on_optics_link_and_learned_sides() -> None:
    events, _ = _events("ncaaf")
    h = _hash("Tennessee Volunteers +4.5")
    fx = _entry("F3", TEN_ALA_FX.fixture.start_date, "TENN", "ALA", "Tennessee", "Alabama",
                [_odd(TEN_ALA, selection_id(h, 1))])
    optic_sides = {selection_id(h, 1): "TENN", selection_id(h, 2): "ALA"}
    hit = sxbet_pass.match_event(events[TEN_ALA], sxbet_pass.optic_event_links([fx]), {}, {}, CFB, optic_sides)
    assert hit is not None
    entry, sides, linked = hit
    assert entry is fx and linked
    assert sides["Alabama Crimson Tide"] == "ALA"


def test_an_unlinked_event_matches_on_kickoff_and_both_names() -> None:
    events, _ = _events("germany_bundesliga")
    by_start, by_day = sxbet_pass._fixture_index([SVW_PAD_FX])
    hit = sxbet_pass.match_event(events[SVW_PAD], {}, by_start, by_day, BUN)
    assert hit is not None
    assert hit[1] == {"SV Werder Bremen": "SVW", "SC Paderborn 07": "PAD"}
    assert hit[2] is False


def test_one_landing_team_is_not_a_match() -> None:
    """ "SC Paderborn 07" does not fit Optic's "Paderborn Lions" (hypothetical): Werder alone lands, and a
    one-name match is never taken (no anchored fallback for SX), even as the only fixture at that minute."""
    fx = _entry("F2", "2026-10-17T13:30:00Z", "SVW", "PAD", "SV Werder Bremen", "Paderborn Lions")
    events, _ = _events("germany_bundesliga")
    by_start, by_day = sxbet_pass._fixture_index([fx])
    assert sxbet_pass.match_event(events[SVW_PAD], {}, by_start, by_day, BUN) is None


def test_two_candidate_fixtures_at_one_minute_match_nothing() -> None:
    twin = _entry("F9", "2026-10-17T13:30:00Z", "SVW", "PAD", "SV Werder Bremen", "SC Paderborn 07")
    events, _ = _events("germany_bundesliga")
    by_start, by_day = sxbet_pass._fixture_index([SVW_PAD_FX, twin])
    assert sxbet_pass.match_event(events[SVW_PAD], {}, by_start, by_day, BUN) is None


def test_the_day_fallback_accepts_a_unique_two_name_match() -> None:
    moved = _entry("F2", "2026-10-17T16:00:00Z", "SVW", "PAD", "SV Werder Bremen", "SC Paderborn 07")
    events, _ = _events("germany_bundesliga")
    by_start, by_day = sxbet_pass._fixture_index([moved])
    hit = sxbet_pass.match_event(events[SVW_PAD], {}, by_start, by_day, BUN)
    assert hit is not None and hit[0] is moved


# === The pass ===

def test_run_pass_stamps_rows_optic_priced_and_counts_the_rest() -> None:
    events, tally = _events("germany_bundesliga")
    optic_rows = {
        row_key(r): r for r in (
            _row("point_spread", "SVW", -1.5), _row("point_spread", "PAD", 1.5),
            _row("game_total", "over", 2.5), _row("game_total", "under", 2.5),
            _row("moneyline_3way", "_TIE", None),
        )
    }
    rows = list(optic_rows.values())
    sxbet_pass.run_pass(BUN, [SVW_PAD_FX], rows, {}, events, key_of=row_key,
                        attach=lambda sr: attach_sxbet_row(optic_rows, {}, sr), tally=tally)
    assert tally.matched_events == 1
    assert tally.stamped == 5
    stamped = {(r.side, r.line): selection_id(r.sx_market_hash, r.sx_outcome)
               for r in rows if r.sx_market_hash is not None and r.sx_outcome is not None}
    assert stamped[("SVW", -1.5)] == f"{_hash('SV Werder Bremen -1.5')}|two"   # taker outcome one
    assert stamped[("PAD", 1.5)] == f"{_hash('SV Werder Bremen -1.5')}|one"
    assert stamped[("under", 2.5)] == f"{_hash('Over 2.5', SVW_PAD)}|one"
    assert tally.ignored == 1                       # soccer type 52 "12"
    assert tally.dropped_no_optic > 0               # the lines Optic did not price


def test_run_pass_leaves_optics_own_mapping_alone_and_drops_a_disagreement() -> None:
    events, tally = _events("germany_bundesliga")
    h = _hash("SV Werder Bremen -1.5")
    svw = _row("point_spread", "SVW", -1.5, optic_id="o1")
    pad = _row("point_spread", "PAD", 1.5, optic_id="o2")
    odds = {"o1": _odd(SVW_PAD, selection_id(h, 1)),      # Optic agrees: SVW is taker outcome one
            "o2": _odd(SVW_PAD, selection_id(h, 1))}      # Optic ALSO puts outcome one on PAD
    optic_rows = {row_key(svw): svw, row_key(pad): pad}
    sxbet_pass.run_pass(BUN, [SVW_PAD_FX], [svw, pad], odds, events, key_of=row_key,
                        attach=lambda sr: attach_sxbet_row(optic_rows, odds, sr), tally=tally)
    assert tally.conflict >= 1
    assert svw.sx_market_hash is None and pad.sx_market_hash is None


def test_run_pass_counts_unmatched_events_as_no_fixture() -> None:
    events, tally = _events("germany_bundesliga")
    sxbet_pass.run_pass(BUN, [], [], {}, events, key_of=row_key, attach=lambda sr: "x", tally=tally)
    assert tally.no_fixture == 12
    assert "SV Werder Bremen" in "".join(sxbet_pass.debug_lines(tally))
    assert "0/1 events matched" in tally.line("germany_bundesliga")


# === attach ===

def test_attach_outcomes() -> None:
    target = _row("game_total", "over", 2.5, optic_id="o1")
    index = {row_key(target): target}
    sr = _row("game_total", "over", 2.5)
    sr.sx_market_hash, sr.sx_outcome, sr.sx_event_id, sr.sx_type = "0xh", 1, SVW_PAD, 2
    assert attach_sxbet_row({}, {}, sr) == "dropped_no_optic"
    assert attach_sxbet_row(index, {"o1": _odd(SVW_PAD, "0xother|two")}, sr) == "optic_other_hash"
    assert attach_sxbet_row(index, {}, sr) == "stamped"
    assert (target.sx_market_hash, target.sx_outcome, target.sx_type) == ("0xh", 1, 2)
    assert attach_sxbet_row(index, {}, sr) == "duplicate"


# === load ===

def _rec(sxbet, source_ids=None) -> dict:
    return {
        "key": {"league": "germany_bundesliga", "start_date": "2026-10-17T13:30:00Z", "home": "SVW",
                "away": "PAD", "market_type": "game_total", "entity": None, "line": 2.5, "side": "under",
                "grouping_key": None},
        "optic_odds": {"fixture_id": "F2", "game_id": "g2", "market_id": "total_goals", "selection": "",
                       "selection_line": "under", "points": 2.5, "grouping_key": "default",
                       "source_ids": source_ids or {}},
        "sxbet": sxbet,
    }


SX_BLOCK = {"event_id": SVW_PAD, "market_id": "0xh", "selection_id": "0xh|one", "type": 2}


def test_load_emits_a_constructed_sx_row_in_optics_shape() -> None:
    rows = [r for r in flatten_rows(_rec(SX_BLOCK), "2026-10-13T15:00:00+00:00") if r["sportsbook"] == "SX Bet"]
    assert len(rows) == 1
    assert rows[0]["source_ids"] == {"event_id": SVW_PAD, "market_id": "0xh", "selection_id": "0xh|one"}


def test_load_never_double_emits_against_optics_sx_passthrough() -> None:
    optic = {"SX Bet": {"event_id": SVW_PAD, "market_id": "0xh", "selection_id": "0xh|one"}}
    rows = [r for r in flatten_rows(_rec(SX_BLOCK, optic), "2026-10-13T15:00:00+00:00") if r["sportsbook"] == "SX Bet"]
    assert len(rows) == 1
    assert rows[0]["source_ids"] == optic["SX Bet"]


# === Name pins (sxbet_names): by Optic competitor id, never by one landing name ===

def test_a_pinned_name_lands_by_optic_id_where_no_name_rule_fits() -> None:
    """ "Excelsior Rotterdam" fits no rule for Optic "SBV Excelsior"; the pin names its Optic competitor id."""
    fx = SimpleNamespace(home="HEE", away="EXC", home_name="SC Heerenveen", away_name="SBV Excelsior",
                         team_map={"4DEB5BDF207E": "EXC", "AAAA00000000": "HEE"})
    eredivisie = _cfg("netherlands_eredivisie", "soccer")
    assert sxbet_pass.side_for("Excelsior Rotterdam", fx, eredivisie) == "EXC"
    no_ids = SimpleNamespace(**{**fx.__dict__, "team_map": {}})
    assert sxbet_pass.side_for("Excelsior Rotterdam", no_ids, eredivisie) is None  # no id on the fixture: no side


def test_a_pin_the_name_rules_contradict_is_no_side() -> None:
    """A pin pointing at the side the name rules put the OTHER way is refused, never trusted alone."""
    eredivisie = _cfg("netherlands_eredivisie", "soccer")
    # "AZ Alkmaar" fits home "AZ Alkmaar" by name, but its pinned id (F7A33FA004CA) sits on the away side here.
    fx = SimpleNamespace(home="AZA", away="CAM", home_name="AZ Alkmaar", away_name="SC Cambuur Leeuwarden",
                         team_map={"F7A33FA004CA": "CAM"})
    assert sxbet_pass.side_for("AZ Alkmaar", fx, eredivisie) is None
