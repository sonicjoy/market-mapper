"""Pre-prod mapping gate: candidate vs the SHA live on prod, on prod's inputs.

One command, run by CI before any prod deploy of the mapper
(``regression:mapping-gate`` in ``.gitlab-ci.yml``).  It answers two
questions a code review cannot:

1. **What would this change do to the mappings we publish right now?**
   The newest prod fetch snapshots are rebuilt from BigQuery
   (``materialize.py``), the activated rules tip is exported once and
   pinned for both sides, and the candidate and the SHA prod is running
   (read from ``markets_us.market_mapping.mapper_git_commit``) both map
   them.  Every removed row must be explained by a reviewed waiver
   (``waivers.toml``) or the gate fails; a contract that moved to the
   opposite side (``swaps.py``) needs a ``side_swap`` waiver.  Added rows
   are new coverage: counted in the report, never gated (question 2
   judges them).
2. **Is anything it publishes wrong, whatever the baseline did?**
   The invariants (``invariants.py``) judge the candidate's output
   against the raw venue catalogues.  A violation the live SHA does not
   have fails the gate; one it shares is printed as ALREADY IN PROD.

Plus the permanent incident cases (``incidents.toml``): each replays the
snapshot that witnessed a past incident and asserts the correct mapping.

A swap that FIXES a flip is recognised: when every contract it moves is
one whose baseline mapping failed ``venue_label_swapped`` and whose
candidate mapping passes, it is reported as a CORRECTION, not a delta.

Exit 0 = safe to deploy.  1 = do not deploy (report says why).  2 = the
gate could not run (infrastructure) — also blocks the deploy; nothing
fails open.

In CI the replays are fanned out (``--stage``): ``plan`` resolves both SHAs,
pins the tip and picks the snapshots once (``plan.json``); one ``run`` job per
slot replays its share in parallel and hands back canonical rows, invariant
violations and incident results; ``verdict`` judges them.  A replay is mostly
serial and memory-bound (one per 12 GiB runner), so wall time is the slowest
replay instead of their sum.  ``--stage all`` (the default) does all three in
one process.

Usage:
    python -m regression.live_gate --candidate HEAD --out gate-report/
    python -m regression.live_gate --candidate HEAD --baseline 8959d90f
    python -m regression.live_gate --stage plan --candidate SHA --plan gate-plan --slots 5
    python -m regression.live_gate --stage run --plan gate-plan --runs gate-runs --slot 3 --slots 5
    python -m regression.live_gate --stage verdict --plan gate-plan --runs gate-runs --out gate-report
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404 - runs git and run_engine.sh with fixed argv, never a shell
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from regression import invariants, materialize
from regression.gate_verdict import TickResult, judge_tick, write_report
from regression.waivers import WaiverError

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_PROJECT = "rs-marketmaking"
# Snapshots land every 30 min; replay the newest ones (0 = no hour alignment). Aligning to 2-hourly
# ticks kept CI's replay cache warm but gated on data up to 2h stale, which failed !490 when the
# fetch output changed shape (league_id) between ticks.
SNAPSHOT_EVERY_HOURS = 0

_LIVE_SHA_SQL = (
    "SELECT mapper_git_commit FROM `{project}.markets_us.market_mapping` "
    "WHERE start_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY) "
    "AND mapped_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR) "
    "AND mapper_git_commit IS NOT NULL "
    "GROUP BY mapper_git_commit ORDER BY MAX(mapped_at) DESC LIMIT 1"
)


class GateError(Exception):
    """The gate could not run; the deploy must not proceed either."""


def sh(*cmd: str, env: dict | None = None, cwd: Path | None = None) -> str:
    """Run a command, return stdout; raise GateError with stderr on failure."""
    # B603: argv is built here from literals, SHAs from `git rev-parse` and
    # paths we created; shell=False, so no untrusted string reaches a shell.
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)  # nosec B603
    if p.returncode != 0:
        raise GateError(f"{' '.join(cmd[:4])} ... failed ({p.returncode}):\n{p.stderr[-4000:]}")
    return p.stdout


def short_sha(ref: str) -> str:
    """Resolve a ref to the short SHA run_engine.sh keys its cache on."""
    return sh("git", "-C", str(REPO), "rev-parse", "--short", ref).strip()


def live_sha(project: str) -> str:
    """The mapper commit prod is publishing with right now.

    Read from the rows themselves (``run_provenance`` stamps every
    published row), not from the deploy job's history — a failed or
    manual deploy cannot make this lie.
    """
    from regression.credentials import bq_client

    rows = list(bq_client(project).query(_LIVE_SHA_SQL.format(project=project)).result())
    if not rows:
        raise GateError(
            "no market_mapping rows mapped in the last 2h — is the prod mapper running?  Pass --baseline SHA."
        )
    sha = rows[0].mapper_git_commit
    try:
        return short_sha(sha)
    except GateError:
        raise GateError(
            f"live SHA {sha} is not in this clone — fetch it, or it was never pushed (prod runs unpushed code?)"
        ) from None


def export_tip(out: Path, project: str) -> str:
    """Pin the activated rules tip to a file both engines load."""
    env = dict(os.environ, GCP_PROJECT=project, PYTHONPATH=str(REPO))
    env.pop("MAPPING_SOT_FIXTURE", None)
    text = sh(
        sys.executable,
        "-m",
        "regression.credentials",
        str(REPO / "scripts" / "build_sot_fixture.py"),
        "--out",
        str(out),
        env=env,
        cwd=REPO,
    )
    for tok in text.split():
        if tok.startswith("rule_set_id="):
            return tok.split("=", 1)[1]
    raise GateError(f"could not read rule_set_id from: {text!r}")


def cache_root() -> Path:
    """Projection cache (shared with run_engine.sh)."""
    return Path(os.environ.get("MM_REGRESSION_CACHE", Path.home() / ".cache" / "mm-regression"))


@dataclass
class Run:
    """One engine version on one tick: canonical + raw output paths."""

    sha: str
    tick: Path
    leagues: tuple[str, ...]
    canon: Path = field(init=False)
    raw: Path = field(init=False)

    def __post_init__(self):
        tick_id = f"{self.tick.parent.name}_{self.tick.name}"
        league_id = "-".join(self.leagues) or "all"
        tag = os.environ.get("MM_REGRESSION_TAG")
        tag = f".t{tag}" if tag else ""
        from regression.project import VERSION

        stem = f"{self.sha}.{tick_id}.{league_id}{tag}.v{VERSION}"
        self.canon = cache_root() / "canon" / f"{stem}.jsonl"
        self.raw = cache_root() / "canon" / f"{stem}.raw.jsonl"


def run_engine(run: Run, env: dict) -> Run:
    """Map one tick at one SHA through run_engine.sh (cached)."""
    sh(str(HERE / "run_engine.sh"), run.sha, str(run.tick), *run.leagues, env=env)
    if not (run.canon.is_file() and run.raw.is_file()):
        raise GateError(f"run_engine.sh produced no output for {run}")
    return run


def violations(run: Run) -> list[invariants.Violation]:
    """Every invariant violation in one run's output, judged against its own tick's catalogues."""
    return invariants.check(invariants.load_records(run.raw), invariants.Catalogues.load(run.tick))


def gate_tick(base: Run, cand: Run, waivers: Path) -> TickResult:
    """Diff + invariants for one tick; corrections folded in."""
    tick = f"{cand.tick.parent.name}/{cand.tick.name}"
    return judge_tick(tick, base.canon, cand.canon, violations(base), violations(cand), waivers)


def check_incidents(cand_runs: dict[str, Run], incidents: list[dict]) -> list[str]:
    """Every expectation of every incident; return the failures."""
    return [f for inc in incidents for f in incident_failures(inc, cand_runs[inc["id"]].raw)]


def incident_failures(inc: dict, raw: Path) -> list[str]:
    """One incident's broken expectations in one candidate output."""
    failures = []
    mapped: dict[tuple[str, str], set[str]] = {}
    for rec in invariants.load_records(raw):
        for sb, cid, _ref, _book in invariants._stamps(rec):
            mapped.setdefault((sb, cid), set()).add(rec["optic_odds"].get("selection") or "")
    for exp in inc.get("expect", []):
        got = mapped.get((exp["sportsbook"], exp["contract"]))
        if not got:
            failures.append(f"{inc['id']}: {exp['contract']} is not mapped at all (expected {exp['selection']!r})")
        elif got != {exp["selection"]}:
            failures.append(f"{inc['id']}: {exp['contract']} mapped to {sorted(got)}, expected {exp['selection']!r}")
    return failures


def load_incidents(path: Path = HERE / "incidents.toml") -> list[dict]:
    """Parse incidents.toml; refuses malformed entries."""
    doc = tomllib.loads(path.read_text())
    incs = doc.get("incident", [])
    for i in incs:
        for f in ("id", "reason", "snapshot", "leagues", "expect"):
            if f not in i:
                raise GateError(f"incidents.toml: {i.get('id', '?')} lacks {f!r}")
    return incs


def _parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--candidate", default="HEAD")
    ap.add_argument("--baseline", default="live", help="SHA, or 'live' = the commit prod is publishing with")
    ap.add_argument("--snapshots", type=int, default=2, help="newest prod snapshots to replay (default 2)")
    ap.add_argument("--snapshot", action="append", default=[], help="also replay this snapshot id (repeatable)")
    ap.add_argument("--league", action="append", default=[], help="restrict the fresh replays to these leagues")
    ap.add_argument("--project", default=os.environ.get("MM_REPLAY_PROJECT", DEFAULT_PROJECT))
    ap.add_argument("--out", type=Path, default=Path("gate-report"))
    ap.add_argument("--jobs", type=int, default=2, help="engine runs in parallel (memory-bound)")
    ap.add_argument(
        "--prune-cache",
        action="store_true",
        help="drop cached ticks and engine outputs this run does not use (keeps a carried cache small)",
    )
    ap.add_argument("--stage", choices=("all", "plan", "run", "verdict"), default="all")
    ap.add_argument("--plan", type=Path, default=Path("gate-plan"), help="plan.json + tip.json (plan writes it)")
    ap.add_argument("--runs", type=Path, default=Path("gate-runs"), help="run outputs (run writes RUNS/SLOT/)")
    ap.add_argument("--slot", type=int, default=int(os.environ.get("CI_NODE_INDEX", "1")), help="this run job, 1..N")
    ap.add_argument("--slots", type=int, default=int(os.environ.get("CI_NODE_TOTAL", "1")), help="run jobs in all")
    return ap.parse_args(argv)


def prune_cache(ticks: list[Path], runs: list[Run]) -> int:
    """Delete cached tick dirs and engine outputs outside ``ticks`` / ``runs``; return files + dirs removed.

    CI carries ``ticks/`` and ``canon/`` between pipelines (immutable per snapshot / SHA / tip), so whatever the
    current run does not use would only grow the cache. Worktrees (``wt/``) are not carried and are left alone.
    """
    root = cache_root()
    keep_ticks = {t.resolve() for t in ticks}
    keep_canon = {p.resolve() for r in runs for p in (r.canon, r.raw, r.canon.with_suffix(".log"))}
    removed = 0
    for day in sorted((root / "ticks").glob("*")):
        for tick in sorted(day.glob("*")):
            if tick.is_dir() and tick.resolve() not in keep_ticks:
                shutil.rmtree(tick)
                removed += 1
        if day.is_dir() and not any(day.iterdir()):
            day.rmdir()
    for f in sorted((root / "canon").glob("*")):
        if f.is_file() and f.resolve() not in keep_canon:
            f.unlink()
            removed += 1
    return removed


def build_ticks(snaps: list[str], incidents: list[dict], project: str) -> dict[str, Path]:
    """Materialize every snapshot the gate needs, in parallel."""
    wanted = list(dict.fromkeys(snaps + [i["snapshot"] for i in incidents]))
    root = cache_root() / "ticks"
    with ThreadPoolExecutor(max_workers=4) as pool:
        dirs = list(pool.map(lambda s: materialize.materialize(s, root, project), wanted))
    return dict(zip(wanted, dirs, strict=True))


PLAN, TIP = "plan.json", "tip.json"
# A full-tick replay against a one-league incident replay, for spreading runs over slots.
FULL_TICK, ONE_LEAGUE = 10, 1


def assign_slots(runs: list[dict], slots: int) -> None:
    """Give every run a slot 1..``slots``, heaviest first onto the least-loaded slot."""
    load = dict.fromkeys(range(1, slots + 1), 0)
    for run in sorted(runs, key=lambda r: (-(ONE_LEAGUE if r["leagues"] else FULL_TICK), r["idx"])):
        slot = min(load, key=lambda k: (load[k], k))
        run["slot"] = slot
        load[slot] += ONE_LEAGUE if run["leagues"] else FULL_TICK


def lay_out_runs(base: str, cand: str, snaps: list[str], leagues: tuple[str, ...], incidents: list[dict]) -> dict:
    """Every replay the gate needs, once each: the (base, cand) run of each snapshot and each incident's run."""
    runs: list[dict] = []
    index: dict[tuple, int] = {}

    def run_of(sha: str, snapshot: str, run_leagues) -> int:
        key = (sha, snapshot, tuple(run_leagues))
        if key not in index:  # candidate == baseline replays once
            index[key] = len(runs)
            runs.append({"idx": len(runs), "sha": sha, "snapshot": snapshot, "leagues": list(run_leagues)})
        return index[key]

    pairs = [{"snapshot": s, "base": run_of(base, s, leagues), "cand": run_of(cand, s, leagues)} for s in snaps]
    by_incident = {i["id"]: run_of(cand, i["snapshot"], i["leagues"]) for i in incidents}
    return {"pairs": pairs, "incidents": by_incident, "runs": runs}


def make_plan(args: argparse.Namespace, plan_dir: Path) -> dict:
    """Resolve both SHAs, pin the rules tip, pick the snapshots and lay out every run; write plan.json."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    cand_full = sh("git", "-C", str(REPO), "rev-parse", args.candidate).strip()
    base = live_sha(args.project) if args.baseline == "live" else short_sha(args.baseline)
    base_full = sh("git", "-C", str(REPO), "rev-parse", base).strip()
    cand = short_sha(cand_full)
    print(
        f"gate: candidate {cand} vs baseline {base} ({'live on prod' if args.baseline == 'live' else 'given'})",
        file=sys.stderr,
    )
    if base == cand:
        print(
            "candidate IS the live SHA: the diff is trivially empty; invariants and incidents still run",
            file=sys.stderr,
        )
    tip = export_tip(plan_dir / TIP, args.project)
    print(f"rules tip pinned: {tip}", file=sys.stderr)
    newest = materialize.latest_snapshots(args.project, args.snapshots, every_hours=SNAPSHOT_EVERY_HOURS)
    snaps = list(dict.fromkeys(newest + list(args.snapshot)))
    plan = {"candidate": cand, "baseline": base, "tip": tip, "project": args.project, "slots": args.slots}
    plan.update(lay_out_runs(base_full, cand_full, snaps, tuple(args.league), load_incidents()))
    assign_slots(plan["runs"], args.slots)
    (plan_dir / PLAN).write_text(json.dumps(plan, indent=2) + "\n")
    for r in plan["runs"]:
        print(
            f"  slot {r['slot']}: r{r['idx']} {r['sha'][:8]} {r['snapshot']} {r['leagues'] or 'all'}", file=sys.stderr
        )
    return plan


def load_plan(plan_dir: Path) -> dict:
    """The plan the plan stage wrote."""
    return json.loads((plan_dir / PLAN).read_text())


def execute(plan: dict, plan_dir: Path, todo: list[dict], out: Path, jobs: int = 1, prune: bool = False) -> None:
    """Materialize, replay and judge ``todo``; write each run's canonical rows, violations and incident results.

    Writes ``r<idx>.canon.jsonl``, ``r<idx>.violations.jsonl`` and, for an incident's run,
    ``r<idx>.incidents.json`` under ``out`` — everything ``verdict`` needs, none of the raw output.
    """
    os.environ["MM_REGRESSION_TAG"] = plan["tip"]  # Run() paths must match run_engine.sh's
    # A replay never publishes: the Underdog pass can raise witness alerts (application-alerts).
    env = dict(os.environ, MAPPING_SOT_FIXTURE=str((plan_dir / TIP).resolve()), ALERT_PUBSUB_ENABLED="false")
    ticks = build_ticks(sorted({r["snapshot"] for r in todo}), [], plan["project"])
    digests = {snap: materialize.digest(tick) for snap, tick in ticks.items()}
    for snap, d in digests.items():
        print(f"tick {snap}: {d}", file=sys.stderr)
    runs = {r["idx"]: Run(short_sha(r["sha"]), ticks[r["snapshot"]], tuple(r["leagues"])) for r in todo}
    if prune:
        print(f"cache: pruned {prune_cache(list(ticks.values()), list(runs.values()))} stale entries", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(lambda r: run_engine(r, env), runs.values()))
    out.mkdir(parents=True, exist_ok=True)
    incidents = {i["id"]: i for i in load_incidents()}
    for idx, run in runs.items():
        with open(run.canon) as f:
            print(f"r{idx}: {sum(1 for _ in f)} canonical rows ({run.canon.name})", file=sys.stderr)
        log = run.canon.with_suffix(".log")
        if run.leagues and log.is_file():  # a one-league incident replay: its engine log is short, keep it
            sys.stderr.write(log.read_text())
        shutil.copyfile(run.canon, out / f"r{idx}.canon.jsonl")
        (out / f"r{idx}.tick.txt").write_text(digests[plan["runs"][idx]["snapshot"]] + "\n")
        invariants.dump(violations(run), out / f"r{idx}.violations.jsonl")
        mine = {i: incident_failures(incidents[i], run.raw) for i, at in plan["incidents"].items() if at == idx}
        if mine:
            (out / f"r{idx}.incidents.json").write_text(json.dumps(mine, indent=2) + "\n")


def verdict(plan: dict, runs_dir: Path, out: Path) -> int:
    """Judge the runs' outputs (any layout under ``runs_dir``); write the report; return the exit code."""

    def one(idx: int, suffix: str) -> Path:
        hits = sorted(runs_dir.rglob(f"r{idx}.{suffix}"))
        if len(hits) != 1:
            raise GateError(f"run r{idx}: {len(hits)} {suffix} under {runs_dir} — did its run job finish?")
        return hits[0]

    out.mkdir(parents=True, exist_ok=True)
    for p in plan["pairs"]:  # base and candidate read their tick in different jobs: they must have read the same
        if one(p["base"], "tick.txt").read_text() != one(p["cand"], "tick.txt").read_text():
            raise GateError(f"{p['snapshot']}: the baseline and candidate runs read different ticks")
    waivers = REPO / "regression" / "waivers.toml"
    results = [
        judge_tick(
            materialize.tick_dir(Path(), p["snapshot"]).as_posix(),
            one(p["base"], "canon.jsonl"),
            one(p["cand"], "canon.jsonl"),
            invariants.load_violations(one(p["base"], "violations.jsonl")),
            invariants.load_violations(one(p["cand"], "violations.jsonl")),
            waivers,
        )
        for p in plan["pairs"]
    ]
    inc_fail = [
        f for i, idx in plan["incidents"].items() for f in json.loads(one(idx, "incidents.json").read_text())[i]
    ]
    return write_report(out, plan["candidate"], plan["baseline"], plan["tip"], results, load_incidents(), inc_fail)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; see module docstring."""
    args = _parse(argv)
    if args.stage == "plan":
        make_plan(args, args.plan)
        return 0
    if args.stage == "run":
        plan = load_plan(args.plan)
        if args.slots != plan["slots"]:
            raise GateError(f"this is slot {args.slot} of {args.slots}, the plan has {plan['slots']} slots")
        todo = [r for r in plan["runs"] if r["slot"] == args.slot]
        out = args.runs / str(args.slot)
        out.mkdir(parents=True, exist_ok=True)
        (out / "slot.json").write_text(json.dumps({"slot": args.slot, "runs": [r["idx"] for r in todo]}) + "\n")
        if todo:
            execute(plan, args.plan, todo, out)
        return 0
    if args.stage == "verdict":
        return verdict(load_plan(args.plan), args.runs, args.out)
    args.slots = 1
    plan = make_plan(args, args.out)
    execute(plan, args.out, plan["runs"], args.out / "runs", jobs=args.jobs, prune=args.prune_cache)
    return verdict(plan, args.out / "runs", args.out)


def entry() -> int:
    """Exit 0/1 from the verdict; 2 for ANY failure to reach one.

    Exit 1 means "the mappings are wrong"; a missing service account, an
    expired token or a BigQuery outage is not that, so everything that
    stops the gate short of a verdict maps to 2 (it still blocks).
    """
    try:
        return main()
    except (GateError, WaiverError) as e:
        print(f"GATE ERROR (deploy blocked, gate could not run): {e}", file=sys.stderr)
    except Exception:  # noqa: BLE001 - infrastructure failures must not read as a verdict
        import traceback

        traceback.print_exc()
        print("GATE ERROR (deploy blocked, gate could not run): unexpected exception above", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(entry())
