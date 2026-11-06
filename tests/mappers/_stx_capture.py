"""The 2026-10-28 STX mapping-trial capture, loaded once for the STX tests.

STX: every open market on Ontario demo (``demo.stxapp.ca``) at 2026-10-28T11:43:44Z, identity and rule fields only,
plus ``GET /api/v1/events/{id}/players`` for four games. Optic: REST v3 ``/fixtures`` for the leagues and windows
covering those events (527 fixtures) and ``/fixtures/odds`` player selections for the same four games. Source:
workspace ``docs/stx/data_samples/2026-10-28-mapping-trial/`` (``fixture_join.json`` and ``team_table_learned.json``
are that trial's own outputs, kept to compare against).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from fetch.stx import load_markets_list, load_players, normalize
from mappers.exchanges.stx import StxMarket, market_from_row
from mappers.exchanges.stx_fixtures import OpticFixtureRef, fixture_from_record
from mappers.exchanges.stx_players import Roster, roster_from_payload
from mappers.exchanges.stx_run import read_optic_selections

DIR = Path(__file__).resolve().parents[1] / "fixtures" / "stx"
AS_OF = datetime(2026, 10, 28, 11, 43, 44, tzinfo=UTC)

GB_CAR_EVENT = "63c2c44a-5f92-4e56-8b3e-08447f695ba3"
GB_CAR_FIXTURE = "20261030CB911D38"
WSH_PHI_EVENT = "cafcaf26-2773-4ad0-a931-a849cb904ae6"
ATL_MIA_EVENT = "35a1d5c4-331b-430a-99a7-ac56cb2649b8"
UGA_FLA_EVENT = "77a25efc-f7b3-4c7d-b5b0-af7cdc414ec3"


def _json(name: str) -> Any:
    return json.loads((DIR / name).read_text(encoding="utf-8"))


@cache
def markets() -> tuple[StxMarket, ...]:
    """Every captured market, through the catalogue loader."""
    rows = load_markets_list(DIR / "stx_open_markets_identity_2026-10-28.json.gz")
    return tuple(m for r in rows if (m := market_from_row(normalize(r))) is not None)


@cache
def questions() -> dict[str, str]:
    """STX question text by market id. Tests only: the mapper never reads text."""
    rows = load_markets_list(DIR / "stx_open_markets_identity_2026-10-28.json.gz")
    return {r["market_id"]: r.get("question") or "" for r in rows}


@cache
def fixtures() -> tuple[OpticFixtureRef, ...]:
    """The captured Optic fixtures."""
    return tuple(
        f for r in _json("optic_fixtures_2026-10-28.json")["fixtures"] if (f := fixture_from_record(r)) is not None
    )


@cache
def rosters() -> dict[str, Roster | None]:
    """The four captured rosters by STX event id (UGA v FLA has none)."""
    return {k: roster_from_payload(v) for k, v in load_players(DIR / "stx_event_players_2026-10-28.json").items()}


@cache
def optic_players() -> dict[str, dict[str, dict[str, str]]]:
    """Optic player indexes for the four captured fixtures."""
    return read_optic_selections(_json("optic_player_selections_2026-10-28.json"))


def trial_join() -> dict[str, dict[str, Any]]:
    """The trial's own per-event join, by STX event id."""
    return {e["event_id"]: e for e in _json("fixture_join_2026-10-28.json")["events"]}


def trial_team_table() -> list[dict[str, Any]]:
    """The trial's learned team table (186 rows)."""
    return _json("team_table_learned_2026-10-28.json")


def player_selection_rows(game: str) -> list[dict[str, Any]]:
    """Captured Optic player-selection rows for one game (``"NFL GB v CAR"``)."""
    return _json("optic_player_selections_2026-10-28.json")["games"][game]["rows"]
