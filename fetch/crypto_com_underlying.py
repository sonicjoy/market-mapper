"""Catalogue source from crypto_underlying_securities.

Primary catalogue source for ``fetch/crypto_com.py``.  Upstream processes
FIX SecurityDef messages into ``processed_upstream_us.crypto_underlying_securities``
with parsed ``meta_*`` fields.  This module synthesizes flat records the
mapper already consumes.

Fixture home/away identity comes only from a security_def seed
(``EXTERNAL_HOME_ID`` / ``EXTERNAL_AWAY_ID``).  Rows without a seed are
dropped (``skipped_no_identity``).  ``fetch/crypto_com_security_def.py``
supplements contracts missing here.  See docs/adding-crypto.md.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

from BigQuery.alerts import build_publisher
from BigQuery.client import (
    CRYPTO_UNDERLYING_SECURITIES_TABLE,
    is_missing_bq_table,
    ro_client,
    ro_query,
)
from fetch.crypto_com_identity import (
    build_identity_index,
    symbol_prefix,
)
from fetch.crypto_com_underlying_flat import (
    flat_prop_record,
    underlying_row_to_flat,
)

logger = logging.getLogger(__name__)

MAPPABLE_MARKET_GROUPS = (
    "Game Line",
    "Fight Line",
    "Player Prop",
    "Team Prop",
    "Game Prop",
    "Fight Prop",
)

# Default look-back for the processed catalogue tables.  Props for games
# 2-3 days out are (re)published in bursts, and rows for fixtures with
# active RFQs can go stale while the symbol stays live.
#
# Must span listing-to-kickoff, not just "recent".  crypto.com lists a
# soccer fixture in one burst ~14 days before kickoff and never
# republishes it, while Optic only exposes that fixture once it is inside
# FIXTURE_HORIZON_HOURS (7 days).  At the previous 7-day look-back the
# listing therefore fell out of the window exactly as the fixture became
# mappable — the two never overlapped and MLS / La Liga produced zero
# crypto rows for months (every in-horizon fixture was last published
# 8-15 days earlier).  Keep a week of headroom over the 14-day burst.
CATALOGUE_WINDOW_MINUTES = 21 * 24 * 60
# Back-compat alias.
UNDERLYING_WINDOW_MINUTES = CATALOGUE_WINDOW_MINUTES

# Drop listings whose fixture already kicked off this long ago.  The
# look-back above is a freshness proxy for "still listed"; on its own a
# 21-day window would drag three weeks of finished fixtures into the
# catalogue file.  Filtering on the event date instead keeps the output
# proportional to live fixtures rather than to publish volume.  Rows with
# an absent or unparseable event date are kept — never drop a symbol we
# cannot classify.
CATALOGUE_EVENT_STALE_HOURS = 24

# crypto.com publishes meta_event_date as an ISO-8601 string with offset.
# Shared with crypto_com_security_def so both catalogue sources scope to
# live fixtures identically.
EVENT_DATE_TS = r"safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', meta_event_date)"

UNDERLYING_CATALOGUE_QUERY = rf"""
SELECT
  symbol, security_id,
  meta_league, meta_sports_grouping, meta_event_date,
  meta_predict_market_type, meta_predict_contract_type,
  meta_predict_period_type, meta_predict_event_type,
  meta_event_name, meta_name, meta_predict_market_id,
  meta_predict_outcome_id, meta_participant, security_desc,
  meta_predict_outcome_type, meta_predict_value, meta_team_id,
  publish_time
FROM `processed_upstream_us.crypto_underlying_securities`
WHERE meta_predict_market_type IN (
  "Game Line", "Fight Line", "Player Prop", "Team Prop", "Game Prop", "Fight Prop")
  AND publish_time > timestamp_sub(current_timestamp(), INTERVAL {{minutes}} MINUTE)
  AND ({EVENT_DATE_TS} IS NULL
    OR {EVENT_DATE_TS} > timestamp_sub(
         current_timestamp(), INTERVAL {CATALOGUE_EVENT_STALE_HOURS} HOUR))
QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY publish_time DESC) = 1
"""  # nosec B608 — interpolands are module constants, not caller input

# Back-compat alias used by tests and callers.
UNDERLYING_PROPS_QUERY = UNDERLYING_CATALOGUE_QUERY.replace(
    "WHERE meta_predict_market_type IN (\n"
    '  "Game Line", "Fight Line", "Player Prop", "Team Prop", "Game Prop", "Fight Prop")',
    'WHERE meta_predict_market_type = "Player Prop"',
)

# How many no-identity prefixes to include in the application-alerts body.
_NO_IDENTITY_ALERT_SAMPLE = 10

# How many dropped game-line symbols to include in the alert log line before
# truncating, so a systemic mapper break can't flood the logs.
_UNPARSED_LOG_SAMPLE = 15


@dataclass(frozen=True, slots=True)
class UnderlyingStats:
    """Counts from an underlying-securities catalogue merge."""

    game_lines: int = 0
    player_props: int = 0
    team_props: int = 0
    game_props: int = 0
    skipped_no_identity: int = 0
    skipped_duplicate: int = 0
    skipped_unparsed_game_line: int = 0
    # Distinct fixture prefixes dropped for missing security_def EXTERNAL_*
    # seed (or blank participant names on a seeded identity).
    no_identity_prefixes: tuple[str, ...] = ()


def _underlying_row_to_dict(row) -> dict:
    """Convert a BigQuery row object to a plain dict."""
    pt = row.publish_time
    return {
        "symbol": row.symbol,
        "security_id": row.security_id,
        "meta_league": row.meta_league,
        "meta_sports_grouping": row.meta_sports_grouping,
        "meta_event_date": row.meta_event_date,
        "meta_predict_market_type": row.meta_predict_market_type,
        "meta_predict_contract_type": row.meta_predict_contract_type,
        "meta_predict_period_type": row.meta_predict_period_type,
        "meta_predict_event_type": row.meta_predict_event_type,
        "meta_event_name": row.meta_event_name,
        "meta_name": row.meta_name,
        "meta_predict_market_id": row.meta_predict_market_id,
        "meta_predict_outcome_id": row.meta_predict_outcome_id,
        "meta_participant": row.meta_participant,
        "security_desc": row.security_desc,
        "meta_predict_outcome_type": row.meta_predict_outcome_type,
        "meta_predict_value": row.meta_predict_value,
        "meta_team_id": row.meta_team_id,
        "publish_time": pt.isoformat() if pt is not None else None,
    }


def synthesize_prop_records(
    props: list[dict],
    identity_index: dict[str, dict],
    existing_security_ids: set[str],
) -> tuple[list[dict], int]:
    """Turn underlying-securities prop rows into flat catalogue records."""
    records: list[dict] = []
    skipped = 0
    for p in props:
        sid = p.get("security_id")
        if sid is None or sid in existing_security_ids:
            continue
        identity = identity_index.get(symbol_prefix(p.get("symbol")) or "")
        if identity is None:
            skipped += 1
            continue
        records.append(flat_prop_record(p, identity))
        existing_security_ids.add(sid)
    return records, skipped


def _resolve_fixture_identity(
    row: dict,
    working_index: dict[str, dict],
) -> dict | None:
    """Look up fixture identity from the security_def seed index only."""
    prefix = symbol_prefix(row.get("symbol")) or ""
    return working_index.get(prefix)


def _process_catalogue_row(
    row: dict,
    working_index: dict[str, dict],
    existing_security_ids: set[str],
    no_identity_prefixes: set[str],
) -> tuple[dict | None, str | None, str | None]:
    """Process one underlying row; return (record, market_group, skip_reason)."""
    sid = row.get("security_id")
    if sid is None or sid in existing_security_ids:
        return None, None, "duplicate" if sid is not None else None

    identity = _resolve_fixture_identity(row, working_index)
    if identity is None:
        prefix = symbol_prefix(row.get("symbol"))
        if prefix:
            no_identity_prefixes.add(prefix)
        return None, None, "no_identity"

    flat, market_group, skip_reason = underlying_row_to_flat(row, identity)
    if flat is None:
        if skip_reason == "no_identity":
            prefix = symbol_prefix(row.get("symbol"))
            if prefix:
                no_identity_prefixes.add(prefix)
        return None, None, skip_reason

    existing_security_ids.add(sid)
    return flat, market_group, None


def _describe_unparsed(row: dict) -> str:
    """One-line diagnostic for a dropped game-line symbol."""
    return (
        f"{row.get('symbol')} "
        f"[{row.get('meta_predict_contract_type')}] "
        f"event={row.get('meta_event_name')!r} "
        f"desc={row.get('security_desc')!r}"
    )


def synthesize_catalogue_records(
    rows: list[dict],
    identity_index: dict[str, dict],
    existing_security_ids: set[str],
) -> tuple[list[dict], UnderlyingStats]:
    """Turn underlying-securities rows into flat catalogue records."""
    no_identity_prefixes: set[str] = set()
    records, tally, unparsed_game_lines = _collect_catalogue_rows(
        rows,
        dict(identity_index),
        existing_security_ids,
        no_identity_prefixes,
    )
    _log_unparsed_game_lines(unparsed_game_lines)
    return records, UnderlyingStats(
        # Fight Line/Prop are UFC analogues of Game Line/Prop.
        game_lines=tally["Game Line"] + tally["Fight Line"],
        player_props=tally["Player Prop"],
        team_props=tally["Team Prop"],
        game_props=tally["Game Prop"] + tally["Fight Prop"],
        skipped_no_identity=tally["no_identity"],
        skipped_duplicate=tally["duplicate"],
        skipped_unparsed_game_line=len(unparsed_game_lines),
        no_identity_prefixes=tuple(sorted(no_identity_prefixes)),
    )


def _collect_catalogue_rows(
    rows: list[dict],
    working_index: dict[str, dict],
    existing_security_ids: set[str],
    no_identity_prefixes: set[str],
) -> tuple[list[dict], Counter[str], list[dict]]:
    """Dispatch each underlying row to a record or a skip tally.

    Returns ``(records, tally, unparsed_game_lines)`` where ``tally`` counts
    kept market groups and skip reasons, and ``unparsed_game_lines`` holds the
    dropped-with-resolved-fixture rows logged by ``_log_unparsed_game_lines``.
    """
    records: list[dict] = []
    tally: Counter[str] = Counter()
    unparsed_game_lines: list[dict] = []
    for row in rows:
        flat, market_group, skip_reason = _process_catalogue_row(
            row,
            working_index,
            existing_security_ids,
            no_identity_prefixes,
        )
        if skip_reason == "unparsed_game_line":
            unparsed_game_lines.append(row)
        elif skip_reason:
            tally[skip_reason] += 1
        elif flat is not None and market_group is not None:
            tally[market_group] += 1
            records.append(flat)
    return records, tally, unparsed_game_lines


def _log_unparsed_game_lines(rows: list[dict]) -> None:
    """Alert on game-line rows dropped because their outcome couldn't be parsed.

    A resolved fixture whose outcome/line cannot be inferred is a mapper gap
    (a bug, an unhandled contract type, or alias drift), not a benign miss, so
    it is logged at WARNING with a capped per-symbol sample for diagnosis.
    """
    if not rows:
        return
    sample = "; ".join(_describe_unparsed(r) for r in rows[:_UNPARSED_LOG_SAMPLE])
    suffix = "" if len(rows) <= _UNPARSED_LOG_SAMPLE else f" (+{len(rows) - _UNPARSED_LOG_SAMPLE} more)"
    logger.warning(
        "crypto game-line mapping gap: dropped %d resolved-fixture rows with unparseable outcome/line: %s%s",
        len(rows),
        sample,
        suffix,
    )


def format_missing_seed_alert(stats: UnderlyingStats) -> str | None:
    """Build application-alerts text for fixtures dropped without usable identity.

    Covers missing EXTERNAL_* seed and seeded IDs with blank participant names.
    Returns None when there is nothing to alert on.
    """
    prefixes = stats.no_identity_prefixes
    if not prefixes and not stats.skipped_no_identity:
        return None
    n = len(prefixes) if prefixes else stats.skipped_no_identity
    sample = list(prefixes[:_NO_IDENTITY_ALERT_SAMPLE])
    if len(prefixes) > _NO_IDENTITY_ALERT_SAMPLE:
        sample_label = ", ".join(sample) + f" (+{len(prefixes) - _NO_IDENTITY_ALERT_SAMPLE} more)"
    elif sample:
        sample_label = ", ".join(sample)
    else:
        sample_label = "(no prefix)"
    return (
        f"crypto.com fixtures dropped (no usable security_def identity): "
        f"{n} — prefixes: {sample_label}"
    )

def publish_missing_seed_alert(stats: UnderlyingStats) -> None:
    """Best-effort Pub/Sub warning for missing-seed drops; never raises."""
    text = format_missing_seed_alert(stats)
    if text is None:
        return
    try:
        publisher = build_publisher()
        try:
            publisher.publish("warning", text)
        finally:
            publisher.close()
    except Exception:
        logger.exception("failed to publish missing-seed crypto identity alert")


def fetch_underlying_catalogue(client, minutes: int) -> list[dict]:
    """Read latest-per-symbol catalogue rows from crypto_underlying_securities."""
    return [_underlying_row_to_dict(r) for r in _query_underlying_rows(client, minutes)]


def _query_underlying_rows(client, minutes: int) -> list:
    """Raw BigQuery rows from crypto_underlying_securities."""
    try:
        return list(ro_query(client, UNDERLYING_CATALOGUE_QUERY.format(minutes=minutes)))
    except Exception as exc:
        if is_missing_bq_table(exc, CRYPTO_UNDERLYING_SECURITIES_TABLE):
            logger.warning(
                "%s not found — skipping underlying catalogue (crypto.com upstream not provisioned in this project)",
                CRYPTO_UNDERLYING_SECURITIES_TABLE,
            )
            return []
        raise


def fetch_underlying_props(client, minutes: int) -> list[dict]:
    """Read latest-per-symbol Player Prop rows from crypto_underlying_securities."""
    rows = fetch_underlying_catalogue(client, minutes)
    return [r for r in rows if r.get("meta_predict_market_type") == "Player Prop"]


def build_catalogue_from_underlying(
    client,
    minutes: int,
    *,
    seed_identity_index: dict[str, dict] | None = None,
) -> tuple[list[dict], UnderlyingStats, int, object | None]:
    """Build the catalogue from crypto_underlying_securities (primary source).

    ``seed_identity_index`` (fixture ids published on security_def) is required
    for Game/Fight Line and bridged props.  Unseeded fixtures are dropped.
    """
    raw_rows = _query_underlying_rows(client, minutes)
    if not raw_rows:
        return [], UnderlyingStats(), 0, None

    rows = [_underlying_row_to_dict(r) for r in raw_rows]
    identity_index = dict(seed_identity_index or {})
    existing: set[str] = set()
    records, stats = synthesize_catalogue_records(rows, identity_index, existing)
    return records, stats, len(rows), _newest_publish(raw_rows)


def _newest_publish(rows) -> object | None:
    newest = None
    for row in rows:
        pt = row.publish_time
        if pt is not None and (newest is None or pt > newest):
            newest = pt
    return newest


def collect_underlying_catalogue(
    raw_contracts: list[dict],
    minutes: int,
) -> tuple[list[dict], UnderlyingStats]:
    """Fetch and synthesize catalogue records from underlying_securities."""
    rows = fetch_underlying_catalogue(ro_client(), minutes)
    if not rows:
        return [], UnderlyingStats()

    identity_index = build_identity_index(raw_contracts)
    existing = {str(c["SecurityID"]) for c in raw_contracts if c.get("SecurityID")}
    return synthesize_catalogue_records(rows, identity_index, existing)


def collect_underlying_props(
    contracts: list[dict],
    minutes: int,
) -> tuple[list[dict], int]:
    """Fetch player props and synthesize records bridged to `contracts`."""
    records, stats = collect_underlying_catalogue(contracts, minutes)
    props = [r for r in records if r.get("eventMetaPREDICT_MARKET_TYPE") == "Player Prop"]
    return props, stats.skipped_no_identity
