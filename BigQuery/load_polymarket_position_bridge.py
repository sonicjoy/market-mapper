"""Build the Polymarket position-id <-> CLOB token-id bridge and upsert it to BigQuery.

Each combo-RFQ leg is keyed by a ``position_id`` (the NegRisk combo-leg token).
The same selection also trades as a standalone single whose ``clob_token_id`` is
what OpticOdds ingests. Gamma's by-condition_id record carries BOTH arrays in the
same outcome order, so ``position_ids[i] <-> clob_token_ids[i] <-> outcomes[i]``.

This loader persists that bridge (one row per outcome of every combinable market)
into ``raw_ingestion_us.polymarket_position_token_bridge`` so the RFQ services can
read it from BQ instead of re-deriving it live from Gamma every refresh, and so the
leg-resolutions loader has the set of position_ids to resolve.

Universe:
  * ACTIVE — condition_ids from combos-rfq-api /v1/rfq/combo-markets (the
    authoritative combinable-leg catalog), enriched with clob_token_ids from Gamma
    by-condition_id. (Gamma's bulk /markets does NOT expose positionIds, so it
    cannot enumerate this universe.)
  * HISTORICAL (``--backfill-since YYYY-MM-DD``) — distinct leg position_ids the RFQ
    observer recorded in polymarket_combo_mapping since that date, reverse-resolved
    via Gamma's ``position_ids`` lookup (which returns positionIds/clobTokenIds even
    for SETTLED markets — unlike the condition_ids lookup). This recovers legs that
    have settled and delisted from the live catalog.
  * ``--cids-file`` adds extra condition_ids (one per line).

Coverage ACCUMULATES: the MERGE (keyed on position_id) retains legs seen in earlier
runs. Schema is authoritative in Terraform (mm-infrastructure/modules/exchanges/
polymarket/); the inline schema here is kept in lockstep and lets the loader run
standalone.

Scheduled by ``infra/cron_polymarket_bridge.sh`` (VM crontab ``8,23,38,53``),
**not** inside ``infra/run_pipeline.sh``. The mapping tick only reads this
table; paging the combos catalog must not hold ``pipeline.lock``. See
``docs/polymarket-bridge.md``.

Usage:
    .venv/bin/python -m BigQuery.load_polymarket_position_bridge
    .venv/bin/python -m BigQuery.load_polymarket_position_bridge --backfill-since 2026-06-01
    .venv/bin/python -m BigQuery.load_polymarket_position_bridge --limit 200 --dry-run
"""

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from datetime import date as _date

from google.cloud import bigquery

from BigQuery.polymarket_bq_util import bq_client, ensure_table, qualify, stage_and_merge
from BigQuery.polymarket_bridge_flip_guard import flip_guard_reason
from fetch import polymarket_combos as combos
from fetch import polymarket_gamma as gamma

TABLE = "raw_ingestion_us.polymarket_position_token_bridge"
STAGE = "raw_ingestion_us.polymarket_position_token_bridge_stage"
# Historical backfill source: leg position_ids the RFQ observer recorded while the
# legs were active. Gamma's position_ids reverse-lookup recovers their bridge even
# after the legs settle + delist (the combos-rfq-api catalog no longer lists them).
BACKFILL_SOURCE_TABLE = "raw_ingestion_us.polymarket_combo_mapping"
KEY_COL = "position_id"
PARTITION_FIELD = "last_updated"
CLUSTERING = ["position_id", "condition_id"]

SCHEMA = [
    bigquery.SchemaField(
        "position_id",
        "STRING",
        "REQUIRED",
        description="NegRisk combo-leg token id (decimal string) — the RFQ position_id; MERGE key",
    ),
    bigquery.SchemaField(
        "clob_token_id", "STRING", "NULLABLE", description="Standalone single-market CLOB token id for the same outcome"
    ),
    bigquery.SchemaField(
        "condition_id", "STRING", "NULLABLE", description="Underlying single-market condition_id (Gamma 0x+64hex form)"
    ),
    bigquery.SchemaField(
        "outcome_index",
        "INTEGER",
        "NULLABLE",
        description="Index of this outcome within the market (aligns all arrays)",
    ),
    bigquery.SchemaField("outcome_label", "STRING", "NULLABLE", description="Outcome label, e.g. 'Yes'/'No'"),
    bigquery.SchemaField("slug", "STRING", "NULLABLE", description="Market slug"),
    bigquery.SchemaField("question", "STRING", "NULLABLE", description="Market question/title"),
    bigquery.SchemaField("n_outcomes", "INTEGER", "NULLABLE", description="Number of outcomes (== len(position_ids))"),
    bigquery.SchemaField(
        "game_start_time",
        "TIMESTAMP",
        "NULLABLE",
        description=(
            "Gamma gameStartTime — Polymarket's own kickoff instant. The authoritative "
            "fixture key for the matcher: the slug carries only a venue-LOCAL date, which "
            "cannot be compared to optic's UTC start_date (a US night game is local D / "
            "UTC D+1), so date matching silently fell through to a ±1-day window and could "
            "stamp the sibling game of a consecutive-day series. NULL for non-sports "
            "markets and for rows written before this column existed."
        ),
    ),
    bigquery.SchemaField(
        "last_updated", "TIMESTAMP", "NULLABLE", description="When this loader last wrote the row (partition key)"
    ),
]


def _bridge_row(m, pid: str, clob: str, i: int, outcomes: list, now_iso: str) -> dict:
    """One bridge row for outcome ``i`` of market ``m`` (position ``pid`` / token ``clob``)."""
    return {
        "position_id": pid,
        "clob_token_id": clob,
        "condition_id": m["condition_id"] or None,
        "outcome_index": i,
        "outcome_label": outcomes[i] if i < len(outcomes) else None,
        "slug": m["slug"] or None,
        "question": m["question"] or None,
        "n_outcomes": len(m["position_ids"]),
        "game_start_time": m.get("game_start_time") or None,
        "last_updated": now_iso,
    }


def build_rows(
    markets,
    now_iso: str,
    combos_outcome_by_pid: dict[str, str] | None = None,
    optic_side_by_clob: dict[str, str] | None = None,
) -> list[dict]:
    """Turn normalized Gamma markets into one bridge row per outcome.

    Skips markets with no ``position_ids`` (non-combinable singles) and markets
    whose position/token arrays disagree in length (a misalignment would corrupt
    the bridge). When ``combos_outcome_by_pid`` / ``optic_side_by_clob`` are given,
    also drops any market whose Gamma position<->token<->outcome ordering disagrees
    with those independent sources (see ``flip_guard_reason``) — fail closed, because
    a mispaired token flips the traded side. Dedupes on ``position_id`` (last write wins).
    """
    by_pid: dict[str, dict] = {}
    skipped_no_pos = 0
    skipped_misaligned = 0
    skipped_flip_guard = 0
    for m in markets:
        pids = m["position_ids"]
        clobs = m["clob_token_ids"]
        outcomes = m["outcomes"]
        if not pids:
            skipped_no_pos += 1
            continue
        if len(pids) != len(clobs):
            skipped_misaligned += 1
            print(
                f"  misaligned arrays for condition {m['condition_id']}: "
                f"{len(pids)} position_ids vs {len(clobs)} clob_token_ids; skipping",
                file=sys.stderr,
            )
            continue
        reason = flip_guard_reason(m, combos_outcome_by_pid, optic_side_by_clob)
        if reason:
            skipped_flip_guard += 1
            print(
                f"  FLIP GUARD drop condition {m['condition_id']}: {reason}",
                file=sys.stderr,
            )
            continue
        for i, (pid, clob) in enumerate(zip(pids, clobs, strict=True)):
            by_pid[pid] = _bridge_row(m, pid, clob, i, outcomes, now_iso)
    print(
        f"  built {len(by_pid)} bridge rows (skipped {skipped_no_pos} non-combinable, "
        f"{skipped_misaligned} misaligned, {skipped_flip_guard} flip-guard)"
    )
    return list(by_pid.values())


# legacy: ticker parse — replace with the typed venue field, do not extend
_SLUG_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _slug_date(slug: str | None) -> _date | None:
    m = _SLUG_DATE_RE.search(slug or "")
    if not m:
        return None
    try:
        return _date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _is_upcoming_slug(slug: str | None, min_date: _date) -> bool:
    """True when the slug's embedded date is on/after ``min_date``, OR the slug has
    no parseable date at all. Fail OPEN on the unparseable case: dropping something we
    can't classify is exactly the kind of silent coverage loss this guards against.
    """
    d = _slug_date(slug)
    return d is None or d >= min_date


def filter_upcoming(markets: list[dict], min_date: _date) -> tuple[list[dict], int]:
    """Split combo-leg markets by their slug-embedded date. Returns ``(kept, dropped_count)``.

    combos-rfq-api's ``/v1/rfq/combo-markets`` mixes past- and future-dated legs in no
    particular order (a sample pulled ~50/50 past vs. upcoming) and accepts no
    server-side date filter -- confirmed empirically: every filter/sort query param
    tried, including a nonsense one, returned identical results. So this filter has to
    run client-side, after the full catalog is paged in.
    """
    kept = [m for m in markets if _is_upcoming_slug(m.get("slug"), min_date)]
    return kept, len(markets) - len(kept)


def _exclude_bridged(cids: list[str], bridged_cids: set[str] | None) -> tuple[list[str], int]:
    """Drop condition_ids already fully bridged in a prior run. Returns ``(kept, skipped_count)``.

    Coverage accumulates via the MERGE (keyed on position_id), so a condition_id with
    bridge rows already needs no re-enrichment -- skipping it spends this run's Gamma
    calls on legs that are still genuinely unmapped instead of legs we already have.
    """
    if not bridged_cids:
        return cids, 0
    kept = [c for c in cids if c not in bridged_cids]
    return kept, len(cids) - len(kept)


def _combos_outcome_by_pid(combo_markets: list[dict]) -> dict[str, str]:
    """{position_id -> outcome label} from combos-rfq-api's own per-market outcome arrays."""
    out: dict[str, str] = {}
    for m in combo_markets:
        cpos = [str(p) for p in (m.get("position_ids") or [])]
        couts = [str(o) for o in (m.get("outcomes") or [])]
        for pid, outcome in zip(cpos, couts, strict=False):
            out[pid] = outcome
    return out


def collect_markets(
    cids_file: str | None,
    limit: int | None,
    min_date: _date | None = None,
    bridged_cids: set[str] | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """Active universe: combo-leg markets (combos-rfq-api + optional file), Gamma-enriched.

    Returns ``(gamma_markets, combos_outcome_by_pid)``. combos-rfq-api is the INDEPENDENT
    Tier-1 source for ``position_id -> outcome`` (a different system from Gamma), so we keep
    its per-position outcome labels to cross-check the bridge pairing in ``build_rows``.

    ``min_date`` / ``bridged_cids`` narrow the raw catalog to upcoming + not-yet-bridged
    legs before Gamma enrichment -- see ``filter_upcoming`` / ``_exclude_bridged``. Extra
    ``cids_file`` condition_ids are appended AFTER both filters (an explicit ask always
    goes through, e.g. for a manual re-check of a specific market).
    """
    print("Fetching combo-leg catalog from combos-rfq-api...", file=sys.stderr)
    combo_markets = combos.fetch_combo_markets()
    print(f"  {len(combo_markets)} raw combo-leg markets from combos-rfq-api", file=sys.stderr)

    if min_date is not None:
        combo_markets, stale = filter_upcoming(combo_markets, min_date)
        if stale:
            print(f"  dropping {stale} past-dated combo markets (before {min_date})", file=sys.stderr)

    cids = list(dict.fromkeys(str(m["condition_id"]) for m in combo_markets if m.get("condition_id")))
    combos_outcome_by_pid = _combos_outcome_by_pid(combo_markets)
    print(
        f"  {len(cids)} condition_ids, {len(combos_outcome_by_pid)} position->outcome from combos-rfq-api",
        file=sys.stderr,
    )

    cids, skipped = _exclude_bridged(cids, bridged_cids)
    if skipped:
        print(f"  skipping {skipped} already-bridged condition_ids (--refresh-existing to force)", file=sys.stderr)

    if cids_file:
        with open(cids_file) as f:
            extra = [ln.strip() for ln in f if ln.strip()]
        merged = dict.fromkeys(cids + extra)
        print(f"  +{len(extra)} from {cids_file} -> {len(merged)} unique", file=sys.stderr)
        cids = list(merged)
    if limit:
        cids = cids[:limit]
    print(f"Enriching {len(cids)} condition_ids from Gamma (clob_token_ids)...", file=sys.stderr)
    by_cid = gamma.fetch_markets_by_condition_ids(cids)
    print(f"  Gamma returned {len(by_cid)} markets", file=sys.stderr)
    return list(by_cid.values()), combos_outcome_by_pid


OPTIC_SIDE_TABLE = "opticodds_us.prices_dedup_state"


def _load_optic_side_by_clob(client, days_back: int = 3, days_ahead: int = 30) -> dict[str, str]:
    """``{clob_token_id -> 'over'|'under'}`` for Polymarket singles OpticOdds has mapped.

    Tier-2 independent source: OpticOdds' own ``selection_line`` for each standalone
    Polymarket single (keyed by ``source_ids.selection_id`` == the CLOB token id) — the
    exact over/under side the maker prices off. Only totals carry a ``selection_line``, so
    this covers the totals legs (the flip class we're guarding). Bounded on the partition
    column ``start_date`` to a fixture window to keep the scan cheap.
    """
    db, da = int(days_back), int(days_ahead)
    src = qualify(client, OPTIC_SIDE_TABLE)
    sql = f"""
      SELECT clob_token_id, selection_line FROM (
        SELECT
          JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id') AS clob_token_id,
          LOWER(selection_line) AS selection_line
        FROM `{src}`
        WHERE LOWER(sportsbook) LIKE '%polymarket%'
          AND selection_line IS NOT NULL
          AND JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id') IS NOT NULL
          AND start_date BETWEEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {db} DAY)
                             AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {da} DAY)
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id')
          ORDER BY last_updated DESC) = 1
      )
      WHERE selection_line IN ('over', 'under')
    """  # nosec B608 — {src} is qualify() of a module constant; {db}/{da} are ints
    job = bigquery.QueryJobConfig(maximum_bytes_billed=20 * 1024**3)
    out = {str(r.clob_token_id): str(r.selection_line) for r in client.query(sql, job_config=job).result()}
    print(f"  optic Tier-2 map: {len(out)} clob_token_id -> over/under", file=sys.stderr)
    return out


def _load_bridged_condition_ids(client) -> set[str]:
    """Distinct ``condition_id``s already fully bridged (a market is bridged all-or-
    nothing -- see ``build_rows``, so any row for a condition_id means the whole
    market's legs are present). Callers use this to skip re-enriching via Gamma every
    run; only genuinely unmapped legs need to be chased. Requires the target table to
    already exist (caller ensures this before calling).
    """
    target = qualify(client, TABLE)
    sql = f"SELECT DISTINCT condition_id FROM `{target}` WHERE condition_id IS NOT NULL"  # nosec B608 — target is qualify() of a module constant
    out = {str(r.condition_id) for r in client.query(sql).result()}
    print(f"  {len(out)} condition_ids already bridged (skip unless --refresh-existing)", file=sys.stderr)
    return out


def _dedup_by_condition(by_pid: dict[str, dict]) -> list[dict]:
    """Collapse a {position_id -> market} map to unique markets (by condition_id)."""
    seen: set[str] = set()
    markets: list[dict] = []
    for m in by_pid.values():
        cid = m["condition_id"]
        if cid and cid not in seen:
            seen.add(cid)
            markets.append(m)
    return markets


def collect_backfill_markets(client, since: str, limit: int | None) -> list[dict]:
    """Historical universe: distinct leg position_ids the RFQ observer recorded since
    ``since`` (from polymarket_combo_mapping), reverse-resolved via Gamma position_ids
    (closed=True) — recovers legs that have settled and delisted from the live catalog.
    """
    src = qualify(client, BACKFILL_SOURCE_TABLE)
    sql = f"""
        SELECT DISTINCT leg_position_id AS pid
        FROM `{src}`
        WHERE publish_time >= TIMESTAMP(@since) AND leg_position_id IS NOT NULL
    """  # nosec B608 — {src} is a code-derived table ref (qualify() of a module constant); @since is bound
    job = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("since", "STRING", since)])
    pids = [r.pid for r in client.query(sql, job_config=job).result()]
    print(f"Backfill: {len(pids)} distinct leg position_ids from combo_mapping since {since}", file=sys.stderr)
    if limit:
        pids = pids[:limit]
    by_pid = gamma.fetch_markets_by_position_ids(pids, closed=True)
    markets = _dedup_by_condition(by_pid)
    print(f"  Gamma position_ids reverse-lookup: {len(by_pid)} legs -> {len(markets)} markets", file=sys.stderr)
    return markets


# Grace window matching the maker's own late-night/UTC-rollover tolerance
# (mirrors mappers/pipeline.py's ±1 day fixture-match grace) -- a game from
# "yesterday" by slug date may still be in-progress or awaiting settlement.
_UPCOMING_GRACE_DAYS = 1


def _prepare_client(
    dry_run: bool, backfill_since: str | None, refresh_existing: bool
) -> tuple[bigquery.Client | None, str | None, set[str] | None]:
    """Resolve the BQ client + target table + already-bridged set for this run.

    A client is needed to query the backfill source, the already-bridged set, and to
    write. A truly offline run (no BQ access at all) needs BOTH --dry-run AND
    --refresh-existing -- otherwise we can't know what's already bridged.
    """
    client = bq_client() if (backfill_since or not dry_run or not refresh_existing) else None
    target = None
    bridged_cids: set[str] | None = None
    if client is not None:
        target = qualify(client, TABLE)
        ensure_table(client, target, SCHEMA, PARTITION_FIELD, CLUSTERING)
        if not refresh_existing:
            bridged_cids = _load_bridged_condition_ids(client)
    return client, target, bridged_cids


def load(
    cids_file: str | None = None,
    backfill_since: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    refresh_existing: bool = False,
) -> None:
    now_iso = datetime.now(UTC).isoformat()
    client, target, bridged_cids = _prepare_client(dry_run, backfill_since, refresh_existing)

    min_date = datetime.now(UTC).date() - timedelta(days=_UPCOMING_GRACE_DAYS)
    markets, combos_outcome_by_pid = collect_markets(
        cids_file, limit, min_date=min_date, bridged_cids=bridged_cids)
    if backfill_since:
        markets = markets + collect_backfill_markets(client, backfill_since, limit)
    # Tier-2 optic map needs a BQ client; in a pure dry-run (no client) Tier 2 is disabled
    # and only the Tier-1 combos cross-check runs.
    optic_side_by_clob = _load_optic_side_by_clob(client) if client is not None else None
    rows = build_rows(
        markets,
        now_iso,
        combos_outcome_by_pid=combos_outcome_by_pid,
        optic_side_by_clob=optic_side_by_clob,
    )
    if not rows:
        if bridged_cids is not None:
            # We were actively filtering to upcoming+unmapped -- empty just means
            # everything upcoming is already bridged, not a broken fetch.
            print("No new bridge rows built — nothing upcoming and still unmapped this run.")
            return
        sys.exit("No bridge rows built (no markets exposed positionIds).")

    if dry_run:
        print("DRY RUN — sample rows:")
        for r in rows[:5]:
            print(f"  {r}")
        print(f"(total {len(rows)} rows; not written)")
        return

    if client is None or target is None:  # non-dry-run path always builds both above
        raise RuntimeError("BigQuery client/target was not initialized for the write path")
    stage = qualify(client, STAGE)
    print(f"Upserting {len(rows)} rows into {target} (via {stage})...")
    n = stage_and_merge(client, target, stage, SCHEMA, rows, KEY_COL)
    print(f"  staged {n} rows, MERGE complete.")


def main():
    p = argparse.ArgumentParser(description="Load the Polymarket position_id<->clob_token_id bridge to BigQuery.")
    p.add_argument(
        "--cids-file",
        default=None,
        help="File of extra condition_ids (one per line) to seed alongside the active catalog.",
    )
    p.add_argument(
        "--backfill-since",
        default=None,
        help="ISO date (YYYY-MM-DD): also backfill historical legs recorded in "
        "polymarket_combo_mapping since this date (Gamma position_ids reverse-lookup).",
    )
    p.add_argument("--limit", type=int, default=None, help="Cap markets/legs processed (dry-run / testing).")
    p.add_argument("--dry-run", action="store_true", help="Fetch + build rows, print a sample, write nothing.")
    p.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Also re-enrich condition_ids already bridged in a prior run (normally skipped).",
    )
    args = p.parse_args()
    load(
        cids_file=args.cids_file,
        backfill_since=args.backfill_since,
        limit=args.limit,
        dry_run=args.dry_run,
        refresh_existing=args.refresh_existing,
    )


if __name__ == "__main__":
    main()
