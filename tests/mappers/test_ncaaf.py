"""NCAAF tip wiring — Optic + crypto.com (CFB)."""

import os
from pathlib import Path

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from mappers.seed.fixture_store import load_fixture
from mappers.seed.tip_factories import build_tip_league
from mappers.sport import Sport
from mappers.vocab.football_markets import (
    FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES,
    NCAAF_CRYPTO,
)


def _tip_cfg():
    snap = load_fixture()
    row = next(r for r in snap.leagues if r.league == "ncaaf")
    return build_tip_league(row)


def test_ncaaf_tip_builds_football_config():
    cfg = _tip_cfg()
    assert cfg.league == "ncaaf"
    assert cfg.sport == Sport.FOOTBALL
    assert cfg.OPTIC.league_id == "ncaaf"
    assert cfg.OPTIC.horizon_hours == 24 * 14
    assert cfg.CRYPTO is not None
    assert cfg.PX is None
    assert cfg.POLYMARKET is None


def test_ncaaf_optic_and_crypto():
    cfg = _tip_cfg()
    assert cfg.OPTIC.table_types == FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES
    assert cfg.CRYPTO is not None
    assert cfg.CRYPTO.league == "CFB"
    assert cfg.CRYPTO.sport_grouping == "CFB"
    assert cfg.CRYPTO.period_type == "Full-Game"
    assert cfg.CRYPTO is not None
    assert cfg.CRYPTO.contract_types == NCAAF_CRYPTO.contract_types


def test_ncaaf_spine_has_period_and_player_ids():
    rows = [
        line.split(",")
        for line in (
            Path(__file__).resolve().parents[2]
            / "docs" / "mapping-rules" / "optic_spine.csv"
        ).read_text(encoding="utf-8").splitlines()
        if line.startswith("ncaaf,")
    ]
    ids = {row[2] for row in rows}
    assert {"moneyline", "point_spread", "total_points"} <= ids
    assert {"1st_half_moneyline_3-way", "1st_half_team_total", "team_total", "player_passing_yards"} <= ids
    intercept = next(row for row in rows if row[2] == "player_interceptions")
    assert intercept[6] == ""
    passing = next(row for row in rows if row[2] == "player_passing_yards")
    assert passing[6] == ""
    team_total = next(row for row in rows if row[2] == "team_total")
    assert team_total[6] == "TEAMTOTAL"
