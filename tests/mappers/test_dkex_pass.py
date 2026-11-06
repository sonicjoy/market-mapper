"""DKEX pass: typed catalogue grouping, fixture matching, entity resolution.

Catalogue rows are the real staging markets in
``tests/fixtures/dkex/staging_markets_2026-09-28.json`` run through
``fetch.dkex.normalize``; the Optic side is a minimal stand-in carrying
only the fields the pass reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fetch.dkex import normalize
from mappers.exchanges.dkex import DkexConfig
from mappers.exchanges.dkex_catalogue_read import DkexEvent, DkexTally, read_catalogue
from mappers.exchanges.dkex_names import city_abbrev_fits, optic_id_side, team_side_for
from mappers.exchanges.dkex_pass import _match_event, _side_for, _start_key, run_pass
from mappers.vocab import dkex_markets as vocab

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_markets_2026-09-28.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))
NFL = DkexConfig(
    league="NFL",
    market_types=vocab.FOOTBALL,
    implied_lines=vocab.FOOTBALL_IMPLIED_LINES,
    ignored_markets=vocab.FOOTBALL_IGNORED,
)
DEN_SF = "01S2KTKBIUCN390"
PIT_CLE = "01S2LVEPIUCM13O"


def _write_catalogue(tmp_path: Path, rows: list[dict] | None = None) -> Path:
    rows = rows if rows is not None else [normalize(r, "api") for r in RAW]
    (tmp_path / "dkex_markets.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8",
    )
    return tmp_path


def _events(tmp_path: Path, rows: list[dict] | None = None) -> tuple[dict[str, DkexEvent], DkexTally]:
    tally = DkexTally()
    return read_catalogue(_write_catalogue(tmp_path, rows), NFL, tally), tally


def _odd(player_id: str, selection: str) -> SimpleNamespace:
    return SimpleNamespace(player_id=player_id, selection=selection)


def _entry(start: str, home: str, away: str, home_name: str, away_name: str,
           odds: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(fixture=SimpleNamespace(
        start_date=start, home=home, away=away,
        home_name=home_name, away_name=away_name, odds=odds or [],
    ))


SF_DEN = _entry("2026-10-04T20:25:00Z", "SF", "DEN", "San Francisco 49ers", "Denver Broncos")
CLE_PIT = _entry(
    "2026-10-02T00:15:00Z", "CLE", "PIT", "Cleveland Browns", "Pittsburgh Steelers",
    odds=[_odd("p1", "Denzel Boston"), _odd("p2", "Aaron Rodgers"), _odd("p3", "Deshaun Watson")],
)


# === Catalogue grouping ===

def test_catalogue_groups_on_competition_id_and_filters_league(tmp_path: Path) -> None:
    events, tally = _events(tmp_path)
    assert set(events) == {DEN_SF, PIT_CLE, "00O2Q7JBQSTTPC0"}
    # BSA, CFB and MLB rows are other leagues by subTopic.
    assert tally.other_league == 5
    assert tally.untyped == 0


def test_home_and_away_come_from_sibling_team_market_roles(tmp_path: Path) -> None:
    """Props list only the player; the event's roles come from WIN/MOVY/TMPTS rows."""
    events, _ = _events(tmp_path)
    ev = events[PIT_CLE]
    assert ev.home is not None and ev.home.name == "CLE Browns"
    assert ev.away is not None and ev.away.name == "PIT Steelers"
    assert ev.has_roles()
    den_sf = events[DEN_SF]
    assert (den_sf.home.name, den_sf.away.name) == ("SF 49ers", "DEN Broncos")  # type: ignore[union-attr]


def test_props_only_event_has_no_roles(tmp_path: Path) -> None:
    events, _ = _events(tmp_path)
    assert not events["00O2Q7JBQSTTPC0"].has_roles()


def test_untyped_rows_are_counted_not_parsed(tmp_path: Path) -> None:
    rows = [normalize({"ticker": r["ticker"], "status": "Open"}, "reports") for r in RAW]
    events, tally = _events(tmp_path, rows)
    assert events == {}
    assert tally.untyped == len(RAW)


def test_combo_rows_are_counted(tmp_path: Path) -> None:
    combo = normalize({"ticker": "COMBO-1", "status": "active", "legs": [{}]}, "api")
    _, tally = _events(tmp_path, [combo])
    assert tally.combos == 1


# === Name fitting ===

def test_city_abbreviation_fits_the_spelled_out_city() -> None:
    assert city_abbrev_fits("DEN Broncos", "Denver Broncos", "DEN")
    assert city_abbrev_fits("NY Jets", "New York Jets", "NYJ")
    assert city_abbrev_fits("LA Dodgers", "Los Angeles Dodgers", "LAD")
    assert city_abbrev_fits("CHI White Sox", "Chicago White Sox", "CWS")
    assert city_abbrev_fits("JAX Jaguars", "Jacksonville Jaguars", "JAX")


def test_city_abbreviation_fits_city_letters_in_order() -> None:
    """Codes that are neither initials nor a prefix (2026-10-05 catalogue).

    The side code passed is our canonical one, not Optic's, so the abbrev
    branch cannot carry these.
    """
    assert city_abbrev_fits("WPG Jets", "Winnipeg Jets", "WJE9")
    assert city_abbrev_fits("STL Blues", "St. Louis Blues", "SLB9")
    assert city_abbrev_fits("FLA Panthers", "Florida Panthers", "FPA9")
    assert city_abbrev_fits("MTL Canadiens", "Montreal Canadiens", "MCA9")
    assert city_abbrev_fits("OKC Thunder", "Oklahoma City Thunder", "OCT9")
    assert city_abbrev_fits("BKN Nets", "Brooklyn Nets", "BNE9")
    # The first letter must open the city, and the nickname must still match.
    assert not city_abbrev_fits("TLS Blues", "St. Louis Blues", "SLB9")
    assert not city_abbrev_fits("WPG Jets", "Winnipeg Flyers", "WFL9")


def test_jax_is_pinned_because_jacksonville_has_no_x() -> None:
    assert not city_abbrev_fits("JAX Jaguars", "Jacksonville Jaguars", "JJA9")
    assert optic_id_side("JAX Jaguars", {"9CCE4CA64CF2": "JJA9"}) == "JJA9"


def test_city_abbreviation_rule_is_narrow() -> None:
    assert not city_abbrev_fits("NY Jets", "New York Giants", "NYG")
    # A full word is not an abbreviation: Mississippi State is not MVSU.
    assert not city_abbrev_fits("Mississippi State", "Mississippi Valley State", "MVSU")
    assert not city_abbrev_fits("Athletics", "Oakland Athletics", "OAK")


def test_team_side_for_needs_exactly_one_side() -> None:
    kw: dict[str, Any] = {"home": "NYJ", "away": "NYG", "home_name": "New York Jets", "away_name": "New York Giants"}
    assert team_side_for("NY Jets", **kw) == "NYJ"
    assert team_side_for("NY Giants", **kw) == "NYG"
    assert team_side_for("NY", **kw) is None


# === Fixture matching ===

def _index(*entries: SimpleNamespace) -> tuple[dict, dict]:
    by_start: dict = {}
    by_day: dict = {}
    for e in entries:
        key = _start_key(e.fixture.start_date)
        by_start.setdefault(key, []).append(e)
        by_day.setdefault(key[:10], []).append(e)
    return by_start, by_day


def test_event_matches_on_start_and_both_role_names(tmp_path: Path) -> None:
    events, _ = _events(tmp_path)
    by_start, by_day = _index(SF_DEN, CLE_PIT)
    resolved = _match_event(events[DEN_SF], by_start, by_day)
    assert resolved is not None
    entry, sides = resolved
    assert entry is SF_DEN
    ev = events[DEN_SF]
    assert sides == {ev.home.id: "SF", ev.away.id: "DEN"}  # type: ignore[union-attr]


def test_postponed_event_matches_on_any_of_its_starts(tmp_path: Path) -> None:
    events, _ = _events(tmp_path)
    ev = events[DEN_SF]
    ev.starts = {"2026-10-05T20:25", _start_key(SF_DEN.fixture.start_date)}
    by_start, _ = _index(SF_DEN)
    assert _match_event(ev, by_start, {}) is not None
    ev.starts = {"2026-10-05T20:25"}
    assert _match_event(ev, by_start, {}) is None


def test_day_fallback_accepts_only_a_unique_fixture(tmp_path: Path) -> None:
    events, _ = _events(tmp_path)
    ev = events[DEN_SF]
    ev.starts = {"2026-10-04T16:00"}  # placeholder kickoff
    _, by_day = _index(SF_DEN)
    assert _match_event(ev, {}, by_day) is not None
    twin = _entry("2026-10-04T23:00:00Z", "SF", "DEN", "San Francisco 49ers", "Denver Broncos")
    _, by_day = _index(SF_DEN, twin)
    assert _match_event(ev, {}, by_day) is None


def test_near_start_places_a_game_across_the_utc_day_edge(tmp_path: Path) -> None:
    """DKEX 22:00 UTC, Optic 00:00 the next day: the same game, two hours apart."""
    events, _ = _events(tmp_path)
    ev = events[DEN_SF]
    ev.starts = {"2026-10-04T22:00"}
    late = _entry("2026-10-05T00:00:00Z", "SF", "DEN", "San Francisco 49ers", "Denver Broncos")
    _, by_day = _index(late)
    assert _match_event(ev, {}, by_day) is not None
    # The next game of a series, a day later, is not in the window.
    _, by_day = _index(late, _entry(
        "2026-10-05T21:00:00Z", "SF", "DEN", "San Francisco 49ers", "Denver Broncos"))
    assert _match_event(ev, {}, by_day) is not None
    # Two games inside the window (a doubleheader) leave the event unplaced.
    _, by_day = _index(late, _entry(
        "2026-10-05T01:00:00Z", "SF", "DEN", "San Francisco 49ers", "Denver Broncos"))
    assert _match_event(ev, {}, by_day) is None


def test_near_start_does_not_reach_past_three_hours(tmp_path: Path) -> None:
    events, _ = _events(tmp_path)
    ev = events[DEN_SF]
    ev.starts = {"2026-10-04T19:00"}
    far = _entry("2026-10-05T00:00:00Z", "SF", "DEN", "San Francisco 49ers", "Denver Broncos")
    _, by_day = _index(far)
    assert _match_event(ev, {}, by_day) is None


def test_cbj_resolves_by_its_optic_id_where_the_name_rule_cannot() -> None:
    """Optic's canonical code is CBJ3 and "CBJ" is no prefix of Columbus."""
    fx = SimpleNamespace(
        home="CBJ3", away="PPI5", home_name="Columbus Blue Jackets",
        away_name="Pittsburgh Penguins",
        team_map={"B59FF9985C9C": "CBJ3", "3B83B74A4BD7": "PPI5"},
    )
    assert _side_for("CBJ Blue Jackets", fx) == "CBJ3"
    assert _side_for("PIT Penguins", fx) == "PPI5"


def test_one_team_name_places_the_event_when_its_opponent_names_no_team_there(tmp_path: Path) -> None:
    """Exactly one same-minute fixture holds one event team; the other is the leftover side."""
    events, _ = _events(tmp_path)
    oddly_named = _entry("2026-10-04T20:25:00Z", "SF", "DEN", "Niners", "Denver Broncos")
    by_start, _ = _index(oddly_named)
    placed = _match_event(events[DEN_SF], by_start, {})
    assert placed is not None
    fixture, sides = placed
    assert fixture is oddly_named
    assert sorted(sides.values()) == ["DEN", "SF"]


def test_two_candidate_fixtures_leave_the_event_unplaced(tmp_path: Path) -> None:
    events, _ = _events(tmp_path)
    a = _entry("2026-10-04T20:25:00Z", "SF", "DEN", "Niners", "Denver Broncos")
    b = _entry("2026-10-04T20:25:00Z", "KC", "DEN", "Kansas City Chiefs", "Denver Broncos")
    by_start, _ = _index(a, b)
    assert _match_event(events[DEN_SF], by_start, {}) is None


# === End to end ===

def _run(tmp_path: Path, entries: list, rows: list[dict] | None = None):
    stamped: list = []

    def attach(_index, _alt, _all, dr) -> str:
        stamped.append(dr)
        return "stamped"

    tally = run_pass("nfl", NFL, entries, {}, [], _write_catalogue(tmp_path, rows), attach)
    return tally, stamped


def test_run_pass_stamps_teams_by_role_and_players_by_name(tmp_path: Path) -> None:
    tally, rows = _run(tmp_path, [SF_DEN, CLE_PIT])
    by_symbol: dict[str, list] = {}
    for r in rows:
        by_symbol.setdefault(r.dkex_symbol, []).append(r)
    den_win = by_symbol["NFL-WIN-FG-01S2KTKBIUCN390-DEOS024"]
    assert [(r.side, r.dkex_side) for r in den_win] == [("DEN", "yes"), ("SF", "no")]
    sf_movy = by_symbol["NFL-MOVY-FG-01S2KTKBIUCN390-SFRS000-GTE-P00035"]
    assert [(r.side, r.line) for r in sf_movy] == [("SF", -3.5), ("DEN", 3.5)]
    prey = by_symbol["NFL-PREY-FG-01S2LVEPIUCM13O-DEON230-GTE-P00195"]
    assert [(r.entity, r.side, r.line) for r in prey] == [
        ("denzel_boston", "over", 19.5), ("denzel_boston", "under", 19.5),
    ]
    # A quarter / half winner stamps only the team's own win; everything else is a pair.
    assert {k: len(v) for k, v in by_symbol.items() if len(v) != (1 if ("-WIN-Q" in k or "-WIN-H" in k) else 2)} == {}
    assert tally.matched_events == 2
    assert tally.swapped_events == 0
    # The props-only event (two FTD markets) has no roles to match on.
    assert tally.no_roles == 2


def test_run_pass_player_not_on_the_fixture_drops_the_market(tmp_path: Path) -> None:
    lean = replace_fixture_odds(CLE_PIT, [_odd("p2", "Aaron Rodgers")])
    _, rows = _run(tmp_path, [SF_DEN, lean])
    assert not [r for r in rows if r.entity == "denzel_boston"]
    assert [r for r in rows if r.entity == "aaron_rodgers"]


def test_run_pass_swapped_orientation_is_resolved_by_name(tmp_path: Path) -> None:
    """Optic has DEN home where DKEX says away: sides follow the names, and it is counted."""
    flipped = _entry("2026-10-04T20:25:00Z", "DEN", "SF", "Denver Broncos", "San Francisco 49ers")
    tally, rows = _run(tmp_path, [flipped])
    den_win = [r for r in rows if r.dkex_symbol == "NFL-WIN-FG-01S2KTKBIUCN390-DEOS024"]
    assert [(r.side, r.dkex_side) for r in den_win] == [("DEN", "yes"), ("SF", "no")]
    assert tally.swapped_events == 1


def replace_fixture_odds(entry: SimpleNamespace, odds: list) -> SimpleNamespace:
    fx = entry.fixture
    return _entry(fx.start_date, fx.home, fx.away, fx.home_name, fx.away_name, odds)


def test_market_participant_outside_the_event_drops(tmp_path: Path) -> None:
    """A team market whose participant id is not one of the event's teams drops."""
    rows = [normalize(r, "api") for r in RAW]
    for r in rows:
        if r["symbol"] == "NFL-WIN-FG-01S2KTKBIUCN390-DEOS024":
            r["participant_id"] = "DKT_SOMEONE_ELSE"
    _, stamped = _run(tmp_path, [SF_DEN], rows)
    assert not [r for r in stamped if r.dkex_symbol == "NFL-WIN-FG-01S2KTKBIUCN390-DEOS024"]


# === Player resolution ===

def test_player_match_prefers_the_exact_name_over_a_combo_selection() -> None:
    """Optic also lists "Jalen Hurts + DeVonta Smith"; a loose fit would call that ambiguous."""
    from mappers.exchanges.dkex_players import PlayerPool

    fx = SimpleNamespace(odds=[
        _odd("p1", "Jalen Hurts"),
        _odd("p1", "Jalen Hurts + DeVonta Smith"),
        _odd("p2", "DeVonta Smith"),
    ])
    assert PlayerPool(fx).resolve("DKP_1", "Jalen Hurts") == "jalen_hurts"


def test_players_the_old_entity_code_confused_resolve_apart() -> None:
    """Matt Olson and Mauricio Dubon both derive MAON; by name they are distinct.

    Measured 2026-09-28: the symbol-code path stamped 34 of Matt Olson's
    DKEX contracts onto Mauricio Dubon's Optic rows.
    """
    from mappers.exchanges.dkex_players import PlayerPool

    pool = PlayerPool(SimpleNamespace(odds=[_odd("a", "Matt Olson"), _odd("b", "Mauricio Dubon")]))
    assert pool.resolve("DKP_A", "Matt Olson") == "matt_olson"
    assert pool.resolve("DKP_B", "Mauricio Dubon") == "mauricio_dubon"
    assert pool.resolve("DKP_C", "Nia Brodie") is None


def test_same_name_players_resolve_apart_by_position_tag() -> None:
    """DKEX "Elias Pettersson (F)" and "(D)" are two players.

    Optic 2026-10-08, fixture 20261008D732F616: "Elias Pettersson (C)" and
    "Elias Nils Pettersson".  Both DKEX participants used to fuzzy-match the
    longer legal name, folding the forward's props onto the defenceman.
    """
    from mappers.exchanges.dkex_players import PlayerPool

    pool = PlayerPool(SimpleNamespace(odds=[
        _odd("a", "Elias Pettersson (C)"), _odd("b", "Elias Nils Pettersson"),
    ]))
    assert pool.resolve("DKP_00VP8J2LIO", "Elias Pettersson (F)") == "elias_pettersson_(c)"
    assert pool.resolve("DKP_0392GLQM6G0G", "Elias Pettersson (D)") == "elias_nils_pettersson"


def test_two_participants_resolving_to_one_player_both_drop() -> None:
    """Brazil 2026-10-07: two different DKEX players both fuzzy-matched
    Optic's "Matheus França Silva".  At least one is wrong, so neither stands."""
    from mappers.exchanges.dkex_players import PlayerPool

    pool = PlayerPool(SimpleNamespace(odds=[
        _odd("a", "Matheus França Silva"), _odd("b", "Yuri Alberto Monteiro da Silva"),
    ]))
    clashes = pool.drop_collisions({
        "DKP_03PG572LE4": "Matheus Pereira da Silva",
        "DKP_03V2LHFOBT6G": "Matheuzinho Silva",
        "DKP_YURI": "Yuri Alberto Monteiro da Silva",
    })
    assert clashes == [("matheus_franca_silva", ["Matheus Pereira da Silva", "Matheuzinho Silva"])]
    assert pool.resolve("DKP_03PG572LE4", "Matheus Pereira da Silva") is None
    assert pool.resolve("DKP_03V2LHFOBT6G", "Matheuzinho Silva") is None
    assert pool.resolve("DKP_YURI", "Yuri Alberto Monteiro da Silva") == "yuri_alberto_monteiro_da_silva"


def test_distinct_players_are_not_a_collision() -> None:
    from mappers.exchanges.dkex_players import PlayerPool

    pool = PlayerPool(SimpleNamespace(odds=[
        _odd("a", "Elias Pettersson (C)"), _odd("b", "Elias Nils Pettersson"),
    ]))
    assert pool.drop_collisions({"F": "Elias Pettersson (F)", "D": "Elias Pettersson (D)"}) == []


# === Soccer club names ===
#
# DKEX writes the common short name, Optic the official one (staging
# 2026-09-29 vs Optic the same day).

from mappers.exchanges.dkex_names import club_short_fits  # noqa: E402


def test_club_short_name_fits_the_official_name() -> None:
    assert club_short_fits("Palmeiras", "SE Palmeiras")
    assert club_short_fits("Cruzeiro", "Cruzeiro EC")
    assert club_short_fits("Dortmund", "BV Borussia 09 Dortmund")
    assert club_short_fits("Tottenham", "Tottenham Hotspur FC")
    assert club_short_fits("Atletico Mineiro", "Clube Atlético Mineiro")
    assert club_short_fits("Man City", "Manchester City FC")
    assert club_short_fits("Gremio Porto Alegre", "Grêmio FB Porto Alegrense")
    # Apostrophes and letters Unicode does not decompose (ł, ø, ß) fold too.
    assert club_short_fits("Newells Old Boys", "Newell's Old Boys")
    assert club_short_fits("Jagiellonia Bialystok", "SSA Jagiellonia Białystok")
    # "Utd" is "United" (EFL Championship, staging 2026-09-29).
    assert club_short_fits("Sheffield Utd", "Sheffield United FC")
    assert club_short_fits("Man Utd", "Manchester United FC")


def test_club_short_name_rule_is_narrow() -> None:
    # Every DKEX word must land, in order.
    assert not club_short_fits("Real Madrid", "Real Sociedad de Fútbol")
    assert not club_short_fits("Botafogo RJ", "Botafogo FR")
    # "Atl" is an abbreviation, not the start of "Athletico": a tip alias.
    assert not club_short_fits("Atl Paranaense", "Club Athletico Paranaense")
    # A prefix needs three letters, and one word of four or more must match.
    assert not club_short_fits("RB Bragantino", "Red Bull Bragantino")
    assert not club_short_fits("FC", "Arsenal FC")
    # "Utd" is United, never another club in the same city.
    assert not club_short_fits("Man Utd", "Manchester City FC")
    assert not club_short_fits("Sheffield Utd", "Sheffield Wednesday FC")
    # A nickname is not an abbreviation: a tip alias.
    assert not club_short_fits("Wolves", "Wolverhampton Wanderers FC")


def test_short_name_fitting_both_sides_is_no_side() -> None:
    """Sao Paulo vs Santos: Optic's Santos is "Santos FC Sao Paulo"."""
    kw: dict[str, Any] = {"home": "SAO", "away": "SAN", "home_name": "São Paulo FC", "away_name": "Santos FC Sao Paulo"}
    assert team_side_for("Sao Paulo", club_short=True, **kw) is None
    assert team_side_for("Santos", club_short=True, **kw) == "SAN"


def test_short_club_rule_is_off_unless_asked() -> None:
    kw: dict[str, Any] = {"home": "PAL", "away": "BAH", "home_name": "SE Palmeiras", "away_name": "EC Bahia"}
    assert team_side_for("Palmeiras", **kw) is None
    assert team_side_for("Palmeiras", club_short=True, **kw) == "PAL"


def test_optic_id_pin_names_the_side_no_name_rule_fits() -> None:
    from mappers.exchanges.dkex_names import optic_id_side

    team_map = {"94CB52205FE40CB1": "WOL", "OTHER": "SHU"}
    assert optic_id_side("Wolves", team_map) == "WOL"
    assert optic_id_side("wolves ", team_map) == "WOL"
    assert optic_id_side("Wolves", {"OTHER": "SHU"}) is None
    assert optic_id_side("Not Pinned", team_map) is None


def test_fcs_names_no_rule_fits_resolve_by_optic_id() -> None:
    """The 2026-10-03 FCS misses: DKEX and Optic spell these schools apart."""
    from mappers.exchanges.dkex_names import optic_id_side

    # Arkansas-Pine Bluff @ Southern University, Optic 202610035622D5DB.
    team_map = {"E92D5ABFC445": "SOU", "70518837B5E5": "UAPB"}
    assert team_side_for("Southern University", home="SOU", away="UAPB",
                         home_name="Southern", away_name="Arkansas Pine Bluff") is None
    assert optic_id_side("Southern University", team_map) == "SOU"
    assert optic_id_side("Arkansas-Pine Bluff", team_map) == "UAPB"
    for name, optic_id in (
        ("Albany NY", "4505BACF6CF8"), ("ETSU", "386F83F6DAFE"),
        ("Nicholls State", "111B0E50F653"), ("St. Thomas MN", "ABB51CDF8C3F"),
        ("Central Connecticut State", "A79562960B7D"), ("Alcorn", "6D5A5DA16039"),
        ("East Texas A&M", "39CFDC90083D"),
    ):
        assert optic_id_side(name, {optic_id: "X", "OTHER": "Y"}) == "X"


def test_optic_id_pin_covers_both_rennes_competitors() -> None:
    from mappers.exchanges.dkex_names import optic_id_side

    assert optic_id_side("Stade Rennes", {"C9C064312E88": "REN"}) == "REN"
    assert optic_id_side("Stade Rennes", {"A7C018E79716": "REN"}) == "REN"
