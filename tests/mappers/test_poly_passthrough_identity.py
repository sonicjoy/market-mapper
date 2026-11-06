"""Optic Polymarket passthrough ids are dropped when the token's own question disagrees.

Real prod cases (2026-09-27, AI validator HIGH):
  * Pumas vs Atletico de San Luis: clob 4797…8654 "Nathan Silva: 1+ goals +
    assists" was on Optic's Jordan Silva player_goals_+_assists over 0.5.
  * Canadian Premier League: a "Inter Toronto FC vs. Pacific FC: Pacific FC
    O/U 4.5 Corners" token was on Optic's York United vs Inter Toronto game.
"""

from __future__ import annotations

import json
from pathlib import Path

from mappers.exchanges import polymarket
from mappers.exchanges.optic import Fixture, Odd
from mappers.poly_passthrough_identity import (
    bridge_by_clob,
    drop_mismatched_passthroughs,
    player_fits,
    question_player,
    question_teams,
)
from mappers.shared import CanonicalRow

_PLAYER_TYPES = frozenset({"player_goals_or_assist", "player_shots"})


def _fixture(game_id: str, home: str, away: str, home_name: str, away_name: str) -> Fixture:
    return Fixture(
        fixture_id=f"f-{game_id}", game_id=game_id, sportradar_id=None,
        start_et="2026-09-27T14:00:00", start_date="2026-09-27T18:00:00Z",
        home=home, away=away, home_name=home_name, away_name=away_name,
        team_map={}, odds=[], is_live=False,
    )


def _odd(odd_id: str, selection: str, clob: str) -> Odd:
    return Odd(
        id=odd_id, market_id=odd_id.split(":")[1], selection=selection,
        grouping_key="default",
        source_ids={"Polymarket": {"selection_id": clob}, "Kalshi": {"market_id": "K"}},
    )


def _row(odd: Odd, market_type: str, entity: str | None, fx: Fixture) -> CanonicalRow:
    return CanonicalRow(
        league="x", start_date=fx.start_date, home=fx.home, away=fx.away,
        market_type=market_type, entity=entity, line=0.5, side="over",
        optic_id=odd.id,
    )


def _bridge(clob: str, question: str) -> dict[str, polymarket.PolyMarket]:
    market = polymarket.PolyMarket(
        condition_id="c", slug="s", question=question,
        outcomes=[polymarket.PolyOutcome(
            clob_token_id=clob, position_id="p", outcome_label="Yes", outcome_index=0,
        )],
    )
    return {clob: market}


def _run(rows, odds, bridge, fixtures, aliases=None):
    return drop_mismatched_passthroughs(
        rows, {o.id: o for o in odds}, bridge, fixtures,
        league="x", player_types=_PLAYER_TYPES,
        player_aliases=aliases or {}, style="mlb_suffix",
    )


_PUMAS = _fixture("19260-72234-2026-09-27", "PUM", "ASL",
                  "Pumas de la Universidad Nacional Autonoma de Mexico",
                  "Atletico de San Luis")


def test_question_player_and_teams():
    assert question_player("Nathan Silva: 1+ goals + assists") == "Nathan Silva"
    assert question_player("Inter Toronto FC vs. Pacific FC: Pacific FC O/U 4.5") is None
    assert question_player("Will it rain?") is None
    assert question_teams("Inter Toronto FC vs. Pacific FC: Pacific FC O/U 4.5 Corners") == (
        "Inter Toronto FC", "Pacific FC")
    assert question_teams("Bonn: Tom Gentzsch vs Max Dahlin") == ("Tom Gentzsch", "Max Dahlin")
    assert question_teams("Browns Team Total: O/U 30.5") is None


def test_player_fits_accepts_spelling_and_suffix_variants():
    assert player_fits("A.J. Brown", "AJ Brown", "aj_brown", {})
    assert player_fits("Marvin Harrison Jr.", "Marvin Harrison", "marvin_harrison", {})
    assert player_fits("Juan Martin", "Juan Cruz Martin Manzano", "juan_cruz_martin_manzano", {})
    assert not player_fits("Nathan Silva", "Jordan Silva", "jordan_silva", {})


def test_player_fits_honours_tip_alias():
    aliases = {"kc_concepcion": "kevin_concepcion"}
    assert not player_fits("KC Concepcion Jr.", "Kevin Concepcion", "kevin_concepcion", {})
    assert player_fits("KC Concepcion Jr.", "Kevin Concepcion", "kevin_concepcion", aliases)


def test_wrong_player_passthrough_is_dropped(capsys):
    clob = "47976589694443183285714565779033358686972797188629406693785327036429546608654"
    odd = _odd(f"{_PUMAS.game_id}:player_goals_+_assists:jordan_silva_over_0_5",
               "Jordan Silva", clob)
    row = _row(odd, "player_goals_or_assist", "jordan_silva", _PUMAS)
    stats = _run([row], [odd], _bridge(clob, "Nathan Silva: 1+ goals + assists"), [_PUMAS])
    assert "Polymarket" not in odd.source_ids
    assert odd.source_ids == {"Kalshi": {"market_id": "K"}}
    assert (stats.dropped_player, stats.verified) == (1, 0)
    assert "(player): Optic 'Jordan Silva'" in capsys.readouterr().err


def test_same_player_passthrough_is_kept():
    odd = _odd(f"{_PUMAS.game_id}:player_shots:jordan_silva_over_0_5", "Jordan Silva", "c1")
    row = _row(odd, "player_shots", "jordan_silva", _PUMAS)
    stats = _run([row], [odd], _bridge("c1", "Jordan Silva: 1+ shots"), [_PUMAS])
    assert "Polymarket" in odd.source_ids
    assert stats.verified == 1


def test_token_missing_from_bridge_is_kept_unverified():
    odd = _odd(f"{_PUMAS.game_id}:player_shots:jordan_silva_over_0_5", "Jordan Silva", "c1")
    row = _row(odd, "player_shots", "jordan_silva", _PUMAS)
    stats = _run([row], [odd], {}, [_PUMAS])
    assert "Polymarket" in odd.source_ids
    assert stats.unverified == 1


_YORK = _fixture("27563-20919-2026-09-27", "YOR", "ITO", "York United FC", "Inter Toronto FC")
_PACIFIC = _fixture("27563-11111-2026-09-27", "ITO", "PAC", "Inter Toronto FC", "Pacific FC")


def test_token_for_another_fixture_is_dropped():
    odd = _odd(f"{_YORK.game_id}:team_total_corners:pacific_fc_over_4_5", "Pacific FC", "c2")
    row = _row(odd, "team_total_corners", "PAC", _YORK)
    question = "Inter Toronto FC vs. Pacific FC: Pacific FC O/U 4.5 Corners"
    stats = _run([row], [odd], _bridge("c2", question), [_YORK, _PACIFIC])
    assert "Polymarket" not in odd.source_ids
    assert stats.dropped_fixture == 1


def test_fixture_name_drift_alone_is_not_evidence():
    # Poly says "Pumas UNAM"; Optic's long legal name shares no containment,
    # and no other fixture in the run matches either: keep the passthrough.
    odd = _odd(f"{_PUMAS.game_id}:total_corners:over_9_5", "Over", "c3")
    row = _row(odd, "total_corners", None, _PUMAS)
    stats = _run([row], [odd], _bridge("c3", "Pumas UNAM vs. San Luis: O/U 9.5 Corners"),
                 [_PUMAS])
    assert "Polymarket" in odd.source_ids
    assert stats.verified == 1


def test_bridge_index_reads_every_prefix(tmp_path: Path):
    line = {
        "condition_id": "c", "slug": "cpl-ito-pac-2026-09-27", "question": "q",
        "outcomes": [
            {"clob_token_id": "a", "position_id": "p", "outcome_label": "Yes", "outcome_index": 0},
            {"clob_token_id": "b", "position_id": "p", "outcome_label": "No", "outcome_index": 1},
        ],
    }
    (tmp_path / "polymarket_markets.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    index = bridge_by_clob(tmp_path, None)
    assert set(index) == {"a", "b"}
    assert index["a"].slug == "cpl-ito-pac-2026-09-27"
