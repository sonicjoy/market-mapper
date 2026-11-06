"""Polymarket: judged from the position<->token bridge's question, outcome label and slug."""

from __future__ import annotations

from BigQuery.ai_validation_exchanges.base import ExchangeSpec, strip_slug_date

#: The position<->token bridge only rewrites condition_ids it has not bridged
#: yet, so a row can be months old. The window exists only to satisfy a possible
#: require-partition-filter, not to filter anything real.
BRIDGE_LOOKBACK_DAYS = 180

_CTE_SQL = """\
poly AS (
  SELECT clob_token_id, question AS poly_question,
         outcome_label AS poly_outcome, slug AS poly_slug
  FROM `{project}.raw_ingestion_us.polymarket_position_token_bridge`
  WHERE clob_token_id IS NOT NULL
    AND last_updated >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY clob_token_id ORDER BY last_updated DESC
  ) = 1
)"""

_JOIN_SQL = "LEFT JOIN poly p ON m.sportsbook = 'Polymarket' AND p.clob_token_id = m.src_selection_id"

_SELECT_SQL = "p.poly_question, p.poly_outcome, p.poly_slug"

_PROMPT = """\
POLYMARKET encoding (q=market question, outcome=this token's outcome label,
slug=market slug):
- The side is bound to the OUTCOME LABEL (or the entity the question names) --
  never to an outcome's position in a list. A team/player name as the label must
  be the same team/player as OURS `side`.
- Yes/No labels: the question states the proposition; Yes = it happens. On a
  totals question ("...more than 8.5 runs?") Yes = over, No = under, and the
  line comes from the question text -- compare it to OURS pts.
- NO DATE IS SHOWN FOR POLYMARKET AND NONE CAN BE JUDGED. The slug's trailing
  date is stripped before you see it, because Polymarket dates the slug by local
  tournament day -- it disagrees with both OURS `date` and `et` for perfectly
  correct mappings. Judge the fixture from the PARTICIPANTS in `q` alone. Never
  return a date-based reason on a POLY row.
- Questions naming both participants without a proposition ("Bonn: A vs B") are
  moneylines; the outcome label picks the winner.
- 'Exact Score: <A> N1 - N2 <B>?' is in FIXTURE order while OURS is
  winner-anchored -- see the CORRECT SCORE rule above and reorder before judging.
  Our matcher resolves A/B to home/away by NAME, never by question order, so the
  question's order carries no side information by itself."""


def _has_text(row: dict) -> bool:
    return bool(row.get("poly_question") or row.get("poly_outcome"))


def _ref(row: dict) -> str | None:
    return row.get("src_selection_id")


def _side(row: dict) -> str | None:
    return row.get("poly_outcome")


def _text(row: dict) -> str | None:
    return row.get("poly_question")


def _line(row: dict) -> str:
    out = f"POLY q='{row.get('poly_question') or ''}' outcome='{row.get('poly_outcome') or ''}'"
    slug = strip_slug_date(row.get("poly_slug"))
    if slug:
        out += f" slug={slug}"
    return out


SPEC = ExchangeSpec(
    name="Polymarket",
    corroborated=True,
    lookback_days=BRIDGE_LOOKBACK_DAYS,
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
