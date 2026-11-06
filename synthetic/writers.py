"""Build + write synthetic rows to BigQuery.

Two targets:
  * opticodds_us.opticodds_fixtures  — synthetic fixtures (id/game_id `wsdsyn-…`)
  * markets_us.market_mapping        — GREG mapping rows (synth + backfill)

Idempotent per run (delete-our-rows-then-insert). Fixtures whose event has left
Kalshi's open set are flipped to status='completed' (housekeeping: drops them off
the odds screen; safety is already handled real-time by the order-book liquidity
filters in MMutils.handlers.fair_price_calculator). Rows older than the window are
pruned.

IAM/guard note: writing opticodds_us requires it in BigQuery/client.WRITABLE_DATASETS
AND the mmmapper VM service account holding BQ dataEditor on opticodds_us — the
latter is a deploy prerequisite outside this code.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

from google.cloud import bigquery

from BigQuery.client import sandbox_query
from synthetic.adapters import SyntheticSeries
from synthetic.coverage import SYNTHETIC_PREFIX

FIXTURES_TABLE = "opticodds_us.opticodds_fixtures"
MAPPING_TABLE = "markets_us.market_mapping"
OVERRIDE_TOPIC = "mapping-override-us"
OVERRIDE_PROVENANCE = {"source": "mm-synthetic"}
# Scalar form of the provenance attribute, used by load_published_overrides to
# recognise rows this job published under a REAL Optic game_id (backfill).
OVERRIDE_SOURCE = OVERRIDE_PROVENANCE["source"]


def synthetic_game_id(event_ticker: str) -> str:
    """Deterministic, collision-proof, self-identifying id for a synthetic event."""
    return SYNTHETIC_PREFIX + event_ticker


def build_fixture_row(gid: str, series: SyntheticSeries, home: str, away: str,
                      start_iso: str, status: str, now_iso: str) -> dict:
    """One opticodds_fixtures row. Sets BOTH flat *_id and nested structs
    (the RFQ mapper + ALLOWED_SPORTS read flat sport_id; odds-screen reads flat
    id + nested .name). Everything else omitted → NULL."""
    return {
        "id": gid,
        "game_id": gid,
        "sport_id": series.sport_id,
        "league_id": series.league_id,
        "start_date": start_iso,
        "home_team_display": home,
        "away_team_display": away,
        "status": status,
        "is_live": status == "live",
        "sport": {"id": series.sport_id, "name": series.sport_name},
        "league": {"id": series.league_id, "name": series.league_name},
        "publish_time": now_iso,
    }


def build_mapping_rows(series: SyntheticSeries, game_id: str, fixture_id: str,
                       ticker_a: str, name_a: str, ticker_b: str, name_b: str,
                       start_iso: str, now_iso: str) -> list[dict]:
    """Four market_mapping rows for a 2-competitor match: each side ticker gets a
    yes and a no row (the mapper joins on (ticker, side)). game_id/fixture_id are
    `wsdsyn-…` for a synthesized fixture or the REAL Optic ids for a backfill.

    Canonical home/away/selection are best-effort display names; for in-play the
    load-bearing fields are source_ids(ticker+side) → game_id/fixture_id."""
    home, away = sorted([name_a, name_b])

    def row(ticker: str, side: str, selection: str, canonical_side: str) -> dict:
        return {
            "sport": series.sport_id,
            "league": series.league_id,
            "start_date": start_iso,
            "home": home,
            "away": away,
            "market_type": "moneyline",
            "entity": None,
            "line": None,
            "side": canonical_side,
            "group_key": None,
            "sportsbook": "Kalshi",
            "game_id": game_id,
            "fixture_id": fixture_id,
            "market_id": series.optic_market_id,
            "selection": selection,
            "selection_line": None,
            "points": None,
            "grouping_key": "default",
            "source_ids": {"market_id": ticker, "selection_id": side},
            "last_updated": now_iso,
        }

    return [
        row(ticker_a, "yes", name_a, name_a),
        row(ticker_a, "no", name_b, name_b),
        row(ticker_b, "yes", name_b, name_b),
        row(ticker_b, "no", name_a, name_a),
    ]


def build_override_message(
    row: dict,
    active: bool = True,
    *,
    mapping_source: str | None = None,
) -> dict:
    """Translate one market_mapping row (build_mapping_rows shape) into a
    mapping_override Pub/Sub message (opticodds mapping_override.proto).

    Same ticker↔selection wiring as the GREG row — the override just puts it on the
    ORIGINAL lineage (`prices_dedup_state`) that the Kalshi orderbook price pipeline
    reads, so the leg actually prices instead of falling back to 1.0. `source_ids` is
    a JSON STRING in the proto; `points`/`selection_points` are line-less markets → 0.
    """
    src = row.get("source_ids") or {}
    msg = {
        "game_id": row["game_id"],
        "market_id": row["market_id"],
        "sportsbook": row["sportsbook"],
        "selection": row["selection"],
        "selection_line": row.get("selection_line") or "",
        "points": float(row.get("points") or 0.0),
        "selection_points": float(row.get("selection_points") or 0.0),
        "grouping_key": row.get("grouping_key") or "default",
        "source_ids": json.dumps(
            {"market_id": src.get("market_id"), "selection_id": src.get("selection_id")}
        ),
        "active": active,
    }
    provenance = (mapping_source or "").strip()
    if provenance:
        msg["mapping_source"] = provenance
    return msg


def _override_key(msg: dict) -> tuple:
    """Composite key matching prices_state_merge.sql's GROUP BY for overrides."""
    return (
        msg["game_id"],
        msg["market_id"],
        (msg.get("sportsbook") or "").lower(),
        msg["selection"],
        msg.get("selection_line") or "",
        float(msg.get("points") or 0),
        float(msg.get("selection_points") or 0),
        msg.get("grouping_key") or "default",
    )


def _source_ids_equal(a: str | None, b: str | None) -> bool:
    """Compare two source_ids JSON strings by CONTENT, not as text.

    The two sides are produced by different writers and never match as text:
    `build_override_message` uses `json.dumps`, which separates with ", " and
    ": ", while `load_published_overrides` reads BigQuery's TO_JSON_STRING, which
    is compact and (for a JSON-typed column) normalises key order:

        built    {"market_id": "KXNASCARRACE-WIN2PB26-CODA", "selection_id": "yes"}
        readback {"market_id":"KXNASCARRACE-WIN2PB26-CODA","selection_id":"yes"}

    Comparing the raw strings therefore marked EVERY key as changed on EVERY run,
    so the set-diff republished the entire desired set every 15 minutes (79
    NASCAR + ~94 ITF messages a tick, all identical to what was already
    published). Nothing mis-priced -- the messages were byte-identical and still
    active -- but it defeated the point of the diff and made the `unchanged`
    count in the log useless for spotting a genuine relist.

    Falls back to text equality when either side is not parseable JSON, so a
    malformed value is treated as changed rather than silently equal.
    """
    if a == b:
        return True
    try:
        return json.loads(a or "{}") == json.loads(b or "{}")
    except (TypeError, ValueError):
        return False


def load_published_overrides(client) -> dict[tuple, dict]:
    """Read back currently-active overrides this job published, from mapping_override.

    Returns {override_key: message_dict} for each active override this job
    has published. Provenance is established two ways, OR'd:

      * ``wsdsyn-`` game_id prefix — only the synthetic job publishes these, and
        it covers the ~50k legacy rows written before the Pub/Sub attribute
        existed, which is why the prefix clause cannot simply be dropped.
      * ``attributes.source = 'mm-synthetic'`` — required for BACKFILLED rows,
        which publish under Optic's REAL game_id and so fail the prefix test.
        Every backfilled row is new, so all of them carry the attribute; the
        legacy caveat above does not apply to them.

    Both clauses are needed. With only the prefix, a backfilled override is
    invisible to the set-diff in :func:`publish_overrides`: it is re-published
    every tick and, once it leaves the desired set, is NEVER retracted (it is in
    neither ``published`` nor ``desired``), leaving ``active=true`` against a real
    Optic fixture with no teardown.
    Uses GROUP BY + ARRAY_AGG (not ROW_NUMBER + PARTITION BY) to match
    prices_state_merge.sql and avoid the FLOAT64 PARTITION BY restriction.
    """
    sql = f"""
        SELECT * FROM (
            SELECT
                game_id, market_id, selection,
                IFNULL(selection_line, '') AS selection_line,
                IFNULL(points, 0) AS points,
                IFNULL(selection_points, 0) AS selection_points,
                grouping_key,
                ARRAY_AGG(sportsbook ORDER BY publish_time DESC LIMIT 1)[OFFSET(0)] AS sportsbook,
                TO_JSON_STRING(ARRAY_AGG(source_ids ORDER BY publish_time DESC LIMIT 1)[OFFSET(0)]) AS source_ids_json,
                ARRAY_AGG(active ORDER BY publish_time DESC LIMIT 1)[OFFSET(0)] AS active
            FROM `{client.project}.opticodds_us.mapping_override`
            WHERE STARTS_WITH(game_id, '{SYNTHETIC_PREFIX}')
               OR JSON_VALUE(attributes, '$.source') = '{OVERRIDE_SOURCE}'
            GROUP BY game_id, market_id, LOWER(sportsbook), selection,
                     IFNULL(selection_line, ''), IFNULL(points, 0),
                     IFNULL(selection_points, 0), grouping_key
        )
        WHERE active IS TRUE
    """
    result = {}
    for r in client.query(sql).result():
        msg = {
            "game_id": r.game_id,
            "market_id": r.market_id,
            "sportsbook": r.sportsbook,
            "selection": r.selection,
            "selection_line": r.selection_line or "",
            "points": float(r.points or 0),
            "selection_points": float(r.selection_points or 0),
            "grouping_key": r.grouping_key or "default",
            "source_ids": r.source_ids_json or "{}",
            "active": True,
        }
        result[_override_key(msg)] = msg
    return result


def publish_overrides(client, mapping_rows: list[dict], dry_run: bool = False) -> dict:
    """Set-diff override publish: enable new, retract stale, skip unchanged.

    Compares desired overrides (from this run's mapping_rows) against
    currently-published active overrides (read from BQ). Publishes:
      - active=true  for keys in desired - published
      - active=false for keys in published - desired
      - nothing      for keys in both (already correct)

    Safety: if desired is empty, retraction is skipped (protects against
    a transient Kalshi API failure causing mass unmapping).
    """
    # Every mapping row gets an override, synthetic or backfilled. A backfilled
    # row carries Optic's real game_id — that is the whole point (it puts the
    # Kalshi ticker on Optic's fixture rather than a minted one), and
    # load_published_overrides recognises it by the mm-synthetic provenance
    # attribute so the retraction diff stays correct.
    #
    # YES SIDE ONLY -- this is load-bearing, do not "simplify" it away.
    #
    # `_override_key` deliberately excludes source_ids, because it must match
    # prices_state_merge.sql's `active_overrides` GROUP BY exactly (game_id,
    # market_id, LOWER(sportsbook), selection, selection_line, points,
    # selection_points, grouping_key). So the key collapses on `selection`.
    #
    # build_mapping_rows emits FOUR rows for a 2-way match:
    #     (ticker_a, yes, sel=name_a)  (ticker_a, no, sel=name_b)
    #     (ticker_b, yes, sel=name_b)  (ticker_b, no, sel=name_a)
    # Keyed on selection those are only TWO keys {name_a, name_b}, and rows 3-4
    # overwrite rows 1-2, so BOTH survivors carried ticker_b and ticker_a was
    # silently dropped. Measured 2026-09-04: all 80 live synthetic events had
    # exactly 1.0 distinct tickers mapped instead of 2 -- i.e. half of every
    # event's Kalshi coverage was missing, on doubles as well as singles, since
    # the job went live.
    #
    # Taking the yes side of EACH ticker gives two keys carrying two DIFFERENT
    # tickers, which is exactly how every hand-built override in production is
    # shaped (checked against the manual set: 3-way soccer = 3 yes rows with 3
    # tickers, 2-way UFC = 2 yes rows with 2 tickers, zero `no` rows anywhere).
    #
    # Cost of dropping the `no` rows: measured 24 of 320,795 ITF legs (0.007%)
    # arrive on a `no` side, and all 24 were ALREADY unmapped, so the slot we
    # were spending on (ticker_b, no) was worth nothing. Kalshi's two tickers
    # already express both directions -- `-GAR` yes and `-ROD` yes -- so nothing
    # needs to be inferred by 1-x.
    #
    # Outright rows are already yes-side only (build_outright_mapping_rows), so
    # this filter is a no-op for them.
    #
    # NOTE this affects the OVERRIDE path only. GREG rows keep all four sides:
    # mapping_loader's greg_raw partitions by (market_id, selection_id), so it
    # can represent them, and reconcile_mappings still receives the full set.
    desired: dict[tuple, dict] = {}
    for r in mapping_rows:
        if (r.get("source_ids") or {}).get("selection_id") != "yes":
            continue
        msg = build_override_message(r)
        key = _override_key(msg)
        prev = desired.get(key)
        if prev is not None and not _source_ids_equal(
                json.dumps(prev.get("source_ids")), json.dumps(msg.get("source_ids"))):
            # Two different tickers collapsing onto one key is the bug above.
            # Filtering to the yes side should make it impossible; shout if not
            # rather than silently dropping one, which is how it hid for weeks.
            print(f"[synthetic] WARNING override key collision, one ticker will be "
                  f"LOST: key={key} kept={prev.get('source_ids')} "
                  f"dropped={msg.get('source_ids')}", file=sys.stderr)
        desired[key] = msg

    published = load_published_overrides(client)

    to_enable = set(desired) - set(published)
    to_retract = set(published) - set(desired)
    unchanged = set(desired) & set(published)

    # Re-publish keys whose source_ids changed (e.g. Kalshi relisted a market
    # with a different side code). Without this, the stale ticker persists
    # because the key is the same and the diff says "unchanged". Compared by
    # CONTENT -- the two sides are serialized differently, so a text compare
    # fires on every key every run (see _source_ids_equal).
    changed = {k for k in unchanged
               if not _source_ids_equal(desired[k]["source_ids"],
                                        published[k]["source_ids"])}
    to_enable |= changed
    unchanged -= changed

    if not desired and to_retract:
        print(f"[synthetic] WARNING: desired set is empty but {len(to_retract)} overrides "
              f"are published — skipping retraction (possible API failure)", file=sys.stderr)
        to_retract = set()

    if dry_run:
        print(f"[synthetic] dry-run — {len(desired)} desired, {len(to_enable)} to enable, "
              f"{len(to_retract)} to retract, {len(unchanged)} unchanged", file=sys.stderr)
        return {"enabled": 0, "retracted": 0, "unchanged": len(unchanged),
                "desired": len(desired), "would_enable": len(to_enable),
                "would_retract": len(to_retract)}

    if not to_enable and not to_retract:
        print(f"[synthetic] overrides: {len(unchanged)} unchanged, nothing to publish",
              file=sys.stderr)
        return {"enabled": 0, "retracted": 0, "unchanged": len(unchanged)}

    from google.cloud import pubsub_v1
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(client.project, OVERRIDE_TOPIC)

    for key in to_enable:
        msg = desired[key]
        publisher.publish(
            topic_path, json.dumps(msg).encode("utf-8"),
            **OVERRIDE_PROVENANCE,
        ).result()

    for key in to_retract:
        msg = dict(published[key])
        msg["active"] = False
        publisher.publish(
            topic_path, json.dumps(msg).encode("utf-8"),
            **OVERRIDE_PROVENANCE,
        ).result()

    print(f"[synthetic] overrides: {len(to_enable)} enabled, {len(to_retract)} retracted, "
          f"{len(unchanged)} unchanged (project={client.project})", file=sys.stderr)
    return {"enabled": len(to_enable), "retracted": len(to_retract), "unchanged": len(unchanged)}


def build_outright_fixture_row(gid: str, series: SyntheticSeries, start_iso: str,
                              status: str, now_iso: str) -> dict:
    """One opticodds_fixtures row for an N-runner OUTRIGHT (F1/NASCAR race winner).

    Mirrors the manual F1/NASCAR process byte-for-byte (verified against the
    surviving belgf1 / hungf1 / brickyard400 rows in rs-marketmaking, which took
    210 confirmed bets between them):
      * home/away are EMPTY STRINGS — a 22-car field has no two sides.
      * the nested structs use name == id, lower case (NOT a display-cased name).
      * status is passed in; the manual rows carry '' and is_live False. Do NOT
        hardcode 'live' the way the 2-way path does: an F1 race is listed ~274h
        ahead, so a constant 'live' would read as in-play for eleven days.
    """
    return {
        "id": gid,
        "game_id": gid,
        "sport_id": series.sport_id,
        "league_id": series.league_id,
        "start_date": start_iso,
        "home_team_display": "",
        "away_team_display": "",
        "status": status,
        "is_live": status == "live",
        "sport": {"id": series.sport_id, "name": series.sport_name},
        "league": {"id": series.league_id, "name": series.league_name},
        "publish_time": now_iso,
    }


def build_outright_mapping_rows(series: SyntheticSeries, game_id: str, fixture_id: str,
                                markets: list[dict], start_iso: str,
                                now_iso: str) -> list[dict]:
    """One market_mapping row per contract for an OUTRIGHT — YES SIDE ONLY.

    An outright is N independent binary contracts, one per runner, so there is no
    "other side" to mirror: contract X's yes is "X wins" and that is the whole
    mapping. This matches every manual script in scripts/mapping_overrides/
    (`"selection_id": "yes"`, no "no" row) and means each row already has a
    distinct `selection`, so `_override_key` cannot collapse two rows onto one
    key the way it does for the 2-way path.

    `selection` comes from yes_sub_title. Unlike ITF there is no Optic mapping to
    match against (Optic publishes no motorsports fixtures at all), so the name
    only has to be stable, not to equal an Optic competitor string.
    """
    rows: list[dict] = []
    for m in markets:
        ticker = m["ticker"]
        # No subtitle: the whole ticker stands in, as an opaque label.
        selection = m.get("yes_sub_title") or ticker
        rows.append({
            "sport": series.sport_id,
            "league": series.league_id,
            "start_date": start_iso,
            "home": "",
            "away": "",
            "market_type": series.optic_market_id,
            "entity": None,
            "line": None,
            "side": selection,
            "group_key": None,
            "sportsbook": "Kalshi",
            "game_id": game_id,
            "fixture_id": fixture_id,
            "market_id": series.optic_market_id,
            "selection": selection,
            "selection_line": None,
            "points": None,
            "grouping_key": "default",
            "source_ids": {"market_id": ticker, "selection_id": "yes"},
            "last_updated": now_iso,
        })
    return rows


def _load_json(client, table: str, rows: list[dict]) -> None:
    """Append rows to a BQ table via a JSON load job (schema read from the table)."""
    if not rows:
        return
    full = f"{client.project}.{table}"
    schema = client.get_table(full).schema
    job = client.load_table_from_json(
        rows, full,
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    if job.errors:
        raise RuntimeError(f"load into {table} failed: {job.errors}")


def reconcile_fixtures(client, live_rows: list[dict], window_start_iso: str) -> None:
    """Upsert live synthetic fixtures; flip dropped ones to completed; prune old."""
    live_ids = [r["id"] for r in live_rows]
    part = f"start_date >= TIMESTAMP('{window_start_iso}')"

    if live_ids:
        id_list = ", ".join(f"'{i}'" for i in live_ids)
        sandbox_query(client, f"""
            DELETE FROM `{client.project}.{FIXTURES_TABLE}`
            WHERE {part} AND id IN ({id_list})
        """)
    _load_json(client, FIXTURES_TABLE, live_rows)

    # Dropped from Kalshi open → completed (housekeeping; removes from odds screen).
    not_in = f"AND id NOT IN ({', '.join(repr(i) for i in live_ids)})" if live_ids else ""
    sandbox_query(client, f"""
        UPDATE `{client.project}.{FIXTURES_TABLE}`
        SET status = 'completed', is_live = FALSE
        WHERE {part} AND STARTS_WITH(id, '{SYNTHETIC_PREFIX}')
          AND COALESCE(status, '') != 'completed' {not_in}
    """)

    # Prune rows older than the window.
    sandbox_query(client, f"""
        DELETE FROM `{client.project}.{FIXTURES_TABLE}`
        WHERE start_date < TIMESTAMP('{window_start_iso}')
          AND STARTS_WITH(id, '{SYNTHETIC_PREFIX}')
    """)


def reconcile_mappings(client, rows: list[dict], window_start_iso: str) -> None:
    """Delete OUR synthetic mapping rows in-window, then insert desired.

    Scoped strictly to `game_id LIKE 'wsdsyn-%'` — NOT by ticker prefix. The GREG
    pipeline's itf_men / itf_women leagues write real (non-synthetic)
    `KXITFMATCH` / `KXITFWMATCH` rows into this same table; a prefix-scoped delete
    would wipe them every run. Doubles are always synthesized, so our rows always
    carry a `wsdsyn-` game_id and this delete can only touch our own rows.
    """
    own = f"STARTS_WITH(game_id, '{SYNTHETIC_PREFIX}')"
    part = f"start_date >= TIMESTAMP('{window_start_iso}')"
    sandbox_query(client, f"""
        DELETE FROM `{client.project}.{MAPPING_TABLE}`
        WHERE {part} AND {own}
    """)
    _load_json(client, MAPPING_TABLE, rows)
    # Prune old
    sandbox_query(client, f"""
        DELETE FROM `{client.project}.{MAPPING_TABLE}`
        WHERE start_date < TIMESTAMP('{window_start_iso}') AND {own}
    """)


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (for last_updated / publish_time)."""
    from datetime import UTC
    return datetime.now(UTC).isoformat()
