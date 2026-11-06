"""Diff two canonical config files: the step-5 equivalence gate.

The last component of roadmap step 5: given two canonical-lines
files (config_project.py form, any of the three readers —
config_extract side A, config_pull side B, config_toml independent),
set-diff their compared forms in BOTH directions and classify every
delta MATCHED / WAIVED(id) / EXPECTED-LOSS / UNEXPLAINED.  Exit 0
iff UNEXPLAINED is zero (invalid waivers file exits 2) — acceptance
is zero UNEXPLAINED deltas, not zero deltas.

One tool, two audit invocations (decision 2, HISTORY.md):

- Seed audit: side A extracted at the snapshot's source_revision vs
  the materialized snapshot.  Expect zero — a delta is a
  transcription bug or (see the S0_cb85f20c3ad7 finding) a snapshot
  that its stamped revision cannot reproduce.
- Tip audit: side A extracted at a chosen SHA vs the coalesced
  current tip.  Console edits since seeding appear as B-only lines;
  nonzero UNEXPLAINED is the triage worklist, not a failure of the
  tool.

Both directions matter identically (contract docstring): entity
tables are exception lists, so a surplus line on either side is a
delta; a changed value shows as one A-only line plus one B-only
line with the same identity, which the report pairs up as CHANGED
for readability (still two deltas for waiver ceilings).

Waivers reuse the step-4 seven-rule machinery (waivers.load_waivers
/ classify, schema-parameterized) with config-shaped predicates:
``direction`` (a_only / b_only / both), ``kind`` and ``league``
required, ``sportsbook`` / ``key_prefix`` optional narrowing.  The
same discipline applies: ceilings are exact, breach waives nothing,
stale waivers are named for deletion, expiry forces renewal
commits.  league is k[0] for every kind except canonical_market,
which has no league — such deltas are deliberately inexpressible as
waivers today (they would be big news, not excusable noise).
A waiver file is additionally BOUND to one audit invocation as
data: it declares ``audit = "<name>"`` and the run must pass the
same ``--audit`` or the file refuses to classify (exit 2) — see
load_config_waivers for the Uwinks incident that made this a
mechanical check rather than a comment.

Two structural provisions the line-diff cannot express as waivers:

- ``--only-kinds entity,alias`` restricts both sides to the kinds a
  partial reader covers (config_toml emits no market rules; without
  the restriction every rule would read as A-only).
- ``--exclude-poly-overlay`` drops entity/alias lines whose
  canonical_key starts with ``poly_name:`` from BOTH sides before
  diffing — the decision-1 boundary: those entities come from
  Python config (the extractor's own domain), which the independent
  TOML reader deliberately does not cover.  The excluded count is
  printed every run; exclusion is scope, not excuse.

Comment loss (decision 3) is accounting, not lines: pass
``--comment-report`` (config_toml's report JSON) and the lost total
is printed as EXPECTED-LOSS.  The waivers file must then carry a
``[comment_loss]`` section (reason + expires) — the standing waiver
citing the comment-migration ask; expiry forces its renewal like
any other waiver, and an expired section is an error, so the loss
number can never quietly become furniture.

File hygiene: both inputs must embed the same contract version in
their filename (``.v<N>.``) — stale-vs-fresh diffs are refused, the
same guarantee the projection caches give run_engine.sh.

Usage (the audits run 2026-08-14):
    python -m regression.config_diff A.jsonl B.jsonl
    python -m regression.config_diff reader.jsonl extract.jsonl \\
        --only-kinds entity,alias --exclude-poly-overlay \\
        --waivers regression/config_waivers.toml \\
        --audit reader-vs-extractor \\
        --comment-report ...toml_report.v1.json

This module must not import from mappers/ or BigQuery/ (README
design rules).
"""
import argparse
import datetime
import json
import re
import sys
import tomllib
from pathlib import Path

from regression.config_project import strip_annotations
from regression.waivers import WaiverError, classify, load_waivers

CONFIG_REQUIRED_MATCH = ("direction", "kind", "league")
CONFIG_OPTIONAL_MATCH = ("sportsbook", "key_prefix")
CONFIG_DIRECTIONS = ("a_only", "b_only", "both")

# k-position of sportsbook per kind (entity/canonical_market: none).
_SPORTSBOOK_POS = {"market_rule": 1, "alias": 3}

_VERSION_RE = re.compile(r"\.v(\d+)\.")
_PRINT_LIMIT = 40


def config_matches(waiver, delta):
    """Mechanical predicate over a config-line delta.

    delta is {"direction": a_only|b_only, "rec": parsed line}."""
    m = waiver["match"]
    rec = delta["rec"]
    if m["direction"] not in ("both", delta["direction"]):
        return False
    if m["kind"] != rec["t"]:
        return False
    if rec["t"] == "canonical_market" or m["league"] != rec["k"][0]:
        return False
    if "sportsbook" in m:
        pos = _SPORTSBOOK_POS.get(rec["t"])
        if pos is None or m["sportsbook"] != rec["k"][pos]:
            return False
    if "key_prefix" in m and not str(rec["k"][2]).startswith(
            m["key_prefix"]):
        return False
    return True


def load_config_waivers(path, today, audit=None):
    """The step-4 loader with the config match schema; also returns
    the [comment_loss] section (validated) if present.

    Waiver files are bound to ONE audit invocation as data, not
    prose: the file must declare ``audit = "<name>"`` and the caller
    must pass the same name, or nothing is classified.  Learned the
    hard way 2026-08-14: the entity-audit waivers, reused on the tip
    audit, silently absorbed a legitimate console edit (the Uwinks
    lol entity) because a predicate's meaning depends on which two
    files are being compared — same territory, different
    population."""
    doc = tomllib.loads(Path(path).read_text())
    declared = doc.get("audit")
    if not declared or not isinstance(declared, str):
        raise WaiverError(
            "invalid waivers file:\n  missing top-level "
            "audit = \"<name>\" — a waiver file is bound to one "
            "audit invocation; unscoped files excuse deltas they "
            "were never reviewed against")
    if audit != declared:
        raise WaiverError(
            f"waivers file is declared for audit {declared!r} but "
            f"this run is {audit!r} — refusing to classify; a "
            f"waiver's meaning depends on which two files are "
            f"compared, so scope must match exactly (pass --audit)")
    waivers = load_waivers(
        path, today, required_match=CONFIG_REQUIRED_MATCH,
        optional_match=CONFIG_OPTIONAL_MATCH,
        directions=CONFIG_DIRECTIONS,
        extra_top_level=("comment_loss", "audit"))
    cl = doc.get("comment_loss")
    if cl is not None:
        problems = _validate_comment_loss(cl, today)
        if problems:
            raise WaiverError("invalid waivers file:\n  "
                              + "\n  ".join(problems))
    return waivers, cl


def _validate_comment_loss(cl, today):
    """Validate a [comment_loss] section -> problem strings."""
    problems = []
    if not cl.get("reason"):
        problems.append("comment_loss.reason is required")
    exp = cl.get("expires")
    if not isinstance(exp, datetime.date):
        problems.append("comment_loss.expires must be a TOML date")
    elif exp < today:
        problems.append(
            f"comment_loss expired {exp} — comment loss is not "
            f"furniture; renew it with a dated commit or close "
            f"the ask it cites")
    for key in cl:
        if key not in ("reason", "expires"):
            problems.append(f"comment_loss: unknown key {key!r}")
    return problems


def _read(path):
    """Canonical file -> {compared form: full line}."""
    out = {}
    for line in Path(path).read_text().splitlines():
        out[strip_annotations(line)] = line
    return out


def _is_poly_overlay(rec):
    return rec["t"] in ("entity", "alias") and \
        str(rec["k"][2]).startswith("poly_name:")


def diff_files(path_a, path_b, only_kinds=None, exclude_poly=False):
    """Two canonical files -> (deltas, stats).

    deltas: [{"direction", "rec", "line"}] for every compared form
    on exactly one side; stats counts matched/excluded/restricted."""
    a, b = _read(path_a), _read(path_b)
    stats = {"a_lines": len(a), "b_lines": len(b),
             "kind_dropped": 0, "poly_excluded": 0}

    def keep(stripped):
        rec = json.loads(stripped)
        if only_kinds is not None and rec["t"] not in only_kinds:
            stats["kind_dropped"] += 1
            return False
        if exclude_poly and _is_poly_overlay(rec):
            stats["poly_excluded"] += 1
            return False
        return True

    a = {s: l for s, l in a.items() if keep(s)}
    b = {s: l for s, l in b.items() if keep(s)}
    stats["matched"] = len(a.keys() & b.keys())
    deltas = [{"direction": "a_only", "rec": json.loads(s), "line": a[s]}
              for s in sorted(a.keys() - b.keys())]
    deltas += [{"direction": "b_only", "rec": json.loads(s), "line": b[s]}
               for s in sorted(b.keys() - a.keys())]
    return deltas, stats


def _pair_changed(deltas):
    """Group deltas sharing (t, k) across directions as CHANGED pairs.

    Purely presentational: a changed value is still two deltas for
    classification and ceilings; the report just shows them together
    so the reader sees 'canonical_name null -> X', not two lists."""
    by_ident = {}
    for d in deltas:
        ident = json.dumps({"t": d["rec"]["t"], "k": d["rec"]["k"]},
                           sort_keys=True)
        by_ident.setdefault(ident, []).append(d)
    changed = {i: ds for i, ds in by_ident.items() if len(ds) == 2}
    single = [ds[0] for ds in by_ident.values() if len(ds) == 1]
    return changed, single


def _print_deltas(title, deltas, out):
    print(f"\n{title}:", file=out)
    changed, single = _pair_changed(deltas)
    shown = 0
    for ident in sorted(changed):
        if shown >= _PRINT_LIMIT:
            break
        a_side = next(d for d in changed[ident]
                      if d["direction"] == "a_only")
        b_side = next(d for d in changed[ident]
                      if d["direction"] == "b_only")
        print(f"  CHANGED {ident}", file=out)
        print(f"    A: {a_side['line']}", file=out)
        print(f"    B: {b_side['line']}", file=out)
        shown += 1
    for d in sorted(single, key=lambda d: (d["direction"], d["line"])):
        if shown >= _PRINT_LIMIT:
            break
        print(f"  {d['direction'].upper()} {d['line']}", file=out)
        shown += 1
    total = len(changed) + len(single)
    if total > shown:
        print(f"  ... and {total - shown} more (of {len(deltas)} "
              f"delta lines)", file=out)


def _version_mismatch(path_a, path_b, out):
    """Refuse to diff across contract versions -> True to refuse."""
    va = _VERSION_RE.search(Path(path_a).name)
    vb = _VERSION_RE.search(Path(path_b).name)
    if va and vb and va.group(1) != vb.group(1):
        print(f"REFUSED: contract version mismatch in filenames "
              f"(v{va.group(1)} vs v{vb.group(1)}) — never diff a "
              f"stale projection against a fresh one", file=out)
        return True
    return False


def _report_comment_loss(comment_report, comment_loss, out):
    """Comment-loss accounting -> extra unexplained deltas (empty
    when an unexpired [comment_loss] declaration covers the loss)."""
    report = json.loads(Path(comment_report).read_text())
    lost = sum(lg["lost"] for lg in report.values())
    if comment_loss is None:
        print(f"UNEXPLAINED comment loss: {lost} instances — "
              f"the waivers file has no [comment_loss] section",
              file=out)
        return [{"direction": "b_only", "line": "<comment loss>",
                 "rec": {"t": "comment", "k": []}}]
    print(f"EXPECTED-LOSS (comment_loss): {lost} comment "
          f"instances do not migrate — "
          f"{comment_loss['reason']} "
          f"[expires {comment_loss['expires']}]", file=out)
    return []


def _print_waiver_notes(notes, out):
    """Stale / breached / expired waiver diagnostics."""
    for wid in notes["stale"]:
        print(f"STALE waiver {wid!r} matched nothing — delete it",
              file=out)
    for wid, n in notes["breached"].items():
        print(f"BREACHED waiver {wid!r}: matched {n} > ceiling — "
              f"waives NOTHING, all {n} unexplained", file=out)
    for wid, n in notes["expired"].items():
        if n:
            print(f"EXPIRED waiver {wid!r} would have covered {n} "
                  f"deltas — renew with a dated commit or triage",
                  file=out)


def run(path_a, path_b, waivers_path=None, audit=None,
        comment_report=None, only_kinds=None, exclude_poly=False,
        today=None, out=None):
    """The gate.  Returns the exit code (0 pass, 1 unexplained,
    2 invalid waivers file or audit-scope mismatch)."""
    today = today or datetime.date.today()
    out = out or sys.stdout
    if _version_mismatch(path_a, path_b, out):
        return 2
    waivers, comment_loss = [], None
    if waivers_path:
        try:
            waivers, comment_loss = load_config_waivers(
                waivers_path, today, audit=audit)
        except WaiverError as e:
            print(e, file=out)
            return 2
    deltas, stats = diff_files(path_a, path_b, only_kinds=only_kinds,
                               exclude_poly=exclude_poly)
    waived, unexplained, notes = classify(
        deltas, waivers, today, match=config_matches)

    print(f"A: {path_a} ({stats['a_lines']} lines)", file=out)
    print(f"B: {path_b} ({stats['b_lines']} lines)", file=out)
    if only_kinds is not None:
        print(f"restricted to kinds: {','.join(sorted(only_kinds))} "
              f"({stats['kind_dropped']} lines out of scope)",
              file=out)
    if exclude_poly:
        print(f"EXCLUDED (decision-1 boundary): "
              f"{stats['poly_excluded']} poly_name overlay lines — "
              f"Python-config entities the independent TOML reader "
              f"does not cover", file=out)
    print(f"MATCHED: {stats['matched']}", file=out)
    for wid, ds in waived.items():
        print(f"WAIVED({wid}): {len(ds)}", file=out)
    if comment_report is not None:
        unexplained = unexplained + _report_comment_loss(
            comment_report, comment_loss, out)
    print(f"UNEXPLAINED: {len(unexplained)}", file=out)
    _print_waiver_notes(notes, out)
    if unexplained:
        _print_deltas("UNEXPLAINED deltas", [
            d for d in unexplained if d["rec"]["t"] != "comment"], out)
        print("\nGATE FAIL", file=out)
        return 1
    print("GATE PASS", file=out)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Diff two canonical config files; exit 0 iff "
                    "zero UNEXPLAINED deltas.")
    ap.add_argument("file_a")
    ap.add_argument("file_b")
    ap.add_argument("--waivers", metavar="TOML")
    ap.add_argument("--audit", metavar="NAME",
                    help="which audit this run is; must equal the "
                         "waivers file's audit declaration")
    ap.add_argument("--comment-report", metavar="JSON",
                    help="config_toml report; lost total prints as "
                         "EXPECTED-LOSS (needs [comment_loss] waiver)")
    ap.add_argument("--only-kinds", metavar="KIND,KIND",
                    help="restrict both sides to these record kinds")
    ap.add_argument("--exclude-poly-overlay", action="store_true",
                    help="drop poly_name:* entity/alias lines from "
                         "both sides (decision-1 boundary)")
    args = ap.parse_args()
    only = set(args.only_kinds.split(",")) if args.only_kinds else None
    return run(args.file_a, args.file_b, waivers_path=args.waivers,
               audit=args.audit, comment_report=args.comment_report,
               only_kinds=only,
               exclude_poly=args.exclude_poly_overlay)


if __name__ == "__main__":
    sys.exit(main())
