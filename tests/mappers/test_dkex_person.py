"""DKEX tennis, UFC and NBA preseason: person-name sides, any-league tennis.

Catalogue rows are real staging markets in
``tests/fixtures/dkex/staging_person_2026-09-29.json`` run through
``fetch.dkex.normalize``; the Optic side is a minimal stand-in carrying
only the fields the pass reads, with the names and start times Optic
listed on 2026-09-29.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fetch.dkex import normalize
from mappers.exchanges.dkex import DkexConfig, league_token
from mappers.exchanges.dkex_catalogue_read import DkexTally
from mappers.exchanges.dkex_names import person_side_for
from mappers.exchanges.dkex_pass import run_pass
from mappers.vocab import dkex_markets as vocab

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_person_2026-09-29.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))

TENNIS = DkexConfig(
    league="ATP", market_types=vocab.TENNIS, ignored_markets=vocab.TENNIS_IGNORED,
    person_names=True, any_league=True,
)
UFC = DkexConfig(
    league="UFC", market_types=vocab.UFC, ignored_markets=vocab.UFC_IGNORED,
    person_names=True,
)
NBA = DkexConfig(league="NBA", market_types=vocab.BASKETBALL)


def _entry(start: str, home: str, away: str, home_name: str, away_name: str) -> SimpleNamespace:
    return SimpleNamespace(fixture=SimpleNamespace(
        start_date=start, home=home, away=away,
        home_name=home_name, away_name=away_name, odds=[],
    ))


def _run(tmp_path: Path, cfg: DkexConfig, entries: list) -> tuple[DkexTally, list]:
    (tmp_path / "dkex_markets.jsonl").write_text(
        "".join(json.dumps(normalize(r, "api")) + "\n" for r in RAW), encoding="utf-8",
    )
    stamped: list = []

    def attach(_index, _alt, _all, dr) -> str:
        stamped.append(dr)
        return "stamped"

    tally = run_pass(cfg.league.casefold(), cfg, entries, {}, [], tmp_path, attach)
    return tally, stamped


def _sides(rows: list) -> set[tuple[str, str, str]]:
    """(DKEX participant, dkex side, canonical side) for every stamped row."""
    by_ticker = {r["ticker"]: r["metadata"]["participants"][0]["name"] for r in RAW}
    return {(by_ticker[r.dkex_symbol], r.dkex_side, r.side) for r in rows}


# === Person names ===

def test_person_side_exact_and_middle_name() -> None:
    kw = {"home": "HUR", "away": "FOK",
          "home_name": "Hubert Hurkacz", "away_name": "Alejandro Davidovich Fokina"}
    assert person_side_for("Hubert Hurkacz", **kw) == "HUR"
    assert person_side_for("Alejandro Davidovich Fokina", **kw) == "FOK"
    assert person_side_for("Alejandro Fokina", **kw) == "FOK"


def test_person_side_needs_first_and_last_name() -> None:
    kw = {"home": "HUR", "away": "FOK",
          "home_name": "Hubert Hurkacz", "away_name": "Alejandro Davidovich Fokina"}
    assert person_side_for("Hurkacz", **kw) is None
    assert person_side_for("Hubert Hurkaczek", **kw) is None


def test_person_fitting_both_sides_is_no_side() -> None:
    kw = {"home": "A", "away": "B", "home_name": "Karolina Pliskova", "away_name": "Karolina Pliskova"}
    assert person_side_for("Karolina Pliskova", **kw) is None


# === Tennis ===

HURKACZ = _entry("2026-09-29T11:00:00Z", "HUR", "FOK", "Hubert Hurkacz", "Alejandro Davidovich Fokina")
MONNET = _entry("2026-09-29T13:00:00Z", "MON2", "CBA3", "Carole Monnet", "Cagla Buyukakcay")
CRAWLEY = _entry("2026-09-29T14:00:00Z", "FCR", "EPR", "Fiona Crawley", "Elena Pridankina")


def test_tennis_reads_every_tour_whatever_the_subtopic(tmp_path: Path) -> None:
    """subTopic is "ATP Chengdu", "WTA Adana 125" or just "ATP": all are read."""
    tally, rows = _run(tmp_path, TENNIS, [HURKACZ, MONNET])
    assert tally.matched_events == 2
    assert _sides(rows) == {
        ("Hubert Hurkacz", "yes", "HUR"), ("Hubert Hurkacz", "no", "FOK"),
        ("Alejandro Davidovich Fokina", "yes", "FOK"), ("Alejandro Davidovich Fokina", "no", "HUR"),
        ("Carole Monnet", "yes", "MON2"), ("Carole Monnet", "no", "CBA3"),
        ("Cagla Buyukakcay", "yes", "CBA3"), ("Cagla Buyukakcay", "no", "MON2"),
    }


def test_tennis_ignores_non_tennis_events(tmp_path: Path) -> None:
    tally, _ = _run(tmp_path, TENNIS, [HURKACZ, MONNET])
    # UFC WIN/FT and NBA WIN/FG are other leagues to the tennis pass.
    assert tally.other_league == 4


def test_tennis_pairing_optic_does_not_list_is_skipped(tmp_path: Path) -> None:
    """DKEX has Siskova v Crawley; Optic has Crawley v Pridankina: one name is not a match."""
    tally, rows = _run(tmp_path, TENNIS, [CRAWLEY])
    assert tally.matched_events == 0
    assert not rows


def test_tennis_doubles_do_not_land_on_a_singles_player(tmp_path: Path) -> None:
    singles = _entry("2026-10-02T00:00:00Z", "SGI", "JVL", "Sander Gille", "Joran Vliegen")
    tally, rows = _run(tmp_path, TENNIS, [singles])
    assert tally.matched_events == 0
    assert not rows


# === UFC ===

def test_ufc_bout_matches_on_the_day_and_both_fighters(tmp_path: Path) -> None:
    """DKEX lists 02:15 UTC, Optic 01:20: the same-day unique fallback matches."""
    silva = _entry("2026-10-04T01:20:00Z", "NSA5", "CWO8", "Natalia Silva", "Cong Wang")
    tally, rows = _run(tmp_path, UFC, [silva])
    assert tally.matched_events == 1
    assert _sides(rows) == {
        ("Natalia Silva", "yes", "NSA5"), ("Natalia Silva", "no", "CWO8"),
        ("Cong Wang", "yes", "CWO8"), ("Cong Wang", "no", "NSA5"),
    }


def test_contender_series_is_the_ufc_league() -> None:
    assert league_token("Dana White\u2019s Contender Series") == "UFC"


# === NBA preseason ===

def test_nba_preseason_is_the_nba_league() -> None:
    assert league_token("NBA Preseason") == "NBA"


def test_nba_preseason_game_stamps(tmp_path: Path) -> None:
    tor = _entry("2026-10-03T23:00:00Z", "TOR", "MIA", "Toronto Raptors", "Miami Heat")
    tally, rows = _run(tmp_path, NBA, [tor])
    assert tally.matched_events == 1
    assert _sides(rows) == {
        ("MIA Heat", "yes", "MIA"), ("MIA Heat", "no", "TOR"),
        ("TOR Raptors", "yes", "TOR"), ("TOR Raptors", "no", "MIA"),
    }


# === Tennis lines: games / sets handicap, total games, set winners ===

# Norrie v Svrcina (ATP Shanghai) as staging listed it on 2026-10-08; the match
# has since settled, so every row is pinned to "active" to be read as open.
LINES = json.loads((FIXTURE.parent / "staging_tennis_lines_2026-10-08.json").read_text(encoding="utf-8"))
NORRIE = _entry("2026-10-08T12:07:07Z", "CNO", "DSV", "Cameron Norrie", "Dalibor Svrcina")


def _run_lines(tmp_path: Path) -> list:
    (tmp_path / "dkex_markets.jsonl").write_text(
        "".join(json.dumps(normalize(r, "api")) + "\n" for r in LINES), encoding="utf-8",
    )
    stamped: list = []

    def attach(_index, _alt, _all, dr) -> str:
        stamped.append(dr)
        return "stamped"

    run_pass("atp", TENNIS, [NORRIE], {}, [], tmp_path, attach)
    return stamped


def _by_type(rows: list) -> dict[str, set[tuple[str, str, str, float | None]]]:
    out: dict[str, set] = {}
    for r in rows:
        out.setdefault(r.market_type, set()).add(
            (r.dkex_side, r.side, r.entity if r.entity else "", r.line))
    return out


def test_tennis_lines_map_to_their_optic_markets(tmp_path: Path) -> None:
    by_type = _by_type(_run_lines(tmp_path))
    assert set(by_type) == {
        "point_spread", "set_handicap", "match_total_games",
        "1st_set_winner", "2nd_set_winner",
    }


def test_tennis_handicap_yes_is_the_named_player_at_minus_the_strike(tmp_path: Path) -> None:
    rows = [r for r in _run_lines(tmp_path) if r.market_type == "point_spread"]
    norrie = {(r.dkex_side, r.side, r.line) for r in rows if r.dkex_symbol.endswith("CAIE002-GTE-P00015")}
    assert norrie == {("yes", "CNO", -1.5), ("no", "DSV", 1.5)}


def test_tennis_total_games_yes_is_over(tmp_path: Path) -> None:
    rows = [r for r in _run_lines(tmp_path) if r.market_type == "match_total_games"]
    got = {(r.dkex_side, r.side, r.line) for r in rows if r.dkex_symbol.endswith("P00115")}
    assert got == {("yes", "over", 11.5), ("no", "under", 11.5)}


def test_tennis_set_winner_is_the_period_s1_and_s2_not_a_season(tmp_path: Path) -> None:
    rows = _run_lines(tmp_path)
    first = {(r.dkex_side, r.side) for r in rows
             if r.market_type == "1st_set_winner" and r.dkex_symbol.endswith("CAIE002")}
    second = {(r.dkex_side, r.side) for r in rows
              if r.market_type == "2nd_set_winner" and r.dkex_symbol.endswith("CAIE002")}
    assert first == second == {("yes", "CNO"), ("no", "DSV")}


def test_ufc_total_rounds_yes_is_over(tmp_path: Path) -> None:
    """TRNDS/FT: the Silva v Wang WIN row re-typed as a bout total (no participants)."""
    wins = [r for r in RAW if r["ticker"].startswith("UFC-WIN-FT-01S9BQSFIUQSKNO")]
    total = json.loads(json.dumps(wins[0]))
    total["ticker"] = "UFC-TRNDS-FT-01S9BQSFIUQSKNO-GTE-P00025"
    total["metadata"]["participants"] = []
    total["parameters"].pop("participant", None)
    total["parameters"].update(
        statAchievement="TRNDS", timePeriod="FT", strikePrice="2.5", outcomeType="GTE")
    (tmp_path / "dkex_markets.jsonl").write_text(
        "".join(json.dumps(normalize(r, "api")) + "\n" for r in (*wins, total)), encoding="utf-8")
    stamped: list = []
    silva = _entry("2026-10-04T01:20:00Z", "NSA5", "CWO8", "Natalia Silva", "Cong Wang")
    run_pass("ufc", UFC, [silva], {}, [], tmp_path,
             lambda _i, _a, _all, dr: stamped.append(dr) or "stamped")
    assert {(r.dkex_side, r.side, r.line) for r in stamped if r.market_type == "total_rounds"} == {
        ("yes", "over", 2.5), ("no", "under", 2.5)}


def test_fighter_nickname_resolves_by_its_optic_id() -> None:
    """DKEX "Lupita Godinez" is Optic's "Loopy Godínez": no name rule fits, the id pin does."""
    from mappers.exchanges.dkex_pass import _side_for
    fx = SimpleNamespace(
        home="LGO", away="KSO", home_name="Loopy Godínez", away_name="Ketlen Souza",
        team_map={"9E55CCC0A9EE": "LGO", "722BB455E232": "KSO"},
    )
    assert _side_for("Lupita Godinez", fx, person=True) == "LGO"
    assert _side_for("Ketlen Souza", fx, person=True) == "KSO"


def test_wta_given_name_variants_resolve_by_their_optic_ids() -> None:
    """DKEX "Caty McNally" / "Yuliia Starodubtseva" are Optic's "Catherine" / "Yulia": the id pins fit them."""
    from mappers.exchanges.dkex_pass import _side_for
    fx = SimpleNamespace(
        home="MCC", away="STA", home_name="Catherine McNally", away_name="Yulia Starodubtseva",
        team_map={"77A1D24EB085": "MCC", "B0285346B076": "STA"},
    )
    assert _side_for("Caty McNally", fx, person=True) == "MCC"
    assert _side_for("Yuliia Starodubtseva", fx, person=True) == "STA"


def test_tennis_and_ufc_spelling_variants_resolve_by_their_optic_ids() -> None:
    """Spacing and given-name variants no name rule fits: the id pins place them."""
    from mappers.exchanges.dkex_pass import _side_for
    cases = [
        ("Anastasiia Sobolieva", "Anastasiya Sobolieva", "Ane Mintegi Del Olmo",
         "B7E70108C926", "ABC3FA7D76D3131B"),
        ("Raluca Georgiana Serban", "Raluka Serban", "Sara Cakarevic",
         "1BE9F0D675DC", "69DDB2873BF80443"),
        ("Cody Chovancek", "Cody Chovancek", "Su Young You", "C44E3FFDF18C6D15", "338A4EF20A5E"),
    ]
    for claimed, home_name, away_name, home_id, away_id in cases:
        fx = SimpleNamespace(home="HOM", away="AWY", home_name=home_name,
                             away_name=away_name if claimed != "Cody Chovancek" else "SuYoung You",
                             team_map={home_id: "HOM", away_id: "AWY"})
        assert _side_for(claimed, fx, person=True) == "HOM"
    fx = SimpleNamespace(home="LJO", away="TCU", home_name="Louis Jourdain", away_name="Timmy Cuamba",
                         team_map={"563A4126E96659EE": "LJO", "C30B4A71FFEB": "TCU"})
    assert _side_for("Timothy Cuamba", fx, person=True) == "TCU"
    assert _side_for("Su Young You", SimpleNamespace(
        home="CCH", away="SYY", home_name="Cody Chovancek", away_name="SuYoung You",
        team_map={"338A4EF20A5E": "SYY"}), person=True) == "SYY"


def test_cfb_and_ufc_name_pins_place_the_side_by_optic_id() -> None:
    """DKEX "Southern Miss", "Ramazonbek Temirov", "Cam Rowston" fit no name rule; the id pins place them."""
    from mappers.exchanges.dkex_pass import _side_for
    cases = [
        ("Southern Miss", "Southern Mississippi", "826709E8B05C", False),
        ("Ramazonbek Temirov", "Ramazan Temirov", "45BF28A082B6", True),
        ("Cam Rowston", "Cameron Rowston", "27A28382FDBD", True),
    ]
    for claimed, optic_name, optic_id, person in cases:
        fx = SimpleNamespace(home="HOM", away="AWY", home_name="Other Side", away_name=optic_name,
                             team_map={optic_id: "AWY"})
        assert _side_for(claimed, fx, person=person) == "AWY"


def test_itf_slugs_run_dkex_with_the_tennis_pass() -> None:
    from mappers.exchanges.dkex_leagues import VENUE_TOKEN_BY_SLUG
    assert VENUE_TOKEN_BY_SLUG["itf_men"] == "ITFM"
    assert VENUE_TOKEN_BY_SLUG["itf_women"] == "ITFW"
