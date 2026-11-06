"""The gate's verdict: one tick's diff + invariants, and the report over every tick.

Split out of ``live_gate.py`` so the fan-out's verdict job (``--stage verdict``) needs only the
standard library: it judges canonical rows and violations the run jobs hand back, no engine.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

from regression import diff, invariants


def _contract_of(sb: str, stamp: dict) -> str | None:
    """The invariants' contract id for a projected stamp."""
    if sb == "crypto_com":
        return stamp.get("symbol") or stamp.get("security_id")
    if sb == "kalshi":
        return f"{stamp.get('market_ticker')}:{stamp.get('side') or 'yes'}"
    if sb == "prophet_x":
        return str(stamp.get("line_id"))
    return None


@dataclass
class TickResult:
    """Everything the gate concluded about one tick."""

    tick: str
    diff_code: int
    unexplained: int
    added: int
    swaps: list[dict]
    corrections: int
    inv: invariants.Verdict
    report: str

    @property
    def failed(self) -> bool:
        return self.unexplained > 0 or self.inv.failed


def judge_tick(
    tick: str,
    base_canon: Path,
    cand_canon: Path,
    base_violations: list[invariants.Violation],
    cand_violations: list[invariants.Violation],
    waivers: Path,
) -> TickResult:
    """Diff + invariants for one tick from canonical rows and violations; corrections folded in."""
    buf = io.StringIO()
    result: dict = {}
    code = diff.run(str(base_canon), str(cand_canon), out=buf, waivers_path=waivers, result=result)
    verdict = invariants.compare(cand_violations, base_violations)
    # A swap is a correction when the baseline's mapping of that contract
    # failed the name invariant and the candidate's does not.
    fixed = {(x.sportsbook, x.contract) for x in verdict.fixed if x.rule == "venue_label_swapped"}
    unexplained = result.get("unexplained", [])
    corrected = [
        d
        for d in unexplained
        if d.get("swap") and (d["rec"]["sb"], _contract_of(d["rec"]["sb"], d["rec"]["stamp"])) in fixed
    ]
    # New rows are new coverage, not a regression: reported, not gated. The invariants still judge them, and
    # the added half of a side swap stays gated (its removed half would fail anyway).
    added = [d for d in unexplained if d["direction"] == "added" and not d.get("swap")]
    remaining = len(unexplained) - len(corrected) - len(added)
    return TickResult(
        tick=tick,
        diff_code=code,
        unexplained=remaining,
        added=len(added),
        swaps=result.get("swaps", []),
        corrections=len(corrected),
        inv=verdict,
        report=_tick_report(buf.getvalue(), len(corrected), len(added), verdict),
    )


def _tick_report(diff_text: str, corrected: int, added: int, verdict: invariants.Verdict) -> str:
    """One tick's report text: the diff, corrections, new rows, the invariants."""
    inv_buf = io.StringIO()
    invariants.render(verdict, out=inv_buf)
    return (
        # diff.py's own verdict counts added rows; the table above is this gate's verdict
        diff_text.replace("GATE FAIL:", "diff:")
        + (
            f"\nCORRECTIONS: {corrected} swap deltas fix a mapping the live SHA had on the wrong side (not counted)\n"
            if corrected
            else ""
        )
        + (f"\nNEW ROWS: {added} added rows are new coverage (reported, not gated)\n" if added else "")
        + f"\n--- invariants ---{inv_buf.getvalue()}"
    )


def _markdown(
    failed: bool, cand: str, base: str, tip: str, results: list[TickResult], incidents: list[dict], inc_fail: list[str]
) -> str:
    """The human report: verdict, per-tick table, incident failures, detail."""
    lines = [
        f"# Mapping gate: {'FAIL - do not deploy' if failed else 'PASS'}",
        "",
        f"candidate `{cand}` vs live `{base}`, rules tip `{tip}`",
        "",
        "| tick | unexplained deltas | new rows (not gated) | side swaps | corrections "
        "| new violations | already in prod |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.tick} | {r.unexplained} | {r.added} | {len(r.swaps)} | {r.corrections} "
        f"| {len(r.inv.new)} | {len(r.inv.existing)} |"
        for r in results
    ]
    lines += ["", f"incident cases: {len(incidents)}, failing: {len(inc_fail)}"]
    lines += [f"- {f}" for f in inc_fail]
    for r in results:
        lines += ["", f"## {r.tick}", "```", r.report.rstrip(), "```"]
    return "\n".join(lines) + "\n"


def _summary(failed: bool, cand: str, base: str, tip: str, results: list[TickResult], inc_fail: list[str]) -> dict:
    """Machine-readable verdict (summary.json)."""
    ticks = [
        {
            "tick": r.tick,
            "unexplained": r.unexplained,
            "added": r.added,
            "swaps": len(r.swaps),
            "corrections": r.corrections,
            "new_violations": len(r.inv.new),
            "existing_violations": len(r.inv.existing),
        }
        for r in results
    ]
    return {
        "result": "fail" if failed else "pass",
        "candidate": cand,
        "baseline": base,
        "tip": tip,
        "ticks": ticks,
        "incident_failures": inc_fail,
    }


def write_report(
    out: Path, cand: str, base: str, tip: str, results: list[TickResult], incidents: list[dict], inc_fail: list[str]
) -> int:
    """Print + save the report and artifacts; return the exit code."""
    failed = any(r.failed for r in results) or bool(inc_fail)
    text = _markdown(failed, cand, base, tip, results, incidents, inc_fail)
    (out / "report.md").write_text(text)
    (out / "summary.json").write_text(json.dumps(_summary(failed, cand, base, tip, results, inc_fail), indent=2))
    for r in results:
        invariants.dump(r.inv.new + r.inv.existing, out / f"violations_{r.tick.replace('/', '_')}.jsonl")
    print(text)
    return 1 if failed else 0
