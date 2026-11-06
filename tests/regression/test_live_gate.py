"""Live gate verdict logic: corrections, incidents, report, exit codes."""

import json

import pytest

from regression import live_gate
from regression.project import project_all
from tests.regression.test_invariants import FLIPPED, GOOD, SYM_MCGEE, _tick


def _run(tmp_path, name, records, tick):
    raw = tmp_path / f"{name}.raw.jsonl"
    raw.write_text("".join(json.dumps(r) + "\n" for r in records))
    canon = tmp_path / f"{name}.jsonl"
    lines, _ = project_all(raw.read_text().splitlines())
    canon.write_text("".join(line + "\n" for line in lines))
    run = live_gate.Run.__new__(live_gate.Run)
    run.sha, run.tick, run.leagues = name, tick, ("ufc",)
    run.raw, run.canon = raw, canon
    return run


def _waivers(tmp_path):
    w = tmp_path / "waivers.toml"
    w.write_text("")
    return w


def test_introducing_the_flip_fails(tmp_path):
    tick = _tick(tmp_path)
    r = live_gate.gate_tick(
        _run(tmp_path, "base", GOOD, tick), _run(tmp_path, "cand", FLIPPED, tick), _waivers(tmp_path)
    )
    assert r.failed
    assert len(r.swaps) == 2 and r.corrections == 0
    assert len(r.inv.new) == 2


def test_fixing_the_flip_is_a_correction_and_passes(tmp_path):
    tick = _tick(tmp_path)
    r = live_gate.gate_tick(
        _run(tmp_path, "base", FLIPPED, tick), _run(tmp_path, "cand", GOOD, tick), _waivers(tmp_path)
    )
    assert r.corrections == 4 and r.unexplained == 0
    assert not r.failed
    assert len(r.inv.fixed) == 2


def test_new_rows_are_reported_not_gated(tmp_path):
    tick = _tick(tmp_path)
    r = live_gate.gate_tick(_run(tmp_path, "base", [], tick), _run(tmp_path, "cand", GOOD, tick), _waivers(tmp_path))
    assert r.added > 0 and r.unexplained == 0
    assert not r.failed
    assert "NEW ROWS" in r.report


def test_removed_rows_still_fail(tmp_path):
    tick = _tick(tmp_path)
    r = live_gate.gate_tick(_run(tmp_path, "base", GOOD, tick), _run(tmp_path, "cand", [], tick), _waivers(tmp_path))
    assert r.unexplained > 0 and r.added == 0
    assert r.failed


def test_same_bug_on_both_sides_passes_but_reports_it(tmp_path):
    tick = _tick(tmp_path)
    r = live_gate.gate_tick(
        _run(tmp_path, "base", FLIPPED, tick), _run(tmp_path, "cand", FLIPPED, tick), _waivers(tmp_path)
    )
    assert not r.failed
    assert len(r.inv.existing) == 2
    assert "ALREADY IN PROD" in r.report


def test_incident_expectations(tmp_path):
    tick = _tick(tmp_path)
    inc = {"id": "x", "expect": [{"sportsbook": "crypto_com", "contract": SYM_MCGEE, "selection": "Court McGee"}]}
    ok = live_gate.check_incidents({"x": _run(tmp_path, "g", GOOD, tick)}, [inc])
    bad = live_gate.check_incidents({"x": _run(tmp_path, "b", FLIPPED, tick)}, [inc])
    gone = live_gate.check_incidents({"x": _run(tmp_path, "e", [], tick)}, [inc])
    assert ok == []
    assert "mapped to ['Eric Nolan'], expected 'Court McGee'" in bad[0]
    assert "not mapped at all" in gone[0]


def test_repo_incidents_file_is_valid():
    incs = live_gate.load_incidents()
    assert any(i["id"] == "2026-09-29-crypto-ufc-side-flip" for i in incs)
    for i in incs:
        assert i["expect"] and i["leagues"]


def test_report_exit_code_and_artifacts(tmp_path):
    tick = _tick(tmp_path)
    r = live_gate.gate_tick(
        _run(tmp_path, "base", GOOD, tick), _run(tmp_path, "cand", FLIPPED, tick), _waivers(tmp_path)
    )
    out = tmp_path / "report"
    out.mkdir()
    assert live_gate.write_report(out, "cand", "base", "P_x", [r], [], []) == 1
    assert "FAIL - do not deploy" in (out / "report.md").read_text()
    summary = json.loads((out / "summary.json").read_text())
    assert summary["result"] == "fail"
    assert summary["ticks"][0]["new_violations"] == 2
    assert live_gate.write_report(out, "c", "b", "P_x", [], [], ["x: broken"]) == 1
    assert live_gate.write_report(out, "c", "b", "P_x", [], [], []) == 0


def test_infrastructure_failure_exits_2_not_1(monkeypatch):
    def boom(argv=None):
        raise RuntimeError("Gaia id not found for email mmmapper-regression@...")

    monkeypatch.setattr(live_gate, "main", boom)
    assert live_gate.entry() == 2
    monkeypatch.setattr(live_gate, "main", lambda argv=None: 1)
    assert live_gate.entry() == 1


def test_prune_cache_keeps_only_what_this_run_uses(tmp_path, monkeypatch):
    """CI carries ticks/ and canon/ between pipelines; anything this run does not use is dropped."""
    monkeypatch.setenv("MM_REGRESSION_CACHE", str(tmp_path))
    used, stale_tick, other_day = (
        tmp_path / "ticks" / d for d in ("2026-10-15/12_45", "2026-10-15/12_15", "2026-09-01/10_00")
    )
    for d in (used, stale_tick, other_day):
        d.mkdir(parents=True)
        (d / "materialized.json").write_text("{}")
    canon = tmp_path / "canon"
    canon.mkdir()
    run = live_gate.Run("abc1234", used, ())
    for f in (run.canon, run.raw, run.canon.with_suffix(".log"), canon / "old.2026-10-15_12_15.all.v1.jsonl"):
        f.write_text("x")
    (tmp_path / "wt" / "abc1234").mkdir(parents=True)

    removed = live_gate.prune_cache([used], [run])

    assert removed == 3
    assert used.is_dir() and not stale_tick.exists() and not other_day.parent.exists()
    assert sorted(p.name for p in canon.iterdir()) == sorted(
        p.name for p in (run.canon, run.raw, run.canon.with_suffix(".log"))
    )
    assert (tmp_path / "wt" / "abc1234").is_dir()


def test_slots_spread_full_ticks_before_one_league_incidents():
    runs = [{"idx": i, "leagues": lg} for i, lg in enumerate([[], [], [], [], ["ufc"], ["ufc"]])]
    live_gate.assign_slots(runs, 5)
    assert [r["slot"] for r in runs] == [1, 2, 3, 4, 5, 5]
    live_gate.assign_slots(runs, 1)
    assert {r["slot"] for r in runs} == {1}


SNAP = "2026-09-30T15:00"


def _fan_out_world(tmp_path, monkeypatch):
    """Every outside call of the gate faked: base maps GOOD, the candidate FLIPPED."""
    monkeypatch.setenv("MM_REGRESSION_CACHE", str(tmp_path / "cache"))
    tick = _tick(tmp_path)
    incident = {
        "id": "x",
        "reason": "r",
        "snapshot": SNAP,
        "leagues": ["ufc"],
        "expect": [{"sportsbook": "crypto_com", "contract": SYM_MCGEE, "selection": "Court McGee"}],
    }
    monkeypatch.setattr(live_gate, "sh", lambda *cmd, **kw: cmd[-1] + "\n")
    monkeypatch.setattr(live_gate, "short_sha", lambda ref: ref[:7])
    monkeypatch.setattr(live_gate, "live_sha", lambda project: "base000")
    monkeypatch.setattr(live_gate, "export_tip", lambda out, project: out.write_text("{}") and "P_x")
    monkeypatch.setattr(live_gate.materialize, "latest_snapshots", lambda *a, **kw: [SNAP])
    monkeypatch.setattr(live_gate, "load_incidents", lambda: [incident])
    monkeypatch.setattr(live_gate, "build_ticks", lambda snaps, incs, project: dict.fromkeys(snaps, tick))
    replayed = []

    def run_engine(run, env):
        replayed.append((run.sha, run.leagues))
        records = GOOD if run.sha.startswith("base") else FLIPPED
        run.raw.parent.mkdir(parents=True, exist_ok=True)
        run.raw.write_text("".join(json.dumps(r) + "\n" for r in records))
        lines, _ = project_all(run.raw.read_text().splitlines())
        run.canon.write_text("".join(line + "\n" for line in lines))
        return run

    monkeypatch.setattr(live_gate, "run_engine", run_engine)
    return replayed


def test_fan_out_reaches_the_same_verdict_as_one_process(tmp_path, monkeypatch):
    replayed = _fan_out_world(tmp_path, monkeypatch)
    plan_dir, runs, report = tmp_path / "plan", tmp_path / "runs", tmp_path / "report"
    assert live_gate.main(["--stage", "plan", "--candidate", "cand000", "--plan", str(plan_dir), "--slots", "3"]) == 0
    plan = json.loads((plan_dir / "plan.json").read_text())
    assert [(r["sha"], r["leagues"], r["slot"]) for r in plan["runs"]] == [
        ("base000", [], 1),
        ("cand000", [], 2),
        ("cand000", ["ufc"], 3),
    ]
    for slot in ("1", "2", "3"):
        args = ["--stage", "run", "--plan", str(plan_dir), "--runs", str(runs), "--slot", slot, "--slots", "3"]
        assert live_gate.main(args) == 0
    assert len(replayed) == 3  # one replay per run, each in its own slot

    code = live_gate.main(["--stage", "verdict", "--plan", str(plan_dir), "--runs", str(runs), "--out", str(report)])

    assert code == 1  # the candidate flips the fight
    summary = json.loads((report / "summary.json").read_text())
    assert summary["ticks"][0]["new_violations"] == 2
    assert summary["incident_failures"] == ["x: " + SYM_MCGEE + " mapped to ['Eric Nolan'], expected 'Court McGee'"]
    one = tmp_path / "one"
    assert live_gate.main(["--candidate", "cand000", "--out", str(one)]) == 1
    assert json.loads((one / "summary.json").read_text())["ticks"] == summary["ticks"]


def test_a_missing_run_output_is_a_gate_error_not_a_pass(tmp_path, monkeypatch):
    _fan_out_world(tmp_path, monkeypatch)
    plan_dir, runs = tmp_path / "plan", tmp_path / "runs"
    live_gate.main(["--stage", "plan", "--candidate", "cand000", "--plan", str(plan_dir), "--slots", "2"])
    live_gate.main(["--stage", "run", "--plan", str(plan_dir), "--runs", str(runs), "--slot", "1", "--slots", "2"])
    with pytest.raises(live_gate.GateError, match="did its run job finish"):
        live_gate.main(["--stage", "verdict", "--plan", str(plan_dir), "--runs", str(runs), "--out", str(tmp_path)])
    live_gate.main(["--stage", "run", "--plan", str(plan_dir), "--runs", str(runs), "--slot", "2", "--slots", "2"])
    (runs / "2" / "r1.tick.txt").write_text("optic_fixtures_odds=1705:000000000000\n")
    with pytest.raises(live_gate.GateError, match="read different ticks"):
        live_gate.main(["--stage", "verdict", "--plan", str(plan_dir), "--runs", str(runs), "--out", str(tmp_path)])
    with pytest.raises(live_gate.GateError, match="the plan has 2 slots"):
        live_gate.main(["--stage", "run", "--plan", str(plan_dir), "--runs", str(runs), "--slot", "1", "--slots", "5"])
