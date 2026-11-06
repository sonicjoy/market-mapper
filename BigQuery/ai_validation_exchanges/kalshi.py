"""Kalshi: judged from Kalshi's own market title / yes_sub_title plus the bound yes|no side."""

from __future__ import annotations

from BigQuery.ai_validation_exchanges.base import ExchangeSpec, mask_exchange_dates

#: Kalshi re-stashes every Sports market every 6h (infra/cron_kalshi_raw.sh);
#: 3 days of snapshots survives a couple of missed runs without widening the scan.
RAW_LOOKBACK_DAYS = 3

_CTE_SQL = """\
kal AS (
  SELECT JSON_VALUE(data, '$.ticker')        AS ticker,
         JSON_VALUE(data, '$.title')         AS kalshi_title,
         JSON_VALUE(data, '$.yes_sub_title') AS kalshi_sub
  FROM `{project}.raw_ingestion_us.kalshi_raw`
  WHERE insert_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY JSON_VALUE(data, '$.ticker') ORDER BY insert_time DESC
  ) = 1
)"""

_JOIN_SQL = "LEFT JOIN kal k ON m.sportsbook = 'Kalshi' AND k.ticker = m.src_market_id"

_SELECT_SQL = "k.kalshi_title, k.kalshi_sub"


#: Kalshi rows are judged from Kalshi's OWN text (title / yes_sub_title) and the
#: side we bound (s=yes|no). The ticker is shown only as an opaque id: mapping no
#: longer decodes ticker grammar, so neither may the judge.
_PROMPT = """\
KALSHI encoding (t=ticker, s=yes|no, title/sub = Kalshi's own text):
- THE TICKER IS AN OPAQUE ID. Never decode it: do not read teams, players, codes,
  lines, thresholds, dates, market families or scopes out of `t`, and never give
  a reason based on what the ticker string seems to say. All evidence comes from
  `title`, `sub` and `s`. If title and sub are both absent, say so in `reason`
  rather than guessing from the ticker.
- THE TITLE (and `sub`, Kalshi's yes_sub_title) ALWAYS DESCRIBES THE CONTRACT'S
  YES SIDE. s=yes = OURS selection is that stated outcome; s=no = OURS selection
  is its COMPLEMENT. Work it in written steps before judging any row -- skipping
  them is THE most common error on Kalshi:
    (1) read the proposition from title/sub: who, what threshold, which scope.
        'Sabah wins by more than 2.5 goals?' == Sabah -2.5.
    (2) if s=no, take the complement: not(Sabah -2.5) == THE OPPONENT +2.5. The
        handicap moves to the OTHER team. It does NOT stay with Sabah. On a
        totals/prop proposition ('over 8.5 runs', '3+ hits') s=no is the under
        of the same line.
    (3) compare THAT to OURS side, line and market.
  e.g. OURS side=AGF line=2.5 || s=no title='Sabah wins by more than 2.5 goals?'
  -> step 2 gives Aarhus +2.5 == OURS. side_ok=true, line_ok=true. Concluding
  "OURS is Aarhus +2.5 but Kalshi is Sabah +2.5" means step 2 was skipped: s=no
  can never leave the + with the title's team. An underdog on s=no is the normal
  shape, not a flipped side.
- Kalshi lists a SEPARATE spread ladder for EACH team, so the same game
  legitimately yields both 'Arizona wins by more than 1.5' s=no (Carolina +1.5)
  and 'Carolina wins by more than 1.5' s=no (Arizona +1.5). Two such rows do not
  contradict each other -- judge each on its own title.
- THRESHOLD RULE: Kalshi states thresholds as "N or more" / "N+" or as "more
  than X.5". "N or more" == over N-0.5 (yes) / under N-0.5 (no); "more than X.5"
  == over X.5. So '3+ hits' matches OURS over 2.5, and 'wins by 2 or more' matches
  -1.5. A half-point gap explained by this rule is a match, never "far-off";
  only a whole-step deviation is a real mismatch.
- Binary propositions (to win / to advance / both teams to score / first goal /
  score-or-assist) carry no threshold: s=yes = the stated outcome, s=no = the
  complement. "To advance" includes extra time and penalties; "wins" on a soccer
  game is the 90-minute result unless the title says otherwise.
- The title's scope words ('1st half', 'first 5 innings', 'regulation', 'in the
  match') are the market's scope -- compare them to OURS market_type."""


def _has_text(row: dict) -> bool:
    return bool(row.get("kalshi_title") or row.get("kalshi_sub"))


def _ref(row: dict) -> str | None:
    return row.get("src_market_id")


def _side(row: dict) -> str | None:
    return row.get("src_selection_id")


def _text(row: dict) -> str | None:
    return " / ".join(p for p in (row.get("kalshi_title"), row.get("kalshi_sub")) if p) or None


def _line(row: dict) -> str:
    out = f"KALSHI t={mask_exchange_dates(row.get('src_market_id')) or ''} s={row.get('src_selection_id') or ''}"
    if row.get("kalshi_title"):
        out += f" title='{row['kalshi_title']}'"
    if row.get("kalshi_sub"):
        out += f" sub='{row['kalshi_sub']}'"
    return out


SPEC = ExchangeSpec(
    name="Kalshi",
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
