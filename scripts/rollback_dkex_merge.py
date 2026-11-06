#!/usr/bin/env python
"""Roll back the DKEX code-leagues merge (!422) and the DKEX mappings it wrote.

    python scripts/rollback_dkex_merge.py plan   --merge SHA
    python scripts/rollback_dkex_merge.py revert --merge SHA [--push]
    python scripts/rollback_dkex_merge.py delete --merge SHA [--execute]

Three steps, in this order:

``plan`` (read-only)
    Resolves the commit set and counts the ``markets_us.market_mapping``
    rows the delete would remove, per ``mapper_git_commit``.

``revert``
    Branches ``revert/dkex-<sha>`` off ``origin/main`` and runs
    ``git revert -m 1 <merge>``.  ``--push`` pushes it and opens the MR
    with ``glab``; merging and redeploying the VM (``infra/deploy.sh
    main``) stay manual.  The revert deletes this script from main, so run
    it from a checkout of the merge commit (or keep a copy).

``delete``
    Removes ``sportsbook = 'DKEX'`` rows whose ``mapper_git_commit`` is in
    the commit set and whose ``mapped_at`` is at or after the merge.  Dry
    run unless ``--execute``.  It refuses while a commit in the set has
    written a DKEX row in the last ``--quiet-minutes`` (the VM still runs
    the merged code, and its next tick would put the rows back) unless
    ``--force``.

The commit set is the merge plus every ``origin/main`` commit descended
from it: ``load_mappings`` MERGEs, so a later tick re-stamps a row with
the commit it ran, and a row the merge created can carry any later
commit.  ``--extra-commit`` adds a deploy that is not on main.  Other
sportsbooks' rows are re-stamped by the same ticks and are never touched.
DKEX rows from before the merge -- including the untracked
``mapper_git_commit IS NULL`` load of 2026-10-02 -- are left alone.
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 — git/glab CLI, fixed argv
import sys
from datetime import UTC, datetime, timedelta

from google.cloud import bigquery

TABLE = "markets_us.market_mapping"
SPORTSBOOK = "DKEX"
DEFAULT_PROJECT = "rs-marketmaking"
MIN_SHA_LEN = 7

# BQ requires a start_date partition filter on market_mapping; this bound
# admits every partition, the commit / mapped_at predicates do the work.
_WHERE = """
start_date >= TIMESTAMP('2000-01-01')
and sportsbook = @sportsbook
and mapped_at >= @since
and length(mapper_git_commit) >= @min_len
and exists (select 1 from unnest(@shas) s where starts_with(s, mapper_git_commit))
"""

COUNT_SQL = f"""
select mapper_git_commit, league, count(*) as n,
       min(mapped_at) as first, max(mapped_at) as last
from `{{project}}.{TABLE}`
where {_WHERE}
group by 1, 2
order by 1, 2
"""  # nosec B608 — table is a module constant

DELETE_SQL = f"""
delete from `{{project}}.{TABLE}`
where {_WHERE}
"""  # nosec B608 — table is a module constant


def _git(*args: str) -> str:
    out = subprocess.run(  # nosec B603 B607 — fixed git argv
        ["git", *args], check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def resolve_merge(sha: str) -> tuple[str, datetime]:
    """Full SHA and committer time of a merge commit on origin/main."""
    _git("fetch", "-q", "origin", "main")
    full = _git("rev-parse", "--verify", f"{sha}^{{commit}}")
    parents = _git("rev-list", "--parents", "-n", "1", full).split()
    if len(parents) < 3:
        sys.exit(f"{full[:12]} is not a merge commit")
    try:
        _git("merge-base", "--is-ancestor", full, "origin/main")
    except subprocess.CalledProcessError:
        sys.exit(f"{full[:12]} is not on origin/main")
    when = datetime.fromisoformat(_git("show", "-s", "--format=%cI", full))
    return full, when.astimezone(UTC)


def commit_set(merge: str, extra: list[str]) -> list[str]:
    """The merge plus every origin/main commit descended from it, full SHAs."""
    after = _git("rev-list", "--ancestry-path", f"{merge}..origin/main").split()
    shas = [merge, *after]
    for sha in extra:
        shas.append(_git("rev-parse", "--verify", f"{sha}^{{commit}}"))
    return list(dict.fromkeys(shas))


def query_params(shas: list[str], since: datetime) -> list:
    return [
        bigquery.ScalarQueryParameter("sportsbook", "STRING", SPORTSBOOK),
        bigquery.ScalarQueryParameter("since", "TIMESTAMP", since),
        bigquery.ScalarQueryParameter("min_len", "INT64", MIN_SHA_LEN),
        bigquery.ArrayQueryParameter("shas", "STRING", shas),
    ]


def count_rows(client: bigquery.Client, project: str, shas: list[str], since: datetime):
    config = bigquery.QueryJobConfig(query_parameters=query_params(shas, since))
    return list(client.query(COUNT_SQL.format(project=project), job_config=config).result())


def _print_counts(rows) -> int:
    total = 0
    for r in rows:
        total += r.n
        print(f"  {r.mapper_git_commit}  {r.league:<28} {r.n:>7}  {r.first} .. {r.last}")
    print(f"  total DKEX rows in scope: {total}")
    return total


def _setup(args) -> tuple[bigquery.Client, list[str], datetime]:
    merge, since = resolve_merge(args.merge)
    shas = commit_set(merge, args.extra_commit)
    print(f"merge {merge[:12]} at {since.isoformat()}; {len(shas)} commit(s) in set:")
    for sha in shas:
        print(f"  {sha[:12]} {_git('show', '-s', '--format=%s', sha)}")
    return bigquery.Client(project=args.project), shas, since


def cmd_plan(args) -> None:
    client, shas, since = _setup(args)
    print(f"{args.project}.{TABLE} rows the delete would remove:")
    _print_counts(count_rows(client, args.project, shas, since))


def cmd_revert(args) -> None:
    merge, _ = resolve_merge(args.merge)
    branch = f"revert/dkex-{merge[:8]}"
    _git("switch", "-c", branch, "origin/main")
    _git("revert", "-m", "1", "--no-edit", merge)
    print(f"reverted {merge[:12]} on {branch}")
    if not args.push:
        print("not pushed; rerun with --push to push and open the MR")
        return
    _git("push", "-u", "origin", branch)
    subprocess.run(  # nosec B603 B607 — fixed glab argv
        ["glab", "mr", "create", "--source-branch", branch, "--target-branch", "main",
         "--title", f"Revert DKEX code-leagues merge {merge[:12]}",
         "--description", f"git revert -m 1 {merge}. "
         "After merge: infra/deploy.sh main on the VM, then "
         "scripts/rollback_dkex_merge.py delete --execute.",
         "--yes"],
        check=True,
    )


def cmd_delete(args) -> None:
    client, shas, since = _setup(args)
    rows = count_rows(client, args.project, shas, since)
    total = _print_counts(rows)
    if total == 0:
        print("nothing to delete")
        return
    last = max(r.last for r in rows)
    quiet = datetime.now(UTC) - timedelta(minutes=args.quiet_minutes)
    if last >= quiet and not args.force:
        sys.exit(
            f"refusing: newest in-scope DKEX row was mapped at {last}, within "
            f"{args.quiet_minutes} min -- the VM still runs the merged code. "
            "Deploy the revert first, or pass --force.",
        )
    if not args.execute:
        print("dry run; rerun with --execute to delete")
        return
    config = bigquery.QueryJobConfig(query_parameters=query_params(shas, since))
    job = client.query(DELETE_SQL.format(project=args.project), job_config=config)
    job.result()
    print(f"deleted {job.num_dml_affected_rows} row(s) from {args.project}.{TABLE}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Roll back the DKEX code-leagues merge and its DKEX mappings.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("revert", cmd_revert), ("delete", cmd_delete)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--merge", required=True, help="merge commit of !422 on main")
        p.add_argument("--project", default=os.environ.get("GCP_PROJECT") or DEFAULT_PROJECT)
        p.add_argument("--extra-commit", action="append", default=[],
                       help="deployed commit not on main (repeatable)")
    revert = sub.choices["revert"]
    revert.add_argument("--push", action="store_true")
    delete = sub.choices["delete"]
    delete.add_argument("--execute", action="store_true")
    delete.add_argument("--force", action="store_true")
    delete.add_argument("--quiet-minutes", type=int, default=30)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
