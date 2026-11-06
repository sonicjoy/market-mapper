"""Alert when a live SX Bet mapping row prices the other side.

End-to-end check on the rows the SX maker reads: the newest
``market_mapping`` row per SX ``(market_id, selection_id)`` -- Optic's
passthrough and our constructed rows alike -- for fixtures starting
now-3h ... now+3d.  Ground truth is SX's own outcome text, not the mapper's
logic, so a flip from any path shows here.

The taker outcome a row prices is the FLIPPED suffix of its
``selection_id`` (``|two`` -> outcome one, ``|one`` -> outcome two; the
suffix is the maker's outcome, ``mappers.exchanges.sxbet.selection_id``).
That outcome's name must agree with the row:

* total  -- the over/under word and the number equal the row's
  ``selection_line`` and ``points``;
* spread -- the outcome's handicap equals the row's ``points`` (sign
  included) and its team fits the row's ``selection``;
* moneyline / 3-way -- the outcome's team fits ``selection`` ("Tie" ↔
  "Draw").

Verdicts: AGREE; FLIP (the row matches the OTHER outcome, not its own);
MISMATCH (the row's number / over-under matches neither outcome);
NOT_SIDE (the row prices SX's "Not X" complement, which the SX maker must
never quote); UNVERIFIED (SX no longer lists the hash, or the row is not a
shape this check reads); name_noise (numbers agree, names fit neither
side -- not an alert).

SX text comes from the run's ``sxbet_markets.jsonl`` (``fetch.sxbet``) and,
for hashes it lacks, ``GET /markets/find`` (public, <= 30 hashes a call,
capped at ``MAX_FIND_CALLS``).  Prints one summary line and, on FLIP /
MISMATCH / NOT_SIDE, an ``ALERT:`` line that ``infra/cron_pipeline.sh``
posts to Slack.  Never fails the pipeline.

Usage:
    GCP_PROJECT=rs-marketmaking python -m BigQuery.sxbet_side_check [RUN_DIR]
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mappers.canonical_codes import names_fit
from mappers.exchanges.dkex_names import club_short_fits
from mappers.exchanges.sxbet import is_not_outcome, parse_handicap, parse_total, strip_segment

SPORTSBOOK = "SX Bet"
FIND_URL = "https://api.sx.bet/markets/find"
FIND_BATCH = 30          # docs.sx.bet/api-reference/get-markets-find: "maximum 30"
MAX_FIND_CALLS = 40      # hashes beyond the run's catalogue; the rest are UNVERIFIED
MAX_BYTES_BILLED = 2 * 1024**3
MAX_LISTED = 8
ALERT_VERDICTS = ("FLIP", "MISMATCH", "NOT_SIDE")
CHECKED = ("AGREE", "FLIP", "MISMATCH", "NOT_SIDE", "name_noise")
PROD_PROJECT = "rs-marketmaking"
#: Below this share of checkable rows the check is blind (prod only).
MIN_CHECKED_SHARE = 0.5

SQL = """
select
  lower(json_value(source_ids, '$.market_id')) as market_hash,
  lower(json_value(source_ids, '$.selection_id')) as selection_id,
  league, market_type, selection, selection_line, points, line,
  market_match_method, fixture_id
from `{table}`
where start_date between timestamp_sub(current_timestamp(), interval 3 hour)
                     and timestamp_add(current_timestamp(), interval 3 day)
  and sportsbook = 'SX Bet'
  and json_value(source_ids, '$.selection_id') is not null
qualify row_number() over (
  partition by json_value(source_ids, '$.market_id'), json_value(source_ids, '$.selection_id')
  order by last_updated desc, mapped_at desc) = 1
"""


@dataclass(frozen=True)
class Row:
    """One newest SX mapping row."""

    market_hash: str
    suffix: str            # "one" | "two" -- the maker's outcome
    league: str
    market_type: str
    selection: str
    selection_line: str
    points: float | None
    line: float | None
    method: str            # market_match_method of the canonical row (provenance only)
    fixture_id: str

    @property
    def taker_outcome(self) -> int:
        """The taker outcome this row prices: ``|two`` is outcome one."""
        return 1 if self.suffix == "two" else 2


def row_from(rec: dict[str, Any]) -> Row | None:
    """A Row from one query record; None when the id is not ``<hash>|one|two``."""
    mh = str(rec.get("market_hash") or "").lower()
    head, _, suffix = str(rec.get("selection_id") or "").lower().partition("|")
    if not mh or head != mh or suffix not in ("one", "two"):
        return None

    def _f(v: Any) -> float | None:
        return None if v is None else float(v)

    return Row(
        market_hash=mh, suffix=suffix, league=str(rec.get("league") or ""),
        market_type=str(rec.get("market_type") or ""), selection=str(rec.get("selection") or ""),
        selection_line=str(rec.get("selection_line") or "").lower(), points=_f(rec.get("points")),
        line=_f(rec.get("line")), method=str(rec.get("market_match_method") or ""),
        fixture_id=str(rec.get("fixture_id") or ""),
    )


# === Name fit ===

_NOISE = frozenset({"club", "united", "city", "real", "sporting", "athletic", "deportivo", "atletico",
                    "the", "and", "football", "futbol", "calcio", "spor", "kulubu", "state",
                    "university", "college", "saint"})


def _norm_tokens(text: str) -> set[str]:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return {t for t in re.findall(r"[a-z0-9]+", ascii_text) if len(t) >= 4 and t not in _NOISE}


def team_fits(sx_name: str, optic_selection: str) -> bool:
    """True when an SX team / player name plausibly names the Optic selection.

    The shared matchers first (club, person, SX short club forms); then one
    shared distinctive word (4+ letters, not club noise).  A FLIP is only
    called when the OTHER outcome fits and the row's own does not, so a
    loose fit here cannot raise an alert on its own.
    """
    a, b = sx_name.strip(), optic_selection.strip()
    if not a or not b:
        return False
    if names_fit(a, b, player=False) or names_fit(a, b, player=True):
        return True
    if club_short_fits(a, b) or club_short_fits(b, a):
        return True
    return bool(_norm_tokens(a) & _norm_tokens(b))


# === Verdict ===

def _kind(row: Row) -> str:
    if row.selection_line in ("over", "under"):
        return "total"
    if row.line is not None and row.points is not None:
        return "spread"
    return "moneyline"


def _struct_and_name(name: str, row: Row, kind: str) -> tuple[bool, bool]:
    """(numbers / over-under agree, team name fits) for one SX outcome against the row."""
    if kind == "total":
        parsed = parse_total(name)
        ok = parsed is not None and parsed[0] == row.selection_line and row.points is not None \
            and abs(parsed[1] - row.points) < 1e-9
        return ok, True
    if kind == "spread":
        handicap = parse_handicap(name)
        if handicap is None or row.points is None:
            return False, False
        return abs(handicap[1] - row.points) < 1e-9, team_fits(handicap[0], row.selection)
    base = strip_segment(name)
    if base.casefold() in ("tie", "draw"):
        return True, row.selection.casefold() in ("draw", "tie")
    return True, team_fits(base, row.selection)


def verdict(row: Row, market: dict[str, Any] | None) -> str:
    """AGREE / FLIP / MISMATCH / NOT_SIDE / UNVERIFIED / name_noise for one row."""
    if market is None:
        return "UNVERIFIED"
    one, two = str(market.get("outcomeOneName") or ""), str(market.get("outcomeTwoName") or "")
    if not one or not two:
        return "UNVERIFIED"
    own, other = (one, two) if row.taker_outcome == 1 else (two, one)
    if is_not_outcome(own):
        return "NOT_SIDE"
    kind = _kind(row)
    own_struct, own_name = _struct_and_name(own, row, kind)
    if is_not_outcome(other):
        other_struct, other_name = False, False
    else:
        other_struct, other_name = _struct_and_name(other, row, kind)
    own_full, other_full = own_struct and own_name, other_struct and other_name
    if own_full and not other_full:
        return "AGREE"
    if other_full and not own_full:
        return "FLIP"
    if not own_struct and not other_struct:
        return "MISMATCH"
    if kind == "spread" and not own_struct and other_struct:
        return "FLIP"          # the number is the other outcome's even if the names say nothing
    return "name_noise"


# === SX text ===

def read_catalogue(run_dir: Path | None) -> dict[str, dict[str, Any]]:
    """{hash -> /markets/active row} from the run's ``sxbet_markets.jsonl`` ({} when absent)."""
    if run_dir is None:
        return {}
    path = run_dir / "sxbet_markets.jsonl"
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("marketHash"):
                out[str(rec["marketHash"]).lower()] = rec
    return out


def find_markets(hashes: Iterable[str], get: Callable[[list[str]], list[dict[str, Any]]],
                 *, max_calls: int = MAX_FIND_CALLS) -> dict[str, dict[str, Any]]:
    """{hash -> market} via ``GET /markets/find``, ``FIND_BATCH`` hashes a call, ``max_calls`` at most."""
    todo = sorted(set(hashes))
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, min(len(todo), FIND_BATCH * max_calls), FIND_BATCH):
        for rec in get(todo[i:i + FIND_BATCH]):
            if isinstance(rec, dict) and rec.get("marketHash"):
                out[str(rec["marketHash"]).lower()] = rec
    return out


def _http_find(batch: list[str]) -> list[dict[str, Any]]:  # pragma: no cover - live SX
    import requests

    resp = requests.get(FIND_URL, params={"marketHashes": ",".join(batch)}, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data")
    return data if isinstance(data, list) else []


# === Run ===

def fetch_rows(client: Any) -> list[Row]:  # pragma: no cover - live BigQuery
    """Newest SX Bet mapping rows in the window (bytes capped)."""
    from google.cloud import bigquery

    from BigQuery.client import ro_query
    from BigQuery.load_mappings import TABLE

    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAX_BYTES_BILLED,
        labels={"component": "mmmapper", "job": "sxbet_side_check"},
    )
    rows = (row_from(dict(r.items())) for r in ro_query(client, SQL.format(table=TABLE), job_config=config))
    return [r for r in rows if r is not None]


def judge(rows: list[Row], markets: dict[str, dict[str, Any]]) -> tuple[Counter, list[tuple[Row, str]]]:
    """Verdict counts and the alerting rows."""
    counts: Counter = Counter()
    bad: list[tuple[Row, str]] = []
    for row in rows:
        v = verdict(row, markets.get(row.market_hash))
        counts[v] += 1
        if v in ALERT_VERDICTS:
            bad.append((row, v))
    return counts, bad


def report_lines(rows: list[Row], counts: Counter, bad: list[tuple[Row, str]],
                 markets: dict[str, dict[str, Any]], *, expect_rows: bool) -> list[str]:
    """The summary line, plus one ``ALERT:`` line when flipped or blind."""
    lines = [f"sxbet side check: {len(rows)} rows {dict(sorted(counts.items()))}"]
    if bad:
        examples = "; ".join(
            f"[{r.league}] {r.market_type} {r.market_hash[:12]}|{r.suffix} sel={r.selection or r.selection_line!r} "
            f"pts={r.points} vs SX {markets.get(r.market_hash, {}).get('outcomeOneName')!r} / "
            f"{markets.get(r.market_hash, {}).get('outcomeTwoName')!r} -> {v}"
            for r, v in bad[:MAX_LISTED]
        )
        lines.append(
            f"ALERT: SX Bet side check: {len(bad)} live mapping row(s) price the wrong SX outcome "
            f"({counts['FLIP']} flip, {counts['MISMATCH']} mismatch, {counts['NOT_SIDE']} not-side). {examples}"
        )
        return lines
    checked = sum(counts[k] for k in CHECKED)
    if expect_rows and (not rows or checked < MIN_CHECKED_SHARE * len(rows)):
        lines.append(f"ALERT: SX Bet side check is BLIND: {checked} of {len(rows)} rows checkable "
                     f"({dict(counts)}). A clean result proves nothing.")
    return lines


def run(run_dir: Path | None, client: Any, find: Callable[[list[str]], list[dict[str, Any]]]) -> list[str]:
    """Query, fetch SX text, judge; return the lines to print."""
    rows = fetch_rows(client)
    markets = read_catalogue(run_dir)
    missing = {r.market_hash for r in rows} - set(markets)
    if missing:
        markets.update(find_markets(missing, find))
    counts, bad = judge(rows, markets)
    return report_lines(rows, counts, bad, markets,
                        expect_rows=os.getenv("GCP_PROJECT", "").strip() == PROD_PROJECT)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wiring
    """CLI: never fails the pipeline, but a crash is reported, not swallowed."""
    args = sys.argv[1:] if argv is None else argv
    run_dir = Path(args[0]) if args else None
    try:
        from BigQuery.client import ro_client

        for line in run(run_dir, ro_client(), _http_find):
            print(line)
    except Exception as exc:  # noqa: BLE001 — post-load best effort
        print(f"ALERT: SX Bet side check FAILED to run ({exc!r}); flips would go unseen.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
