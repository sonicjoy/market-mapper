"""SX Bet: judged from SX's own outcome names, market type and line.

Off unless ``AI_VALIDATION_SXBET=1`` (``enabled``).  SX rows are Optic's
passthrough plus the rows ``mappers/exchanges/sxbet_pass.py`` constructs off
SX's catalogue, and corroboration (``prices_dedup_state``) holds no SX rows
today (measured 2026-10-13), so turning this on sends every SX row in the
window to the model once.  That is an owner call; the deterministic side-check
runs regardless.

The text comes from ``raw_ingestion_us.sxbet_fetch_raw`` (``BigQuery/
load_exchange_fetch.py``): the newest ``/markets/active`` row per marketHash.
"""

from __future__ import annotations

import os

from BigQuery.ai_validation_exchanges.base import ExchangeSpec

#: The loader appends a snapshot every 15 minutes; a day covers a missed tick
#: and keeps the scan to one DAY partition (the snapshot_id prune below takes
#: it to the newest hours).
RAW_LOOKBACK_DAYS = 1

#: SX market type ids we map (mappers/vocab/sxbet_markets.py), as the judge
#: reads them.  The period is part of the id; "period" is a quarter in American
#: football / basketball and a set in tennis.
TYPE_LABELS: dict[str, str] = {
    "1": "1X2 as a binary: outcome one is the result, outcome two its complement",
    "2": "Under/Over", "28": "Under/Over incl. overtime", "3": "Asian handicap",
    "342": "Asian handicap incl. overtime", "52": "two-way winner", "226": "two-way winner incl. overtime",
    "53": "Asian handicap, 1st half", "77": "Under/Over, 1st half",
    "64": "Asian handicap, 1st period", "21": "Under/Over, 1st period",
    "65": "Asian handicap, 2nd period", "45": "Under/Over, 2nd period",
    "66": "Asian handicap, 3rd period", "46": "Under/Over, 3rd period",
    "166": "Under/Over games", "201": "Asian handicap games", "165": "set total", "866": "set spread",
    "202": "1st period (set) winner", "203": "2nd period (set) winner",
    "236": "Under/Over, first 5 innings", "281": "Asian handicap, first 5 innings",
}

_CTE_SQL = """\
sx AS (
  -- SX's /markets/active rows verbatim (BigQuery/load_exchange_fetch.py). The
  -- snapshot_id prune is on the leading cluster column ('YYYY-MM-DDTHH:MM'), so the
  -- scan is the newest few snapshots, not the whole day.
  SELECT market_hash                            AS sx_market_hash,
         JSON_VALUE(data, '$.outcomeOneName')   AS sx_outcome_one,
         JSON_VALUE(data, '$.outcomeTwoName')   AS sx_outcome_two,
         JSON_VALUE(data, '$.type')             AS sx_type,
         JSON_VALUE(data, '$.line')             AS sx_line,
         JSON_VALUE(data, '$.teamOneName')      AS sx_team_one,
         JSON_VALUE(data, '$.teamTwoName')      AS sx_team_two,
         JSON_VALUE(data, '$.leagueLabel')      AS sx_league
  FROM `{project}.raw_ingestion_us.sxbet_fetch_raw`
  WHERE fetch_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
    AND snapshot_id >= FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M', TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR))
  QUALIFY ROW_NUMBER() OVER (PARTITION BY market_hash ORDER BY fetch_time DESC) = 1
)"""

_JOIN_SQL = """\
LEFT JOIN sx s
  ON m.sportsbook = 'SX Bet'
 AND s.sx_market_hash = LOWER(m.src_market_id)"""

_SELECT_SQL = """\
s.sx_outcome_one, s.sx_outcome_two, s.sx_type, s.sx_line,
s.sx_team_one, s.sx_team_two, s.sx_league"""

_PROMPT = """\
SX BET encoding (sel=the outcome this row maps, other=the market's other outcome, type=SX market type, line, teams):
- An SX market is ONE binary with two outcomes. `sel` is the outcome OURS claims, already
  resolved from the id -- judge OURS against `sel` and nothing else. `other` is shown only so
  you can see the pair: OURS must NOT match `other`.
- `type` names the market AND its period (e.g. "Asian handicap, 1st half"). A period suffix
  inside `sel` ("(1st half)", "(sets)", "(1st Period)") repeats it; "1st Period" is the first
  quarter in American football and basketball and the first set in tennis.
- Spreads: `sel` is "<team> <signed handicap>" ("SC Paderborn 07 +0.75"); that number IS the
  line, with its sign -- compare it to OURS pts. A level handicap is written unsigned ("Team 0").
- Totals: `sel` is "Over N" / "Under N" -- the side and the line.
- `type` 1 is one result of a 1X2: `sel` is the team (or "Tie") and OURS is that 3-way result.
  A `sel` starting "Not " is never a valid mapping -- flag it.
- Team names are SX's display names and often differ from OURS spelling ("Barcelona FC" /
  "FC Barcelona", "Tennessee Volunteers" / "Tennessee"): judge identity, not spelling.
"""


def enabled() -> bool:
    """True when the SX spec is switched on (``AI_VALIDATION_SXBET=1``)."""
    return os.environ.get("AI_VALIDATION_SXBET") == "1"


def taker_outcome(row: dict) -> tuple[str | None, str | None]:
    """(the outcome this row maps, the other outcome) from the selection id's MAKER suffix.

    ``<hash>|two`` is the taker's outcome ONE, ``<hash>|one`` outcome two
    (``mappers/exchanges/sxbet.selection_id``).
    """
    suffix = str(row.get("src_selection_id") or "").lower().rpartition("|")[2]
    one, two = row.get("sx_outcome_one"), row.get("sx_outcome_two")
    if suffix == "two":
        return one, two
    if suffix == "one":
        return two, one
    return None, None


def _has_text(row: dict) -> bool:
    return taker_outcome(row)[0] is not None


def _ref(row: dict) -> str | None:
    return row.get("src_selection_id")


def _side(row: dict) -> str | None:
    return None


def _text(row: dict) -> str | None:
    sel, other = taker_outcome(row)
    return f"{sel} / other: {other}" if sel else None


def _line(row: dict) -> str:
    sel, other = taker_outcome(row)
    sx_type = str(row.get("sx_type") or "")
    out = f"SXBET sel='{sel or ''}' other='{other or ''}' type='{TYPE_LABELS.get(sx_type, sx_type)}'"
    if row.get("sx_line") is not None:
        out += f" line={row['sx_line']}"
    if row.get("sx_team_one") or row.get("sx_team_two"):
        out += f" teams='{row.get('sx_team_one') or ''} v {row.get('sx_team_two') or ''}'"
    return out


SPEC = ExchangeSpec(
    name="SX Bet",
    # Optic publishes its own SX ids; when prices_dedup_state carries them the
    # passthrough rows corroborate and only constructed rows reach the model.
    corroborated=True,
    lookback_days=RAW_LOOKBACK_DAYS,
    cte_sql=_CTE_SQL,
    join_sql=_JOIN_SQL,
    select_sql=_SELECT_SQL,
    prompt=_PROMPT,
    has_text=_has_text,
    ref=_ref,
    side=_side,
    text=_text,
    line=_line,
)
