"""Override lane: console overrides for venues that read ``markets_us.market_mapping``.

A console ``mapping_override`` materialises into ``opticodds_us.opticodds_mapping``.
crypto.com (mmcryptocom ``MappingService``, keyed on ``source_ids.symbol``) and
Polymarket (USA) (mmpolymarketusrfq ``mapping_lever``, keyed on
``source_ids.market_id``) never read that table, so their overrides are no-ops
there. This lane turns their active overrides into ``market_mapping`` stage rows
inside the main load, so the load's own cleanups keep them.

Behind ``MAPPING_OVERRIDE_LANE`` (default OFF). OFF: no BigQuery call, rows
returned untouched, no extra DML. ON covers crypto.com only; Polymarket (USA)
also needs ``MAPPING_OVERRIDE_LANE_POLYUSA`` because its consumer (``mapping_lever``)
still demands a name witness for the YES side and would refuse an override row
it cannot witness, and an override on one side drops the mapper's other side.

Per run, ON:
  * read the latest ``mapping_override`` message per venue key (+ side for
    Polymarket (USA)); keep ``active`` ones;
  * resolve each against a row already in the batch for the same Optic
    selection (``game_id`` + ``market_id`` + ``selection`` + line) — that row
    carries the canonical MERGE key columns. No batch row -> unresolved (logged,
    nothing written: an override for a fixture this run did not stage is picked
    up by the run that does);
  * drop batch rows of that venue with the same venue key or the same MERGE key,
    then add the override row (override wins);
  * before MERGE, delete table rows the override replaces (same venue key, any
    game — a wrong-fixture mapping must go too) and stale override rows on
    staged games whose override is no longer active.

Override rows are marked in the provenance columns: ``market_match_method`` /
``fixture_match_method`` / ``verify_tier`` = ``override`` and
``mapping_audit_event_id`` = the override's Pub/Sub message id (operator and
reason live on that ``mapping_override`` row's attributes).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

LANE_ENV = "MAPPING_OVERRIDE_LANE"
LANE_POLYUSA_ENV = "MAPPING_OVERRIDE_LANE_POLYUSA"
CRYPTO = "crypto.com"
POLY_USA = "Polymarket (USA)"
LANE_SPORTSBOOKS = (CRYPTO, POLY_USA)
OVERRIDE_METHOD = "override"
OVERRIDE_TABLE = "opticodds_us.mapping_override"

_KEY_COLUMNS = ("sport", "league", "start_date", "home", "away", "market_type", "entity", "line", "side", "group_key")
_OPTIC_COLUMNS = ("game_id", "fixture_id", "market_id", "selection", "selection_line", "points", "grouping_key")

# Latest message per venue key wins; Polymarket (USA) keys also carry the side
# (``selection_id`` yes|no) because one instrument symbol maps two selections.
ACTIVE_OVERRIDES_SQL = f"""
SELECT message_id, publish_time, sportsbook, game_id, market_id, selection,
       selection_line, points, grouping_key, TO_JSON_STRING(source_ids) AS source_ids_json
FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY sportsbook,
        COALESCE(JSON_VALUE(source_ids, '$.symbol'), JSON_VALUE(source_ids, '$.market_id')),
        IF(sportsbook = '{POLY_USA}', LOWER(COALESCE(JSON_VALUE(source_ids, '$.selection_id'), '')), '')
      ORDER BY publish_time DESC, message_id DESC
    ) AS rn
  FROM {OVERRIDE_TABLE}
  WHERE sportsbook IN ('{CRYPTO}', '{POLY_USA}')
)
WHERE rn = 1 AND active
"""  # nosec B608 — module constants only


def _env_on(name: str) -> bool:
    """True when env var ``name`` is set to 1/true/yes/on."""
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def lane_enabled() -> bool:
    """True when ``MAPPING_OVERRIDE_LANE`` is on."""
    return _env_on(LANE_ENV)


def lane_sportsbooks() -> tuple[str, ...]:
    """Venues the lane applies to right now: crypto.com, plus Polymarket (USA) behind its own flag."""
    if not lane_enabled():
        return ()
    return LANE_SPORTSBOOKS if _env_on(LANE_POLYUSA_ENV) else (CRYPTO,)


@dataclass(frozen=True)
class LaneOverride:
    """One active override for a lane venue."""

    sportsbook: str
    venue_key: str
    side: str
    game_id: str
    market_id: str
    selection: str
    selection_line: str
    points: float
    message_id: str
    publish_time: str


@dataclass
class LaneReport:
    """What the lane did this run; ``resolved`` / ``active`` drive the pre-MERGE delete."""

    active: dict[str, set[str]] = field(default_factory=dict)
    resolved: dict[str, set[str]] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    replaced: int = 0

    def summary(self) -> str:
        """One log line."""
        applied = sum(len(keys) for keys in self.resolved.values())
        return (
            f"  override lane: {applied} applied, {len(self.unresolved)} unresolved "
            f"(fixture not in this batch), {self.replaced} mapper rows replaced"
        )


def _source_ids(raw: str | None) -> dict[str, Any]:
    """``source_ids`` JSON (tolerates the double-encoded producer quirk)."""
    value: Any = raw
    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def venue_key(sportsbook: str, source_ids: dict[str, Any]) -> str:
    """What the venue's consumer looks a row up by: crypto symbol, else the US instrument symbol."""
    key = source_ids.get("symbol") if sportsbook == CRYPTO else source_ids.get("market_id")
    return str(key or "").strip()


def parse_override(raw: dict[str, Any]) -> LaneOverride | None:
    """Sink row -> LaneOverride; None when it carries no usable venue key."""
    book = str(raw.get("sportsbook") or "")
    src = _source_ids(raw.get("source_ids_json"))
    key = venue_key(book, src)
    if book not in lane_sportsbooks() or not key:
        return None
    published = raw.get("publish_time")
    return LaneOverride(
        sportsbook=book,
        venue_key=key,
        side=str(src.get("selection_id") or "").strip().lower(),
        game_id=str(raw.get("game_id") or ""),
        market_id=str(raw.get("market_id") or ""),
        selection=str(raw.get("selection") or ""),
        selection_line=str(raw.get("selection_line") or ""),
        points=float(raw.get("points") or 0.0),
        message_id=str(raw.get("message_id") or ""),
        publish_time=published.isoformat() if isinstance(published, datetime) else str(published or ""),
    )


def fetch_active_overrides(client: Any) -> list[LaneOverride]:
    """Active lane overrides from the sink (one query, ~85 MB unpartitioned table)."""
    rows = client.query(ACTIVE_OVERRIDES_SQL).result()
    parsed = (parse_override(dict(row.items())) for row in rows)
    return [ov for ov in parsed if ov is not None]


def _same_selection(row: dict[str, Any], ov: LaneOverride) -> bool:
    """Batch row is the Optic selection the override names (line-insensitive to None vs '')."""
    return (
        str(row.get("game_id") or "") == ov.game_id
        and str(row.get("market_id") or "") == ov.market_id
        and str(row.get("selection") or "").casefold() == ov.selection.casefold()
        and str(row.get("selection_line") or "") == ov.selection_line
        and float(row.get("points") or 0.0) == ov.points
    )


def _override_source_ids(ov: LaneOverride, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Venue-shaped ``source_ids``; crypto keeps the mapper's security_id for the symbol when known."""
    if ov.sportsbook == POLY_USA:
        return {"market_id": ov.venue_key, **({"selection_id": ov.side} if ov.side else {})}
    for row in rows:
        src = row.get("source_ids") or {}
        if row.get("sportsbook") == CRYPTO and src.get("symbol") == ov.venue_key:
            return {**src, "symbol": ov.venue_key}
    return {"symbol": ov.venue_key}


def build_override_row(ov: LaneOverride, rows: list[dict[str, Any]], column_names: set[str]) -> dict[str, Any] | None:
    """Stage row for ``ov`` from the batch row of the same Optic selection; None when not in batch."""
    base = next((row for row in rows if _same_selection(row, ov)), None)
    if base is None:
        return None
    provenance = {
        "market_match_method": OVERRIDE_METHOD,
        "fixture_match_method": OVERRIDE_METHOD,
        "verify_tier": OVERRIDE_METHOD,
        "mapping_audit_event_id": ov.message_id,
        "mapped_at": ov.publish_time or None,
    }
    row = {col: base.get(col) for col in (*_KEY_COLUMNS, *_OPTIC_COLUMNS, "last_updated")}
    row.update(sportsbook=ov.sportsbook, source_ids=_override_source_ids(ov, rows))
    row.update({col: value for col, value in provenance.items() if col in column_names})
    return row


def _row_venue_key(row: dict[str, Any]) -> str:
    """Venue key of a batch row ('' for non-lane books)."""
    book = str(row.get("sportsbook") or "")
    return venue_key(book, row.get("source_ids") or {}) if book in LANE_SPORTSBOOKS else ""


def _canonical_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """MERGE key without the source identity (Polymarket (USA) identity is NULL)."""
    return (*(row.get(col) for col in _KEY_COLUMNS), row.get("sportsbook"))


def _same_usa_side(row: dict[str, Any], new_row: dict[str, Any]) -> bool:
    """A US symbol is two selections: an override of one side keeps the other.

    Sideless on either row (an old override, a sideless passthrough) keeps
    the symbol-wide replace.
    """
    if new_row["sportsbook"] != POLY_USA:
        return True
    a = str((row.get("source_ids") or {}).get("selection_id") or "").lower()
    b = str((new_row.get("source_ids") or {}).get("selection_id") or "").lower()
    return not a or not b or a == b


def _replaces(row: dict[str, Any], new_row: dict[str, Any]) -> bool:
    """Batch row the override row supersedes: same venue key, or (Poly USA) same canonical key."""
    if row.get("sportsbook") != new_row["sportsbook"]:
        return False
    if _row_venue_key(row) == _row_venue_key(new_row) and _same_usa_side(row, new_row):
        return True
    return new_row["sportsbook"] == POLY_USA and _canonical_key(row) == _canonical_key(new_row)


def apply_override_lane(
    rows: list[dict[str, Any]],
    overrides: list[LaneOverride],
    column_names: set[str],
) -> tuple[list[dict[str, Any]], LaneReport]:
    """Batch rows with each resolvable override replacing the mapper's row(s) for its venue key."""
    report = LaneReport()
    built: list[dict[str, Any]] = []
    for ov in sorted(overrides, key=lambda o: o.publish_time):
        report.active.setdefault(ov.sportsbook, set()).add(ov.venue_key)
        new_row = build_override_row(ov, rows, column_names)
        if new_row is None:
            report.unresolved.append(f"{ov.sportsbook}|{ov.venue_key}|{ov.side}")
            continue
        # A later override for the same canonical selection wins over an earlier one.
        built = [r for r in built if _canonical_key(r) != _canonical_key(new_row) or r["sportsbook"] != POLY_USA]
        built.append(new_row)
        report.resolved.setdefault(ov.sportsbook, set()).add(ov.venue_key)
    kept = [row for row in rows if not any(_replaces(row, new_row) for new_row in built)]
    report.replaced = len(rows) - len(kept)
    return kept + built, report


def _quoted(values: set[str]) -> str:
    """SQL string literal list, quotes doubled; FALSE-safe via ``_in_or_false``."""
    return ", ".join("'" + v.replace("'", "''") + "'" for v in sorted(values))


def _in_or_false(expr: str, values: set[str]) -> str:
    """``expr IN (...)``, or FALSE for an empty set (``IN ()`` is invalid SQL)."""
    return f"{expr} IN ({_quoted(values)})" if values else "FALSE"


def _book_clause(book: str, report: LaneReport, alias: str, stage_table: str) -> str:
    """Rows of one lane venue to delete before MERGE."""
    field_name = "symbol" if book == CRYPTO else "market_id"
    key = f"JSON_VALUE({alias}.source_ids, '$.{field_name}')"
    replaced = _in_or_false(key, report.resolved.get(book, set()))
    still_active = _in_or_false(key, report.active.get(book, set()))
    stale = (
        f"({alias}.market_match_method = '{OVERRIDE_METHOD}' "  # nosec B608 — module constants + quote-doubled keys
        f"AND {alias}.game_id IN (SELECT DISTINCT game_id FROM {stage_table}) "
        f"AND NOT {still_active})"
    )
    return f"({alias}.sportsbook = '{book}' AND ({replaced} OR {stale}))"


def supersede_sql(report: LaneReport, *, table: str, stage_table: str, cutoff: str) -> str:
    """DELETE rows the override rows replace, plus stale override rows on staged games.

    Replaced keys are deleted on ANY game (a wrong-fixture row must go); the
    MERGE then inserts the override row from stage. The ``start_date`` bound
    satisfies the table's required partition filter.
    """
    books = " OR ".join(_book_clause(book, report, "t", stage_table) for book in LANE_SPORTSBOOKS)
    return f"""
        DELETE FROM {table} t
        WHERE t.start_date >= TIMESTAMP('{cutoff}')
            AND ({books})
    """  # nosec B608 — keys are quote-doubled literals from our own override sink


def stage_override_lane(
    client: Any,
    rows: list[dict[str, Any]],
    column_names: set[str],
) -> tuple[list[dict[str, Any]], LaneReport | None]:
    """Load-time entry point: rows unchanged and no query when the lane is OFF."""
    if not lane_enabled():
        return rows, None
    rows, report = apply_override_lane(rows, fetch_active_overrides(client), column_names)
    print(report.summary())
    for key in report.unresolved[:20]:
        print(f"    unresolved override {key}")
    return rows, report


def supersede_override_rows(
    client: Any, report: LaneReport | None, *, table: str, stage_table: str, cutoff: str, run_dml: Any
) -> None:
    """Pre-MERGE delete; no-op when the lane is OFF (``report`` is None)."""
    if report is None:
        return
    print("Superseding rows replaced by overrides...")
    run_dml(client, supersede_sql(report, table=table, stage_table=stage_table, cutoff=cutoff))
