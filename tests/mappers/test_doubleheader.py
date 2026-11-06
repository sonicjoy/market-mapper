"""Same-day doubleheader matching: Optic keeps both games; crypto time-aligns."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from mappers.exchanges.optic import OpticConfig, load_fixtures
from mappers.pipeline import (
    ScheduleEntry,
    _pick_entry_by_time,
    _unique_entry,
    run,
)
from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.shared import MatchKey


def _mlb_cfg():
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == "mlb")
    return build_tip_league(row)


def _optic_game(
    *,
    game_id: str,
    fixture_id: str,
    start_date: str,
    home_abbr: str = "BOS",
    away_abbr: str = "TB",
    home_name: str = "Boston Red Sox",
    away_name: str = "Tampa Bay Rays",
    status: str = "unplayed",
    is_live: bool = False,
) -> dict:
    home_id = f"{fixture_id}-home"
    away_id = f"{fixture_id}-away"
    return {
        "id": fixture_id,
        "game_id": game_id,
        "start_date": start_date,
        "status": status,
        "is_live": is_live,
        "league": {"id": "mlb"},
        "home_competitors": [{
            "id": home_id,
            "name": home_name,
            "abbreviation": home_abbr,
        }],
        "away_competitors": [{
            "id": away_id,
            "name": away_name,
            "abbreviation": away_abbr,
        }],
        "odds": [
            {
                "id": f"{game_id}:moneyline:home",
                "market_id": "moneyline",
                "name": home_name,
                "selection": home_name,
                "normalized_selection": home_name,
                "selection_line": None,
                "points": None,
                "team_id": home_id,
                "grouping_key": "moneyline:ml",
            },
            {
                "id": f"{game_id}:moneyline:away",
                "market_id": "moneyline",
                "name": away_name,
                "selection": away_name,
                "normalized_selection": away_name,
                "selection_line": None,
                "points": None,
                "team_id": away_id,
                "grouping_key": "moneyline:ml",
            },
        ],
        "source_ids": {},
    }


_ALBION_GID = "10814-17438-2026-09-07"
_ALBION_START = "2026-09-07T18:00:00Z"


def _load_games(tmp_path: Path, games: list[dict]):
    path = tmp_path / "optic.jsonl"
    path.write_text(
        "\n".join(json.dumps(g) for g in games) + "\n", encoding="utf-8")
    return load_fixtures(path, OpticConfig(league_id="mlb", table_types={}))


def _listed(index, date: str = "2026-09-07"):
    return index.get(MatchKey(date, "BOS", "TB")) or []


def test_load_fixtures_keeps_same_day_doubleheader(tmp_path: Path):
    path = tmp_path / "optic.jsonl"
    g1 = _optic_game(
        game_id="39506-32800-2026-07-17-10",
        fixture_id="fix1",
        start_date="2026-07-17T17:35:00Z",
    )
    g2 = _optic_game(
        game_id="39506-32800-2026-07-17-16",
        fixture_id="fix2",
        start_date="2026-07-17T23:10:00Z",
    )
    path.write_text(
        json.dumps(g1) + "\n" + json.dumps(g2) + "\n", encoding="utf-8")

    cfg = OpticConfig(league_id="mlb", table_types={})
    index = load_fixtures(path, cfg)

    key = MatchKey("2026-07-17", "BOS", "TB")
    assert key in index
    assert len(index[key]) == 2
    game_ids = {f.game_id for f in index[key]}
    assert game_ids == {
        "39506-32800-2026-07-17-10",
        "39506-32800-2026-07-17-16",
    }


def test_collapse_prefers_live_clone(tmp_path: Path, capsys):
    """Albion: live old-prefix id wins over unplayed date-matching clone."""
    live = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="202609057767889F",
        start_date=_ALBION_START,
        status="live",
        is_live=True,
    )
    ghost = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="20260907261BED6B",
        start_date=_ALBION_START,
        status="unplayed",
    )
    listed = _listed(_load_games(tmp_path, [ghost, live]))
    assert len(listed) == 1
    assert listed[0].fixture_id == "202609057767889F"
    err = capsys.readouterr().err
    assert "collapse clone 20260907261BED6B" in err
    assert "202609057767889F" in err
    assert _ALBION_GID in err


def test_collapse_prefers_completed_over_unplayed(tmp_path: Path):
    """Albion after kickoff: completed board beats leftover unplayed clone."""
    done = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="202609057767889F",
        start_date=_ALBION_START,
        status="completed",
    )
    ghost = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="20260907261BED6B",
        start_date=_ALBION_START,
        status="unplayed",
    )
    listed = _listed(_load_games(tmp_path, [ghost, done]))
    assert [fx.fixture_id for fx in listed] == ["202609057767889F"]


def test_collapse_prefers_completed_over_delayed(tmp_path: Path):
    """Played board beats a leftover delayed clone (same kickoff)."""
    delayed = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="202609057767889F",
        start_date=_ALBION_START,
        status="delayed",
    )
    done = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="20260907261BED6B",
        start_date=_ALBION_START,
        status="completed",
    )
    listed = _listed(_load_games(tmp_path, [delayed, done]))
    assert [fx.fixture_id for fx in listed] == ["20260907261BED6B"]


def test_collapse_delayed_beats_unplayed(tmp_path: Path):
    delayed = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="202609057767889F",
        start_date=_ALBION_START,
        status="delayed",
    )
    ghost = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="20260907261BED6B",
        start_date=_ALBION_START,
        status="unplayed",
    )
    listed = _listed(_load_games(tmp_path, [ghost, delayed]))
    assert [fx.fixture_id for fx in listed] == ["202609057767889F"]


def test_collapse_unplayed_prefers_date_prefix(tmp_path: Path):
    old = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="202609057767889F",
        start_date=_ALBION_START,
    )
    new = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="20260907261BED6B",
        start_date=_ALBION_START,
    )
    listed = _listed(_load_games(tmp_path, [old, new]))
    assert [fx.fixture_id for fx in listed] == ["20260907261BED6B"]


def test_collapse_cancelled_loses_to_unplayed(tmp_path: Path):
    cancelled = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="202609057767889F",
        start_date=_ALBION_START,
        status="cancelled",
    )
    unplayed = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="20260907261BED6B",
        start_date=_ALBION_START,
        status="unplayed",
    )
    listed = _listed(_load_games(tmp_path, [cancelled, unplayed]))
    assert [fx.fixture_id for fx in listed] == ["20260907261BED6B"]


def test_collapse_keeps_sole_cancelled(tmp_path: Path):
    only = _optic_game(
        game_id=_ALBION_GID,
        fixture_id="20260907261BED6B",
        start_date=_ALBION_START,
        status="cancelled",
    )
    listed = _listed(_load_games(tmp_path, [only]))
    assert [fx.fixture_id for fx in listed] == ["20260907261BED6B"]


def test_pick_entry_by_time_chooses_nearest_tipoff():
    class _Fix:
        def __init__(self, start_date: str, game_id: str):
            self.start_date = start_date
            self.game_id = game_id

    early = ScheduleEntry(_Fix("2026-07-17T17:35:00Z", "early"))  # type: ignore[arg-type]
    late = ScheduleEntry(_Fix("2026-07-17T23:10:00Z", "late"))  # type: ignore[arg-type]

    assert _pick_entry_by_time(
        [early, late], "2026-07-17T17:35:00+00:00"
    ).fixture.game_id == "early"
    assert _pick_entry_by_time(
        [early, late], "2026-07-17T23:10:00Z"
    ).fixture.game_id == "late"


def test_unique_entry_skips_ambiguous_doubleheader():
    class _Fix:
        def __init__(self, game_id: str):
            self.game_id = game_id
            self.start_date = "2026-07-17T17:35:00Z"

    a = ScheduleEntry(_Fix("a"))  # type: ignore[arg-type]
    b = ScheduleEntry(_Fix("b"))  # type: ignore[arg-type]
    assert _unique_entry([a]) is a
    assert _unique_entry([a, b]) is None
    assert _unique_entry([]) is None


def test_crypto_doubleheader_maps_to_distinct_start_dates(tmp_path: Path):
    """Two crypto EXTERNAL_GAME_IDs attach to two Optic tip-offs."""
    data = tmp_path / "2026-07-16" / "09_39"
    data.mkdir(parents=True)

    g1 = _optic_game(
        game_id="39506-32800-2026-07-17-10",
        fixture_id="fix-early",
        start_date="2026-07-17T17:35:00Z",
    )
    g2 = _optic_game(
        game_id="39506-32800-2026-07-17-16",
        fixture_id="fix-late",
        start_date="2026-07-17T23:10:00Z",
    )
    (data / "optic_fixtures_odds.jsonl").write_text(
        json.dumps(g1) + "\n" + json.dumps(g2) + "\n", encoding="utf-8")

    def crypto_sel(
        *,
        security_id: str,
        symbol: str,
        egid: str,
        start: str,
        outcome: str,
        participant: str,
    ) -> dict:
        return {
            "SecurityID": security_id,
            "Symbol": symbol,
            "eventName": f"{participant} to win",
            "eventMetaEXTERNAL_GAME_ID": egid,
            "eventMetaLEAGUE": "MLB",
            "eventMetaSPORTS_GROUPING": "MLB",
            "eventMetaEVENT_DATE": start,
            "eventMetaPREDICT_MARKET_TYPE": "Game Line",
            "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline",
            "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
            "eventMetaPREDICT_EVENT_TYPE": "Game",
            "eventMetaPREDICT_OUTCOME_TYPE": outcome,
            "eventMetaPREDICT_MARKET_ID": f"mkt-{egid}",
            "eventMetaPREDICT_OUTCOME_ID": f"out-{security_id}",
            "eventMetaPARTICIPANT": participant,
            "eventMetaEXTERNAL_HOME_ID": "10000025",
            "eventMetaEXTERNAL_AWAY_ID": "10000011",
            "eventMetaHOME_PARTICIPANT": "Boston Red Sox",
            "eventMetaAWAY_PARTICIPANT": "Tampa Bay Rays",
            "eventMetaPREDICT_VALUE": "",
        }

    crypto_rows = [
        crypto_sel(
            security_id="sec-early-away",
            symbol="NX.F.OPT.MLB-00001-260717-M.O.1.1",
            egid="10079725",
            start="2026-07-17T17:35:00+00:00",
            outcome="Away",
            participant="Tampa Bay Rays",
        ),
        crypto_sel(
            security_id="sec-early-home",
            symbol="NX.F.OPT.MLB-00001-260717-M.O.1.2",
            egid="10079725",
            start="2026-07-17T17:35:00+00:00",
            outcome="Home",
            participant="Boston Red Sox",
        ),
        crypto_sel(
            security_id="sec-late-away",
            symbol="NX.F.OPT.MLB-00003-260717-M.O.1.1",
            egid="10078741",
            start="2026-07-17T23:10:00+00:00",
            outcome="Away",
            participant="Tampa Bay Rays",
        ),
        crypto_sel(
            security_id="sec-late-home",
            symbol="NX.F.OPT.MLB-00003-260717-M.O.1.2",
            egid="10078741",
            start="2026-07-17T23:10:00+00:00",
            outcome="Home",
            participant="Boston Red Sox",
        ),
    ]
    (data / "crypto_com_markets.jsonl").write_text(
        "\n".join(json.dumps(r) for r in crypto_rows) + "\n",
        encoding="utf-8",
    )
    (data / "prophetx_events.jsonl").write_text("", encoding="utf-8")
    (data / "prophetx_markets.jsonl").write_text("", encoding="utf-8")
    (data / "kalshi_markets.jsonl").write_text("", encoding="utf-8")

    result = run(data, _mlb_cfg())
    crypto_ml = [
        r for r in result.rows
        if r.crypto_security_id is not None and r.market_type == "moneyline"
    ]
    starts = {(r.start_date, r.side, r.optic_game_id) for r in crypto_ml}
    assert ("2026-07-17T17:35:00Z", "BOS", "39506-32800-2026-07-17-10") in starts
    assert ("2026-07-17T17:35:00Z", "TB", "39506-32800-2026-07-17-10") in starts
    assert ("2026-07-17T23:10:00Z", "BOS", "39506-32800-2026-07-17-16") in starts
    assert ("2026-07-17T23:10:00Z", "TB", "39506-32800-2026-07-17-16") in starts

    keys = {
        (r.start_date, r.home, r.away, r.market_type, r.side)
        for r in crypto_ml
    }
    assert len(keys) == len(crypto_ml) == 4


def test_crypto_stale_vintage_reschedule_uses_freshest_time(tmp_path: Path):
    """Group time comes from the freshest listing, not scan order.

    After a doubleheader reschedule the catalogue keeps stale vintages
    whose EVENT_DATE is the *old* start time.  On PIT@CLE 2026-07-18,
    Game 2 (moved 20:10 -> 23:10) still had 46 stale records saying
    20:10 — exactly halfway between the two fixtures — and scan-order
    sels[0] attached Game 2 to Game 1's 17:10 fixture.  The freshest
    listing (max security_id = latest issuance) carries the current
    schedule, so the group must time-align from it.
    """
    data = tmp_path / "2026-07-18" / "03_00"
    data.mkdir(parents=True)

    g1 = _optic_game(
        game_id="39506-32800-2026-07-18-10",
        fixture_id="fix-early",
        start_date="2026-07-18T17:10:00Z",
    )
    g2 = _optic_game(
        game_id="39506-32800-2026-07-18-16",
        fixture_id="fix-late",
        start_date="2026-07-18T23:10:00Z",
    )
    (data / "optic_fixtures_odds.jsonl").write_text(
        json.dumps(g1) + "\n" + json.dumps(g2) + "\n", encoding="utf-8")

    def crypto_sel(
        *,
        security_id: str,
        symbol: str,
        egid: str,
        start: str,
        outcome: str,
        participant: str,
    ) -> dict:
        return {
            "SecurityID": security_id,
            "Symbol": symbol,
            "eventName": f"{participant} to win",
            "eventMetaEXTERNAL_GAME_ID": egid,
            "eventMetaLEAGUE": "MLB",
            "eventMetaSPORTS_GROUPING": "MLB",
            "eventMetaEVENT_DATE": start,
            "eventMetaPREDICT_MARKET_TYPE": "Game Line",
            "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline",
            "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
            "eventMetaPREDICT_EVENT_TYPE": "Game",
            "eventMetaPREDICT_OUTCOME_TYPE": outcome,
            "eventMetaPREDICT_MARKET_ID": f"mkt-{egid}",
            "eventMetaPREDICT_OUTCOME_ID": f"out-{security_id}",
            "eventMetaPARTICIPANT": participant,
            "eventMetaEXTERNAL_HOME_ID": "10000025",
            "eventMetaEXTERNAL_AWAY_ID": "10000011",
            "eventMetaHOME_PARTICIPANT": "Boston Red Sox",
            "eventMetaAWAY_PARTICIPANT": "Tampa Bay Rays",
            "eventMetaPREDICT_VALUE": "",
        }

    # Game 1: single vintage at its true 17:10 tip-off.
    # Game 2: the stale vintage (old 20:10 time, halfway between the
    # fixtures) comes FIRST in scan order; the fresh re-issue (higher
    # security_id, same symbols so dedupe_superseded collapses the
    # pair) carries the rescheduled 23:10.
    crypto_rows = [
        crypto_sel(
            security_id="202607170000001D",
            symbol="NX.F.OPT.MLB-00001-260718-M.O.1.1",
            egid="10079725",
            start="2026-07-18T17:10:00+00:00",
            outcome="Home",
            participant="Boston Red Sox",
        ),
        crypto_sel(
            security_id="202607170000002D",
            symbol="NX.F.OPT.MLB-00008-260718-M.O.1.1",
            egid="10078755",
            start="2026-07-18T20:10:00+00:00",
            outcome="Home",
            participant="Boston Red Sox",
        ),
        crypto_sel(
            security_id="202607180000009D",
            symbol="NX.F.OPT.MLB-00008-260718-M.O.1.1",
            egid="10078755",
            start="2026-07-18T23:10:00+00:00",
            outcome="Home",
            participant="Boston Red Sox",
        ),
    ]
    (data / "crypto_com_markets.jsonl").write_text(
        "\n".join(json.dumps(r) for r in crypto_rows) + "\n",
        encoding="utf-8",
    )
    (data / "prophetx_events.jsonl").write_text("", encoding="utf-8")
    (data / "prophetx_markets.jsonl").write_text("", encoding="utf-8")
    (data / "kalshi_markets.jsonl").write_text("", encoding="utf-8")

    result = run(data, _mlb_cfg())
    crypto_ml = [
        r for r in result.rows
        if r.crypto_security_id is not None and r.market_type == "moneyline"
    ]
    attached = {(r.start_date, r.optic_game_id, r.crypto_security_id)
                for r in crypto_ml}
    assert attached == {
        ("2026-07-18T17:10:00Z", "39506-32800-2026-07-18-10",
         "202607170000001D"),
        # Game 2 sits on the LATE fixture, stamped with the fresh
        # vintage (dedupe_superseded keeps max security_id).
        ("2026-07-18T23:10:00Z", "39506-32800-2026-07-18-16",
         "202607180000009D"),
    }
