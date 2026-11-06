"""One league's bad data must not cost every other league its rows.

mappers.run maps every scheduled league (serial or process pool) and writes
mappings only after all leagues finish, so any exception used to abort the
whole tick: on 2026-08-06 a boxing moneyline odd that Optic shipped with no
team_id asserted in optic.build_rows and no league was mapped or loaded
to BigQuery for hours.  The run now alerts and carries on, and only
exits non-zero when nothing at all could be mapped — infra/run_pipeline.sh
runs under `set -e`, so a non-zero exit would skip the BigQuery load and
discard the leagues that did map.
"""

import json

import pytest

from mappers import pipeline, run
from mappers.pipeline import PipelineResult
from mappers.shared import CanonicalRow

GOOD = "cfl"
BAD = "boxing_matches"


def _canonical_row():
    return CanonicalRow(
        league=GOOD, start_date="2026-08-08", home="BC", away="HAM",
        market_type="moneyline", entity=None, line=None, side="BC",
    )


def _fake_run(bad: set[str]):
    def fake(_data_dir, league, orphan_dist=5, **_kwargs):
        if str(league.league) in bad:
            raise AssertionError("optic odd with no team_id")
        return PipelineResult(
            rows=[_canonical_row()], odd_lookup={}, game_ref_lookup={},
        )
    return fake


def test_failing_league_alerts_and_the_others_still_map(
        tmp_path, monkeypatch, capsys):
    # Serial path: ProcessPool workers would not see this monkeypatch.
    monkeypatch.setenv("MAP_LEAGUE_WORKERS", "1")
    monkeypatch.setattr(pipeline, "run", _fake_run({BAD}))
    monkeypatch.setattr(
        "sys.argv",
        ["mappers.run", str(tmp_path), "--league", BAD, GOOD,
         "--write-mappings"])

    run.main()

    written = [json.loads(line) for line
               in (tmp_path / "mappings.jsonl").read_text().splitlines()]
    assert [(r["key"]["league"], r["key"]["market_type"]) for r in written] \
        == [(GOOD, "moneyline")]
    err = capsys.readouterr().err
    assert f"ALERT: {BAD} mapping failed" in err
    # Cause stays on the ALERT: line (Slack greps that) and in the
    # traceback (full log).
    alert_line = next(line for line in err.splitlines()
                      if line.startswith("ALERT:"))
    assert "AssertionError: optic odd with no team_id" in alert_line
    assert "optic odd with no team_id" in err


def test_every_league_failing_exits_non_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("MAP_LEAGUE_WORKERS", "1")
    monkeypatch.setattr(pipeline, "run", _fake_run({BAD, GOOD}))
    monkeypatch.setattr(
        "sys.argv",
        ["mappers.run", str(tmp_path), "--league", BAD, GOOD,
         "--write-mappings"])

    with pytest.raises(SystemExit) as exc:
        run.main()

    assert exc.value.code == 1
    assert not (tmp_path / "mappings.jsonl").exists()


def test_map_league_step_emitted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAP_LEAGUE_WORKERS", "1")
    monkeypatch.setattr(pipeline, "run", _fake_run(set()))
    monkeypatch.setattr(
        "sys.argv",
        ["mappers.run", str(tmp_path), "--league", GOOD, "--write-mappings"])

    run.main()

    err = capsys.readouterr().err
    assert f"STEP name=map_league league={GOOD} " in err
    assert " rows=1" in err


def test_map_league_workers_env(monkeypatch):
    monkeypatch.delenv("MAP_LEAGUE_WORKERS", raising=False)
    assert run.map_league_workers() == 4
    monkeypatch.setenv("MAP_LEAGUE_WORKERS", "2")
    assert run.map_league_workers() == 2
    monkeypatch.setenv("MAP_LEAGUE_WORKERS", "0")
    assert run.map_league_workers() == 1
    monkeypatch.setenv("MAP_LEAGUE_WORKERS", "nope")
    assert run.map_league_workers() == 4
