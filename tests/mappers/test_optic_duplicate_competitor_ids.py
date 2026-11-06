"""Optic odds citing a competitor record the fixture doesn't carry.

Optic keys a participant by a per-competition competitor RECORD (``id``),
not by the underlying entity (``base_id``): Bournemouth is "AFC Bournemouth"
F2CCF38E0A5A in the Premier League and "Bournemouth" CDE44712BC73 in Club
Friendlies, both base_id 3859.  A fixture's odds can cite a different record
of the same participant than the fixture's own competitor list, which used
to KeyError on ``team_map[odd.team_id]`` in build_rows and abort the entire
multi-league run (mappers.run maps every league in one process and writes
mappings only after the loop).

Both cases pinned below are real, from a BQ sweep on 2026-07-31:
  - Club Friendlies fixture 2026073021541BD6 listed Bournemouth as
    CDE44712BC73, while all 93 of its priced Bournemouth rows (moneyline +
    asian_handicap) carried 22A4CC8308D1.
  - ITF Women fixture 2026073188167D5A listed Jo-Yee Chan as
    683EF74AE5BA4918, while all 227 of her priced moneyline rows carried
    AB66162D2171FF06.
In both the odds' ``selection`` still held the fixture's own participant
name, which is what load_fixtures recovers the side from.  The odds payload
carries no base_id, so that name is the only signal available.

Optic can also omit ``team_id`` altogether on a plain 2-way moneyline: on
2026-08-06, 7 of 38 priced boxing_matches moneyline odds carried team_id=null
across four 2026-08-08 fights (Pickles vs Curtis, Coyle vs Beuke, Eales vs
Krasimirov, Axe vs Hickey) from Kalshi, DraftKings, FanDuel and BetMGM alike.
That tripped build_rows' ``assert odd.team_id is not None`` and aborted the
whole tick, so the same selection-name fallback now covers a missing id.
"""

import json
from dataclasses import replace

from mappers.exchanges.optic import Fixture, Odd, OpticConfig, build_rows, load_fixtures
from mappers.run import LEAGUES
from mappers.vocab.soccer_markets import SOCCER_OPTIC_TABLE_TYPES
from mappers.vocab.tennis_markets import TENNIS_OPTIC_TABLE_TYPES
from tests.mappers._combat_helpers import BOXING_OPTIC

CLF_OPTIC = LEAGUES["international_club_friendlies"].OPTIC
WC_OPTIC = LEAGUES["world_cup"].OPTIC
ITFW_OPTIC = OpticConfig(league_id="itf_women", table_types=dict(TENNIS_OPTIC_TABLE_TYPES))

# The real ids, so a future reader can trace these back to the incident.
BOU_FIXTURE_ID = "CDE44712BC73"
BOU_ODDS_ID = "22A4CC8308D1"
AUG_ID = "CEEFEF932E66"
CHAN_FIXTURE_ID = "683EF74AE5BA4918"
CHAN_ODDS_ID = "AB66162D2171FF06"
CHARNEY_ID = "72BC54F1C235EA74"


def _competitor(comp_id: str, name: str, abbreviation: str) -> dict:
    return {"id": comp_id, "name": name, "abbreviation": abbreviation}


def _write_game(tmp_path, league_id: str, home: dict, away: dict,
                odds: list[dict], filename: str = "optic.jsonl"):
    game = {
        "id": "FIX1",
        "game_id": "GAME1",
        "start_date": "2026-07-30T18:00:00Z",
        "status": "unplayed",
        "is_live": False,
        "home_competitors": [home],
        "away_competitors": [away],
        "league": {"id": league_id},
        "odds": odds,
        "source_ids": {},
    }
    path = tmp_path / filename
    path.write_text(json.dumps(game) + "\n", encoding="utf-8")
    return path


def _game_odd(market_id: str, selection: str, team_id: str | None, **kw) -> dict:
    return {
        "id": f"GAME1:book:{market_id}:{selection}",
        "market_id": market_id,
        "selection": selection,
        "team_id": team_id,
        "grouping_key": "default",
        **kw,
    }


def _only_fixture(index):
    (fixtures,) = index.values()
    (fixture,) = fixtures
    return fixture


# === load_fixtures: recover the odds-side record by participant name ===


def test_soccer_odds_record_resolves_to_the_home_side(tmp_path):
    """Club Friendlies: the odds' Bournemouth record maps to the fixture's."""
    path = _write_game(
        tmp_path, "international_-_club_friendlies",
        _competitor(BOU_FIXTURE_ID, "Bournemouth", "BOU"),
        _competitor(AUG_ID, "FC Augsburg", "AUG"),
        [
            _game_odd("moneyline", "Bournemouth", BOU_ODDS_ID),
            _game_odd("asian_handicap", "Bournemouth", BOU_ODDS_ID,
                      points=-1.5),
            _game_odd("moneyline", "FC Augsburg", AUG_ID),
        ],
    )
    fixture = _only_fixture(load_fixtures(path, CLF_OPTIC))

    assert fixture.team_map[BOU_ODDS_ID] == "BOU"
    # The fixture's own ids keep their mapping untouched.
    assert fixture.team_map[BOU_FIXTURE_ID] == "BOU"
    assert fixture.team_map[AUG_ID] == "AUG"

    rows, _, _ = build_rows(
        "2026-07-30T18:00:00Z", "BOU", "AUG", fixture, CLF_OPTIC,
        league="international_club_friendlies")
    assert [(r.market_type, r.side, r.line) for r in rows] == [
        ("moneyline_3way", "BOU", None),
        ("point_spread", "BOU", -1.5),
        ("moneyline_3way", "AUG", None),
    ]


def test_tennis_odds_record_resolves_through_abbr_overrides(tmp_path):
    """ITF Women: empty Optic abbreviations, so both the fixture record and
    the odds record must land on the pinned canonical code."""
    cfg = replace(ITFW_OPTIC, abbr_overrides={
        CHAN_FIXTURE_ID: "CHA3",
        CHARNEY_ID: "CHA4",
    })
    path = _write_game(
        tmp_path, "itf_women",
        _competitor(CHAN_FIXTURE_ID, "Jo-Yee Chan", ""),
        _competitor(CHARNEY_ID, "Piper Charney", ""),
        [
            _game_odd("moneyline", "Jo-Yee Chan", CHAN_ODDS_ID),
            _game_odd("moneyline", "Piper Charney", CHARNEY_ID),
        ],
    )
    fixture = _only_fixture(load_fixtures(path, cfg))

    assert fixture.team_map[CHAN_ODDS_ID] == "CHA3"

    rows, _, _ = build_rows(
        "2026-07-30T18:00:00Z", "CHA3", "CHA4", fixture, cfg,
        league="itf_women")
    assert [(r.market_type, r.side) for r in rows] == [
        ("moneyline", "CHA3"),
        ("moneyline", "CHA4"),
    ]


def test_unknown_record_with_a_foreign_name_is_not_claimed(tmp_path):
    """A name that matches neither side stays unmapped — never guessed onto
    whichever side happens to be left."""
    path = _write_game(
        tmp_path, "international_-_club_friendlies",
        _competitor(BOU_FIXTURE_ID, "Bournemouth", "BOU"),
        _competitor(AUG_ID, "FC Augsburg", "AUG"),
        [_game_odd("moneyline", "Nottingham Forest", "DEADBEEF")],
    )
    fixture = _only_fixture(load_fixtures(path, CLF_OPTIC))
    assert "DEADBEEF" not in fixture.team_map


def test_identical_side_names_resolve_nothing(tmp_path):
    """When both competitors normalize to the same name, no name match can
    tell them apart, so nothing is claimed."""
    path = _write_game(
        tmp_path, "international_-_club_friendlies",
        _competitor("H1", "Bournemouth", "BOU"),
        _competitor("A1", "bournemouth", "BOU2"),
        [_game_odd("moneyline", "Bournemouth", "UNKNOWN1")],
    )
    fixture = _only_fixture(load_fixtures(path, CLF_OPTIC))
    assert "UNKNOWN1" not in fixture.team_map


# === build_rows: fail safe when the name fallback missed ===


def _fixture(odds: list[Odd], home: str, away: str, team_map: dict,
             home_name: str | None = None,
             away_name: str | None = None) -> Fixture:
    return Fixture(
        fixture_id="FIX1", game_id="GAME1", sportradar_id=None,
        start_et="2026-07-30T14:00:00", start_date="2026-07-30T18:00:00Z",
        home=home, away=away,
        home_name=home_name or home, away_name=away_name or away,
        team_map=team_map, odds=odds, is_live=False,
    )


def _odd(market_id: str, selection: str, team_id: str | None, **kw) -> Odd:
    return Odd(
        id=f"GAME1:book:{market_id}:{selection}", market_id=market_id,
        selection=selection, team_id=team_id, grouping_key="default", **kw)


def test_unresolvable_team_id_drops_only_that_odd(capsys):
    """The fixture's other odds still map, and the run does not raise."""
    odds = [
        _odd("moneyline", "Bournemouth", "UNRESOLVED"),
        _odd("moneyline", "FC Augsburg", "AUG"),
    ]
    rows, odd_lookup, _ = build_rows(
        "2026-07-30T18:00:00Z", "BOU", "AUG",
        _fixture(odds, "BOU", "AUG", {"BOU": "BOU", "AUG": "AUG"}),
        CLF_OPTIC, league="international_club_friendlies")

    assert [(r.market_type, r.side) for r in rows] == [("moneyline_3way", "AUG")]
    assert set(odd_lookup) == {"GAME1:book:moneyline:FC Augsburg"}
    assert "UNRESOLVED" in capsys.readouterr().err


def test_player_prop_keeps_its_row_when_the_team_id_is_unknown():
    """Player props take their entity from the selection, never team_map, so
    an unknown record there must not cost us the row."""
    odds = [_odd("first_goal_scorer", "Lionel Messi", "UNRESOLVED",
                 selection_line=None, player_id="P1")]
    rows, _, _ = build_rows(
        "2026-07-30T18:00:00Z", "ESP", "ARG",
        _fixture(odds, "ESP", "ARG", {"ESP": "ESP", "ARG": "ARG"}),
        WC_OPTIC, league="world_cup")
    (row,) = rows
    assert (row.entity, row.side) == ("lionel_messi", "yes")


def test_draw_side_still_resolves_without_a_team_id():
    """Regression: the 3-way draw leg carries team_id=None and must keep
    mapping to the tie side rather than tripping the new guard."""
    odds = [_odd("moneyline", "Draw", None)]
    rows, _, _ = build_rows(
        "2026-07-30T18:00:00Z", "BOU", "AUG",
        _fixture(odds, "BOU", "AUG", {"BOU": "BOU", "AUG": "AUG"}),
        CLF_OPTIC, league="international_club_friendlies")
    (row,) = rows
    assert row.market_type == "moneyline_3way"
    assert row.side not in ("BOU", "AUG")


# === build_rows: odds shipped with no team_id at all ===


def _boxing_fixture(odds: list[Odd]) -> Fixture:
    """The Pickles vs Curtis shape: 2-way moneyline, pinned fighter codes."""
    return _fixture(odds, "BPI6", "MCA9",
                    {"BPI6_ID": "BPI6", "MCA9_ID": "MCA9"},
                    home_name="Billy Pickles", away_name="Max Curtis")


def test_missing_team_id_resolves_both_sides_by_selection_name():
    """The boxing incident: every priced side ships team_id=null, and both
    still map off the selection name."""
    odds = [
        _odd("moneyline", "Billy Pickles", None),
        _odd("moneyline", "Max Curtis", None),
    ]
    rows, _, _ = build_rows(
        "2026-08-08T18:00:00Z", "BPI6", "MCA9", _boxing_fixture(odds),
        BOXING_OPTIC, league="boxing_matches")
    assert [(r.market_type, r.side) for r in rows] == [
        ("moneyline", "BPI6"),
        ("moneyline", "MCA9"),
    ]


def test_missing_team_id_with_a_foreign_name_drops_only_that_odd(capsys):
    """A selection matching neither fighter is skipped, not guessed onto the
    side that happens to be left, and its sibling odd still maps."""
    odds = [
        _odd("moneyline", "Gradus Kraus", None),
        _odd("moneyline", "Max Curtis", None),
    ]
    rows, odd_lookup, _ = build_rows(
        "2026-08-08T18:00:00Z", "BPI6", "MCA9", _boxing_fixture(odds),
        BOXING_OPTIC, league="boxing_matches")

    assert [(r.market_type, r.side) for r in rows] == [("moneyline", "MCA9")]
    assert set(odd_lookup) == {"GAME1:book:moneyline:Max Curtis"}
    assert "Gradus Kraus" in capsys.readouterr().err


def test_missing_team_id_drops_when_both_names_are_the_same(capsys):
    """Identical participant names can't tell the sides apart, so a
    team_id-less odd is dropped rather than assigned to either."""
    fixture = _fixture(
        [_odd("moneyline", "Max Curtis", None)], "MCA9", "MCA8",
        {"A": "MCA9", "B": "MCA8"},
        home_name="Max Curtis", away_name="max curtis")
    rows, _, _ = build_rows(
        "2026-08-08T18:00:00Z", "MCA9", "MCA8", fixture, BOXING_OPTIC,
        league="boxing_matches")

    assert rows == []
    assert "no team_id" in capsys.readouterr().err


def test_shared_abbr_team_total_drops_both_not_raise(capsys):
    """Nantes/Nancy both resolving to NAN must not abort the league tick."""
    nantes, nancy = "NANTES_ID", "NANCY_ID"
    odds = [
        Odd(
            id="GAME1:nantes_under", market_id="team_total",
            selection="FC Nantes", team_id=nantes,
            grouping_key="fc_nantes:0.5", selection_line="under", points=0.5,
        ),
        Odd(
            id="GAME1:nancy_under", market_id="team_total",
            selection="AS Nancy-Lorraine", team_id=nancy,
            grouping_key="as_nancy-lorraine:0.5", selection_line="under",
            points=0.5,
        ),
        Odd(
            id="GAME1:nantes_ml", market_id="moneyline",
            selection="FC Nantes", team_id=nantes, grouping_key="default",
        ),
    ]
    cfg = OpticConfig(
        league_id="france_-_ligue_2",
        table_types=dict(SOCCER_OPTIC_TABLE_TYPES),
    )
    rows, odd_lookup, _ = build_rows(
        "2026-09-07T18:45:00Z", "NAN", "NAN",
        _fixture(
            odds, "NAN", "NAN", {nantes: "NAN", nancy: "NAN"},
            home_name="FC Nantes", away_name="AS Nancy-Lorraine",
        ),
        cfg, league="france_ligue_2",
    )
    assert all(row.market_type != "team_total" for row in rows)
    assert any(row.market_type == "moneyline_3way" for row in rows)
    assert "GAME1:nantes_under" not in odd_lookup
    assert "GAME1:nancy_under" not in odd_lookup
    assert "grouping_key collision" in capsys.readouterr().err
