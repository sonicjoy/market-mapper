"""Novig: judged from the raw market JSON's description, typed fields and outcome description."""

from __future__ import annotations

from BigQuery.ai_validation_exchanges.base import ExchangeSpec

#: Novig re-stashes every 6h too (infra/cron_novig_raw.sh); same slack as Kalshi.
RAW_LOOKBACK_DAYS = 3

_CTE_SQL = """\
nv AS (
  -- Novig's `data` column is the market JSON verbatim (BigQuery/load_novig_raw.py);
  -- `kind='markets'` rows carry the market + outcome description text. No ticker/
  -- symbol grammar to decode, so unlike kal/poly/cc this needs no date masking.
  -- Player-prop outcomes describe only the threshold ("Under 2.5"), never the
  -- player -- that lives on the market's own `player` object, so it is pulled
  -- separately (mappers/exchanges/novig.py NovigPlayer: fullName then name).
  SELECT JSON_VALUE(data, '$.id')          AS novig_market_id,
         JSON_VALUE(data, '$.description') AS novig_market_desc,
         JSON_VALUE(data, '$.type')        AS novig_market_type,
         JSON_VALUE(data, '$.strike')      AS novig_strike,
         IFNULL(
           JSON_VALUE(data, '$.player.fullName'),
           JSON_VALUE(data, '$.player.name')
         ) AS novig_player_name,
         JSON_EXTRACT_ARRAY(data, '$.outcomes') AS outcomes
  FROM `{project}.raw_ingestion_us.novig_raw`
  WHERE kind = 'markets'
    AND insert_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY JSON_VALUE(data, '$.id') ORDER BY insert_time DESC
  ) = 1
), nv_out AS (
  SELECT novig_market_id, novig_market_desc, novig_player_name,
         novig_market_type, novig_strike,
         JSON_VALUE(outcome, '$.id')          AS novig_outcome_id,
         JSON_VALUE(outcome, '$.description') AS novig_outcome_desc,
         JSON_VALUE(outcome, '$.type')        AS novig_outcome_type
  FROM nv, UNNEST(outcomes) AS outcome
)"""

_JOIN_SQL = """\
LEFT JOIN nv_out n
  ON m.sportsbook = 'Novig'
 AND n.novig_market_id = m.src_market_id
 AND n.novig_outcome_id = m.src_selection_id"""

_SELECT_SQL = """\
n.novig_market_desc, n.novig_outcome_desc, n.novig_player_name,
n.novig_market_type, n.novig_strike, n.novig_outcome_type"""

#: Novig hands us OpticOdds ids directly (mappers/exchanges/novig.py) — fixture,
#: team and player identity are an ID JOIN, not name matching, so this block is
#: short: no ticker/slug/symbol grammar, no sign convention to decode, no date.
_PROMPT = """\
NOVIG encoding (sel=outcome description, mkt=market description, type/strike/outcome=typed, who=player):
- `type`, `strike` and `outcome` are Novig's own TYPED fields and outrank any text.
  `type` is the market family (MONEY, SPREAD, TOTAL, TEAM_TOTAL, SET_SPREAD,
  TOTAL_SETS, MONEYLINE_3_WAY_WIN, MONEYLINE_3_WAY_DRAW, SPREAD_1H, TOTAL_1H, ...);
  `strike` is the signed line; `outcome` is Home/Away/Over/Under (on the draw leg a
  Yes/No pair: Yes = the draw happens). Judge market_ok from `type`, never from the
  unit you would guess a number is in (a +-1.5 SET_SPREAD is a set handicap, not a
  game spread), and take the line from `strike`.
- Digits inside `mkt` are a venue label, not a line: "V. Morvayova @ I. Burillo
  Escorihuela t2.5" is a 2.5 total (the `t` is part of the label), never 22.5.
- `sel` is the traded outcome in Novig's own words and is the primary evidence for
  side and line: a team name with a signed number ("DAL -7.5", "PHI +7.5"), an
  over/under phrase ("Over 44.5"), or a threshold-only prop phrase ("Under 2.5").
  A number inside `sel` IS the line -- compare it to OURS pts/line. No number in
  `sel` and no threshold in OURS = line_ok.
- `mkt` is Novig's own one-line market description -- evidence for market_ok and
  scope, not for side or line.
- `who`, when present, is the player the whole market is about, from Novig's own
  player object -- NOT part of `sel`, which on a player prop states only the
  threshold ("Under 2.5") and never names the player. `who` is the evidence for
  entity_ok; a player prop with no `who` shown means Novig's own feed carried no
  player name, not that OURS entity is unconfirmed.
- Novig's fixture/team/player identity is resolved by an ID JOIN upstream
  (opticOddsId), not by name matching, so treat fixture_ok/entity_ok exactly like
  any other exchange but expect the spelling to already agree closely -- a
  genuine mismatch here is a real finding, not a transliteration quirk.
- No ticker/slug/symbol grammar and no ladder-style N-0.5 offset: Novig's numeric
  strike is copied straight into OURS `line`/`pts` with the same sign, so a real
  sign disagreement is a real finding, not an encoding convention to reason
  through first.
"""


def _has_text(row: dict) -> bool:
    return bool(row.get("novig_outcome_desc") or row.get("novig_market_desc"))


def _ref(row: dict) -> str | None:
    # Novig's source_ids.selection_id is the outcome id, same shape as
    # Polymarket's clob_token_id -- the side is baked into the id, not a
    # separate field (unlike Kalshi's ticker+yes/no).
    return row.get("src_selection_id")


def _side(row: dict) -> str | None:
    return None


def _text(row: dict) -> str | None:
    typed = f"{row['novig_market_type']} {row['novig_strike']}" if row.get("novig_market_type") else None
    parts = (row.get("novig_outcome_desc"), row.get("novig_market_desc"), typed)
    return " / ".join(p for p in parts if p) or None


def _line(row: dict) -> str:
    out = f"NOVIG sel='{row.get('novig_outcome_desc') or ''}'"
    if row.get("novig_market_desc"):
        out += f" mkt='{row['novig_market_desc']}'"
    if row.get("novig_market_type"):
        out += f" type={row['novig_market_type']}"
        if row.get("novig_strike") is not None:
            out += f" strike={row['novig_strike']}"
        if row.get("novig_outcome_type"):
            out += f" outcome={row['novig_outcome_type']}"
    if row.get("novig_player_name"):
        out += f" who='{row['novig_player_name']}'"
    return out


SPEC = ExchangeSpec(
    name="Novig",
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
