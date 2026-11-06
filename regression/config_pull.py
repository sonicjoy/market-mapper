"""Materialize a BQ rule snapshot to canonical config lines (side B).

Step 5's BQ reader half: given a ``rule_set_id``, produce the file of
canonical lines (config_project.py, current VERSION) that says what
that snapshot actually contains — the "B" side the differ will hold
against the config extracted from the repo at a SHA (side A).

A ``rule_set_id`` is NOT self-contained (COW storage, main eab7b11):
a logical snapshot is its layer plus every ancestor layer via
``mapping_rule_sets.parent_rule_set_id``, merged tip→root with
last-write-wins per natural key, where a tombstone row hides the key
outright.  This module re-implements that coalesce — a DELIBERATE
transcription of ``mappers/control_plane/cow_rebuild.py`` (regression/
never imports mappers/; changes there are contract changes here).
Two deliberate hardenings over the original, loud-not-silent per
harness philosophy: a lineage cycle or missing parent receipt is an
error (cow_rebuild silently stops), and a duplicate natural key
WITHIN one layer is an error (cow_rebuild lets the first row win).
Neither changes the result for well-formed data.

What becomes lines (kinds per config_project):

- ``mapping_market_rules``  -> market_rule
- ``mapping_entities``      -> entity, plus one alias line per nested
  alias (exception-list semantics: the explosion IS the point)
- ``mapping_rule_sets.canonical_markets`` -> canonical_market, read
  from the TIP receipt only — candidate creation clones the parent's
  list verbatim onto the child row (bq_store._insert_receipt), so the
  tip always carries the full set and needs no coalesce.
- ``mapping_leagues`` is deferred (decision 2026-08-13, HISTORY.md).

``rule_set_id`` rides on every line as an annotation: after a
coalesce it names the layer a row survives from, which is exactly
the provenance a tip-audit delta report wants.  The ``tombstone``
column never reaches records — it is coalesce machinery, not
snapshot content.  BEWARE its type on the wire: the bq CLI's JSON
stringifies scalars, so tombstone arrives as "true"/"false"/null and
``bool(row["tombstone"])`` would treat "false" as deleted; only the
explicit coercion here is safe.

Reads go through the ``bq`` CLI (the mini-audit recipe, HISTORY.md) —
caller's own gcloud creds, four small queries, no SDK.  rule_set_ids
are validated against a strict charset before ever meeting SQL.

One sanctioned exception to transcription fidelity: rows pinned in
``KNOWN_STALE_ROWS`` (see its comment block) are dropped — loudly —
before canonicalization, so a known, decided-upon config defect
does not block step-5 testing while its fix is in flight.

Snapshots are append-only: once written, a rule_set_id's rows never
change, so the materialized file is cached forever under the
projection-cache convention —
``$MM_REGRESSION_CACHE`` (else ``~/.cache/mm-regression``)
``/config/<project>.<rule_set_id>.v<VERSION>.jsonl`` — with the
contract VERSION in the filename so a contract bump orphans stale
files instead of diffing against them.  ``--refresh`` re-pulls.

Usage:
    python -m regression.config_pull S0_cb85f20c3ad7
    python -m regression.config_pull P_0eccd9b1a539 --project marketmaking-test

Prints the cached file path on stdout (script-friendly); provenance
and per-kind counts go to stderr.  This module must not import from
mappers/ or BigQuery/ (README design rules).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from regression.config_project import VERSION, canon_all

DEFAULT_PROJECT = "rs-marketmaking"
DATASET = "markets_us"

# Known-stale rows dropped before canonicalization — the harness's
# only sanctioned deviation from transcription fidelity, agreed with
# Greg 2026-08-14 so step-5 testing can proceed while the fix sits
# with Joe (plan.md "Asks for Joe").  Deliberately follows the
# waiver policy rules even though it cannot live in waivers.toml
# (that machinery is diff-time; this failure is materialization-time):
#
# - Pinned by rule_id, which the extractor content-addresses from
#   (league, sportsbook, action-tag, source_key) — so the pin is
#   event-invalidated, not merely dated: ANY change to what the row
#   is un-matches it and the duplicate check goes loud again.  The
#   `expect` fields are belt-and-braces against a hash collision —
#   a matched rule_id with different content is an error, never a
#   silent drop (narrow by construction, rule 4).
# - We drop the IGNORE, not the map, because that is exactly what
#   the fix will do — today's canonical files equal the post-fix
#   state, so nothing re-materializes when it lands.
# - Self-retiring: when the fix lands the pin matches nothing and
#   every run reports the entry stale for deletion (rule 6); every
#   drop is printed, never silently green (rule 7); `expires` is the
#   anti-rot long-stop (rule 5) — expired AND still matching is a
#   hard error forcing an explicit renewal commit.
KNOWN_STALE_ROWS = {
    "c32db3f13913e0c9": {
        "expect": {"league": "ufc", "sportsbook": "optic",
                   "source_key_type": "market_id",
                   "source_key": "method_of_victory",
                   "action": "ignore"},
        "reason": ("stale INTENTIONAL_OPTIC_IGNORES entry "
                   "contradicting the live MoV map (crossed merges "
                   "bdaa5e5/17fc347) — asks to Joe, plan.md; "
                   "renewed 2026-09-15, still pending Joe"),
        # Renewed 2026-09-15 (was 2026-09-14, set 2026-08-14 in b48834e).
        # The row still matches, so the ask is still open — this is the
        # explicit renewal the expiry demands, not a reset of the clock
        # for its own sake. Same one-month long-stop as the original.
        "expires": "2026-10-15",
    },
}

# Interpolated into SQL after validation — keep this strict.
_RULE_SET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Natural keys per table, mirroring control_plane/cow_diff.py
# (market_rule_key / entity_key) — the same deliberate copy
# config_project.py's kind keys make.
_RULE_KEY = ("league", "sportsbook", "source_key_type", "source_key")
_ENTITY_KEY = ("league", "entity_type", "canonical_key")


class SnapshotIntegrityError(Exception):
    """The rule-set lineage or its rows violate COW invariants."""


def bq_json(sql, project):
    """Run one SELECT through the bq CLI, parse its JSON output."""
    out = subprocess.run(
        ["bq", "--quiet", f"--project_id={project}", "query",
         "--use_legacy_sql=false", "--format=json",
         "--max_rows=1000000", sql],
        check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def _check_id(rule_set_id):
    if not _RULE_SET_ID_RE.fullmatch(rule_set_id or ""):
        raise ValueError(f"malformed rule_set_id: {rule_set_id!r}")
    return rule_set_id


def lineage(rule_set_id, receipts):
    """Tip→root receipt chain via parent pointers.

    receipts is every mapping_rule_sets row (the table is tiny).
    Unlike cow_rebuild.lineage_ids, a cycle or a dangling parent is
    an error, not a quiet stop — a snapshot whose ancestry cannot be
    fully resolved must never be silently materialized shallow."""
    by_id = {}
    for r in receipts:
        rid = r["rule_set_id"]
        if rid in by_id:
            raise SnapshotIntegrityError(
                f"duplicate mapping_rule_sets receipt: {rid}")
        by_id[rid] = r
    chain = []
    seen = set()
    cur = rule_set_id
    while cur is not None:
        if cur in seen:
            raise SnapshotIntegrityError(
                f"lineage cycle at {cur} (chain so far: "
                f"{[r['rule_set_id'] for r in chain]})")
        if cur not in by_id:
            raise SnapshotIntegrityError(
                f"no mapping_rule_sets receipt for {cur}"
                + (" (dangling parent pointer)" if chain else ""))
        seen.add(cur)
        chain.append(by_id[cur])
        cur = chain[-1]["parent_rule_set_id"]
    return chain


def _tombstoned(row):
    """Coerce the wire tombstone value; loud on anything unexpected.

    bq CLI JSON stringifies scalars: bool(\"false\") is True, so a
    naive truthiness test would DELETE every row an ancestor layer
    ever marked tombstone=false explicitly."""
    v = row.get("tombstone")
    if v is None or isinstance(v, bool):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "false"):
        return s == "true"
    raise SnapshotIntegrityError(f"untombstoneable value: {v!r}")


def coalesce(layers, key_fields):
    """Tip→root last-write-wins merge; tombstones hide their key.

    layers is a list of row-dict lists, tip first (lineage order).
    Returns surviving rows with the tombstone column removed.  A
    natural key claimed twice within ONE layer is corrupt data and
    errors (across layers it is the point of the coalesce)."""
    seen = set()
    out = []
    for layer in layers:
        in_layer = set()
        for row in layer:
            key = tuple(row.get(f) for f in key_fields)
            if key in in_layer:
                raise SnapshotIntegrityError(
                    f"duplicate natural key within one layer: {key} "
                    f"(rule_set_id {row.get('rule_set_id')!r})")
            in_layer.add(key)
            if key in seen:
                continue
            seen.add(key)
            if _tombstoned(row):
                continue
            row = dict(row)
            row.pop("tombstone", None)
            out.append(row)
    return out


def drop_known_stale(rows, today=None, out=None):
    """Filter KNOWN_STALE_ROWS out of market-rule rows, loudly.

    Shared by both readers (side B here, the side-A runner to come —
    the extractor computes the same rule_id, so one pin covers both).
    Every drop prints; a pin that matches nothing prints a
    delete-me notice; a pin past its expiry that STILL matches is an
    error demanding a renewal commit."""
    today = today or datetime.date.today()
    out = out or sys.stderr
    kept, matched = [], {rid: 0 for rid in KNOWN_STALE_ROWS}
    for row in rows:
        entry = KNOWN_STALE_ROWS.get(row.get("rule_id"))
        if entry is None:
            kept.append(row)
            continue
        rid = row["rule_id"]
        mismatch = {f: row.get(f) for f, want in entry["expect"].items()
                    if row.get(f) != want}
        if mismatch:
            raise SnapshotIntegrityError(
                f"known-stale pin {rid} matched a row whose content "
                f"disagrees with the pinned expectation: {mismatch} — "
                f"refusing to drop; re-verify the exemption")
        if datetime.date.fromisoformat(entry["expires"]) < today:
            raise SnapshotIntegrityError(
                f"known-stale pin {rid} expired {entry['expires']} "
                f"and still matches — renew it with a dated commit "
                f"or deal with the row ({entry['reason']})")
        matched[rid] += 1
    for rid, n in matched.items():
        entry = KNOWN_STALE_ROWS[rid]
        what = "/".join(str(entry["expect"][f]) for f in
                        ("league", "sportsbook", "source_key_type",
                         "source_key"))
        if n:
            print(f"DROPPED known-stale row {rid} ({what} "
                  f"action={entry['expect']['action']}) x{n} — "
                  f"{entry['reason']} [expires {entry['expires']}]",
                  file=out)
        else:
            print(f"NOTE: known-stale pin {rid} ({what}) matched "
                  f"nothing — the fix landed; delete it from "
                  f"KNOWN_STALE_ROWS", file=out)
    return kept


def _by_layer(rows, chain):
    """Group table rows into lineage order (tip first)."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row["rule_set_id"], []).append(row)
    return [grouped.pop(r["rule_set_id"], []) for r in chain]


def records_from(rules, entities, canonical_markets, tip_id):
    """Coalesced rows -> (kind, dict) records for canon_all.

    Entities explode into an entity record plus one alias record per
    nested alias; the alias inherits the entity's key fields and its
    layer provenance.  canonical_markets come off the tip receipt."""
    for row in rules:
        yield "market_rule", row
    for row in entities:
        aliases = row.pop("aliases", None) or []
        yield "entity", row
        for alias in aliases:
            yield "alias", {
                "league": row["league"],
                "entity_type": row["entity_type"],
                "canonical_key": row["canonical_key"],
                "rule_set_id": row.get("rule_set_id"),
                **alias,
            }
    for cm in canonical_markets:
        yield "canonical_market", {**cm, "rule_set_id": tip_id}


def materialize(rule_set_id, project=DEFAULT_PROJECT, query=None):
    """rule_set_id -> (sorted canonical lines, stats, tip receipt).

    query is injectable for tests; the default runs bq_json against
    the given project."""
    _check_id(rule_set_id)
    run = query or (lambda sql: bq_json(sql, project))
    # SQL below is f-string-built, but every interpolated id is
    # _check_id-validated and DATASET is a module constant — no
    # user-controlled input reaches the query text.
    chain = lineage(rule_set_id, run(
        f"select rule_set_id, parent_rule_set_id, source_revision, "  # nosec B608
        f"environment from {DATASET}.mapping_rule_sets"))
    ids = ", ".join(
        f"'{_check_id(r['rule_set_id'])}'" for r in chain)
    rules = coalesce(_by_layer(drop_known_stale(run(
        f"select * from {DATASET}.mapping_market_rules "  # nosec B608
        f"where rule_set_id in ({ids})")), chain), _RULE_KEY)
    entities = coalesce(_by_layer(run(
        f"select * from {DATASET}.mapping_entities "  # nosec B608
        f"where rule_set_id in ({ids})"), chain), _ENTITY_KEY)
    [tip_row] = run(
        f"select canonical_markets from {DATASET}.mapping_rule_sets "  # nosec B608
        f"where rule_set_id = '{rule_set_id}'")
    lines, stats = canon_all(records_from(
        rules, entities, tip_row["canonical_markets"] or [],
        rule_set_id))
    return lines, stats, chain[0]


def canon_config_path(project, rule_set_id):
    """The cached canonical-lines path for one materialized snapshot."""
    cache = Path(os.environ.get("MM_REGRESSION_CACHE",
                                Path.home() / ".cache" / "mm-regression"))
    return cache / "config" / f"{project}.{rule_set_id}.v{VERSION}.jsonl"


def pull(rule_set_id, project=DEFAULT_PROJECT, refresh=False):
    """Materialize into the cache (or reuse); returns the file path.

    Writes land as ``.part`` and are renamed only once complete, so
    an interrupted pull never leaves a file a later run would trust
    (the corpus.py discipline)."""
    dest = canon_config_path(project, rule_set_id)
    if dest.is_file() and not refresh:
        print(f"cached: {dest.name}", file=sys.stderr)
        return dest
    lines, stats, tip = materialize(rule_set_id, project)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_text("".join(line + "\n" for line in lines))
    part.rename(dest)
    print(f"{rule_set_id} (source_revision "
          f"{tip.get('source_revision')}, env {tip.get('environment')}"
          f"): {len(lines)} lines — "
          + ", ".join(f"{k} {n}" for k, n in stats.items()),
          file=sys.stderr)
    return dest


def main():
    ap = argparse.ArgumentParser(
        description="Materialize a BQ rule snapshot to canonical "
                    "config lines (COW-coalesced, cached).")
    ap.add_argument("rule_set_ids", nargs="+", metavar="RULE_SET_ID")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--refresh", action="store_true",
                    help="re-pull even if a cached file exists")
    args = ap.parse_args()
    for rid in args.rule_set_ids:
        print(pull(rid, project=args.project, refresh=args.refresh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
