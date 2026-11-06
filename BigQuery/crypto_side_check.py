"""Alert when a live crypto.com mapping row prices the other side.

End-to-end check on the rows mmcryptocom actually loads: the newest
``market_mapping`` row per crypto.com symbol, for every side-bearing market
(moneyline / spread / winner / team_total and period variants). Ground truth
is crypto.com's own catalogue, not the mapper's logic, so a flip from any
path — an in-memory id pin, a bad alias, the Optic-stamp path — shows here.

- FLIP: the row's selection names the sibling symbol's participant, not the
  symbol's own (2026-09-30 incident, epic &91: 38 UFC bets priced the
  opponent). Word order is ignored (Wang Cong == Cong Wang).
- SIGN_FLIP: a spread row's line is the negative of the signed number in
  crypto.com's own event name ("Team -1.5 to win").
- BLIND: too few rows could be checked (catalogue missing / query empty), so
  a clean result would prove nothing.

Cost: ~4 GiB per run (3-day catalogue window covers 100% of symbols,
measured 2026-09-30). Runs after every mapping load in run_pipeline.sh.

Usage:
    GCP_PROJECT=rs-marketmaking python -m BigQuery.crypto_side_check
"""

from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from google.cloud import bigquery

from BigQuery.alerts import Severity, build_publisher, format_critical_alert
from BigQuery.client import CRYPTO_UNDERLYING_SECURITIES_TABLE, ro_client, ro_query
from BigQuery.load_mappings import TABLE as MAPPING_TABLE

logger = logging.getLogger(__name__)

SIDE_MARKETS = r"moneyline|spread|winner|team_total|to_advance|run_line|puck"
SPREAD_MARKETS = ("spread", "run_line", "puck")
# Below this share of rows with a catalogue participant the check is blind.
MIN_CHECKED_SHARE = 0.9
MAX_LISTED = 20
JOB_LABELS = {"component": "mmmapper", "job": "crypto_side_check"}
# crypto.com trades only in prod; TEST has no crypto rows, so an empty result
# there is expected, not blindness. Override with CRYPTO_SIDE_CHECK_EXPECT_ROWS.
PROD_PROJECT = "rs-marketmaking"

_SQL = """
with mm as (
  select json_value(source_ids, '$.symbol') as symbol, league, market_type,
         coalesce(selection, entity) as sel, line, mapper_git_commit
  from `{mapping}`
  where start_date between timestamp_sub(current_timestamp(), interval 1 day)
                       and timestamp_add(current_timestamp(), interval 14 day)
    and sportsbook = 'crypto.com'
    and regexp_contains(market_type, r'{markets}')
  qualify row_number() over (
    partition by json_value(source_ids, '$.symbol')
    order by last_updated desc, mapped_at desc) = 1
),
cat as (
  select symbol, meta_participant as p, meta_predict_market_id as mid,
         meta_predict_contract_type as ct, meta_event_name as ev,
         split(symbol, '.O.1.')[safe_offset(0)] as event_key
  from `{catalogue}`
  where publish_time > timestamp_sub(current_timestamp(), interval 3 day)
  qualify row_number() over (partition by symbol order by publish_time desc) = 1
),
sib as (
  select c.symbol, array_agg(distinct o.p ignore nulls) as sibs
  from cat c
  join cat o
    on o.event_key = c.event_key and o.ct = c.ct and o.mid = c.mid
   and o.symbol != c.symbol and coalesce(o.p, '') != coalesce(c.p, '')
  where c.symbol in (select symbol from mm)
  group by 1
)
select m.league, m.market_type, m.symbol, m.sel, m.line, m.mapper_git_commit,
       c.p as own, c.ev, c.symbol is not null as in_cat, s.sibs
from mm m
left join cat c using (symbol)
left join sib s using (symbol)
"""

_LINE_IN_NAME = re.compile(r"([+-]?\d+(?:\.\d+)?) to win")


@dataclass(frozen=True)
class Row:
    """One newest mapping row joined to its catalogue participant(s)."""

    league: str
    market_type: str
    symbol: str
    sel: str
    line: float | None
    commit: str
    own: str
    ev: str
    in_cat: bool
    sibs: tuple[str, ...]


def _norm(text: str) -> str:
    """Accent-, case- and punctuation-free, single-spaced."""
    ascii_text = unicodedata.normalize("NFD", text or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", ascii_text.lower()).split())


def names_fit(left: str, right: str) -> bool:
    """Same name, same words in any order, or one a whole-word part of the other."""
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return False
    if a == b or sorted(a.split()) == sorted(b.split()):
        return True
    return f" {a} " in f" {b} " or f" {b} " in f" {a} "


def _spread_sign_flipped(row: Row) -> bool:
    """Spread line is the negative of the signed number in the event name."""
    if not any(m in row.market_type for m in SPREAD_MARKETS):
        return False
    match = _LINE_IN_NAME.search(row.ev or "")
    if match is None or row.line is None:
        return False
    named = float(match.group(1))
    return named != 0 and abs(named + row.line) < 1e-9


def verdict(row: Row) -> str:
    """FLIP / SIGN_FLIP alert; ok / name_noise / no_participant / no_catalogue do not."""
    if not row.in_cat:
        return "no_catalogue"
    if not _norm(row.own):
        return "no_participant"
    own_fit = names_fit(row.sel, row.own)
    if not own_fit and any(names_fit(row.sel, sib) for sib in row.sibs):
        return "FLIP"
    if _spread_sign_flipped(row):
        return "SIGN_FLIP"
    return "ok" if own_fit else "name_noise"


def fetch_rows(client: Any) -> list[Row]:
    """Newest crypto.com side-bearing mapping rows with catalogue names."""
    sql = (
        _SQL.replace("{mapping}", MAPPING_TABLE)
        .replace("{catalogue}", CRYPTO_UNDERLYING_SECURITIES_TABLE)
        .replace("{markets}", SIDE_MARKETS)
    )
    config = bigquery.QueryJobConfig(labels=JOB_LABELS)
    return [
        Row(
            league=str(r.league or ""),
            market_type=str(r.market_type or ""),
            symbol=str(r.symbol or ""),
            sel=str(r.sel or ""),
            line=None if r.line is None else float(r.line),
            commit=str(r.mapper_git_commit or ""),
            own=str(r.own or ""),
            ev=str(r.ev or ""),
            in_cat=bool(r.in_cat),
            sibs=tuple(str(s) for s in (r.sibs or []) if s),
        )
        for r in ro_query(client, sql, job_config=config)
    ]


def expect_rows() -> bool:
    """True where crypto.com is live, so an empty result means the check is blind."""
    raw = os.getenv("CRYPTO_SIDE_CHECK_EXPECT_ROWS", "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on")
    return os.getenv("GCP_PROJECT", "").strip() == PROD_PROJECT


def format_alert(rows: list[Row], counts: Counter[str]) -> tuple[Severity, str] | None:
    """(severity, text) to publish, or None when the check is clean and not blind."""
    bad = [r for r in rows if verdict(r) in ("FLIP", "SIGN_FLIP")]
    if bad:
        head = (
            f"crypto.com SIDE FLIP: {len(bad)} live mapping row(s) price the other side "
            f"({counts['FLIP']} flip, {counts['SIGN_FLIP']} spread sign). "
            "Pause crypto.com betting and check epic &91."
        )
        lines = [
            f"[{r.league}] {r.market_type} {r.symbol}: mapped {r.sel!r} line={r.line} "
            f"but crypto.com lists {r.own!r} ({r.commit})"
            for r in bad[:MAX_LISTED]
        ]
        return "critical", format_critical_alert("\n".join([head, *lines]))
    checkable = sum(counts[k] for k in ("ok", "name_noise"))
    if not rows and not expect_rows():
        return None
    if not rows or checkable < MIN_CHECKED_SHARE * (len(rows) - counts["no_participant"]):
        return "warning", (
            f"crypto.com side check is BLIND: {checkable} of {len(rows)} live rows "
            f"had a catalogue participant ({dict(counts)}). A clean result proves nothing."
        )
    return None


def publish(severity: Severity, text: str) -> None:
    """Print an ``ALERT:`` line, then publish on the shared application-alerts topic.

    The ``ALERT:`` line reaches Slack through ``infra/cron_pipeline.sh`` (as the
    SX check does), so a disabled publisher or missing channel cannot silence it.
    """
    logger.warning("%s", text)
    print("ALERT: " + " | ".join(line for line in text.splitlines() if line), flush=True)
    publisher = build_publisher()
    try:
        publisher.publish(severity, text)
    finally:
        publisher.close()


def run_check() -> None:
    """Query, judge, log the summary, publish when flipped or blind."""
    rows = fetch_rows(ro_client())
    counts = Counter(verdict(r) for r in rows)
    logger.info("crypto.com side check: %d rows %s", len(rows), dict(counts))
    alert = format_alert(rows, counts)
    if alert is not None:
        publish(*alert)


def main() -> int:
    """CLI entry: never fail the pipeline, but never fail silently either.

    A check that crashes is as blind as one that finds nothing, so a failure
    publishes a warning instead of only logging.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run_check()
    except Exception as exc:
        logger.exception("crypto.com side check failed (non-fatal)")
        try:
            publish("warning", f"crypto.com side check FAILED to run ({exc!r}); flips would go unseen.")
        except Exception:
            logger.exception("could not publish side-check failure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
