"""crypto.com: judged from the FIX security catalogue's selection / event / participant meta."""

from __future__ import annotations

from BigQuery.ai_validation_exchanges.base import ExchangeSpec, mask_exchange_dates

#: crypto.com catalogue lookback. The catalogue republishes every live symbol
#: daily: on 2026-11-03 all 51,064 mapped crypto.com symbols had a row in the
#: last day. 14 days of crypto_underlying_securities alone billed 46 GB and
#: pushed the run past its 50 GiB cap (every run failed from 2026-10-29).
CATALOGUE_LOOKBACK_DAYS = 3

_CTE_SQL = """\
cc AS (
  -- The two catalogue tables carry the same facts under different names, and
  -- neither is a superset: security_def adds the home/away participants (and
  -- calls the selection text `meta_alpha_strike`), underlying_securities calls
  -- that same text `meta_event_name` and has no participant split. Prefer
  -- security_def per symbol, fall back to underlying_securities.
  SELECT symbol, cc_selection, cc_event, cc_participant, cc_home, cc_away,
         cc_period, cc_contract, cc_family
  FROM (
    SELECT symbol,
           meta_alpha_strike            AS cc_selection,
           meta_name                    AS cc_event,
           meta_participant             AS cc_participant,
           meta_home_participant        AS cc_home,
           meta_away_participant        AS cc_away,
           meta_predict_period_type     AS cc_period,
           meta_predict_contract_type   AS cc_contract,
           meta_predict_market_type     AS cc_family,
           publish_time,
           1 AS src_rank
    FROM `{project}.processed_upstream_us.crypto_security_def`
    WHERE publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
    UNION ALL
    SELECT symbol,
           meta_event_name, meta_name, meta_participant,
           CAST(NULL AS STRING), CAST(NULL AS STRING),
           meta_predict_period_type, meta_predict_contract_type,
           meta_predict_market_type, publish_time,
           2 AS src_rank
    FROM `{project}.processed_upstream_us.crypto_underlying_securities`
    WHERE publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
  )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY symbol ORDER BY src_rank, publish_time DESC
  ) = 1
)"""

_JOIN_SQL = "LEFT JOIN cc c ON m.sportsbook = 'crypto.com' AND c.symbol = m.src_symbol"

_SELECT_SQL = """\
c.cc_selection, c.cc_event, c.cc_participant, c.cc_home, c.cc_away,
c.cc_period, c.cc_contract, c.cc_family"""

_PROMPT = """\
CRYPTO.COM encoding (sym=FIX Symbol, sel=selection text, event=event name,
who=participant, home/away=participants, period=scope, contract=market,
family=market family):
- `sel` is the selection in crypto.com's own words and is the primary evidence
  for side, entity AND line: "Charles Conwell to win", "Ryan Kreidler Over 3.5
  Total Hits Milestone", "None To Score A Run". A number inside `sel` IS the
  line -- compare it to OURS pts/line. No number and no threshold in OURS =
  line_ok.
- SPREAD SIGNS: crypto.com writes the sign itself and lists BOTH sides --
  "Olympique Lyonnais -8.5 to win" (favourite, OURS line=-8.5) and, on the same
  game, "SK Slovan Bratislava 8.5 to win" (underdog receiving, OURS line=+8.5).
  OURS copies crypto's own signed value verbatim, so the two agree by
  construction. A MISSING minus means the PLUS side -- "Levski Sofia 5.5 to win"
  is +5.5, NOT "wins by 5.5". Only flag when the signs actually differ; do not
  read "N to win" as "wins by N".
- `event` is the fixture: "Away @ Home" for team sports, "A vs B" for
  fight/tennis cards, or a tournament/future title. `home`/`away` name the two
  participants explicitly when present -- prefer them for fixture_ok, and note
  that crypto.com's home/away can be listed either way round in `event`.
- `who` is the entity the contract is about (player, team, coach) -- the
  evidence for entity_ok on props.
- `contract` is the market ("Moneyline", "Spread", "To Score A Run", "Total Hits
  Milestones") and `period` the scope ("Full-Game", "1st Inning", "Full Fight",
  "Regular Season"). A scope or market that disagrees with OURS market_type is a
  market_ok failure. Milestone contracts are over N-0.5 style: "Over 3.5
  Milestone" == over 3.5.
- `family` is the grouping ("Game Line", "Player Prop", "Game Prop", "Fight
  Line", "Player Future"). A future/tournament family mapped onto a single
  fixture is a fixture_ok failure.
- The symbol (NX.F.OPT.<LEAGUE>-<index>-<yymmdd>-<code>) carries NO participant
  names: the yymmdd is the event date (matching either OURS `date` or `et` is
  fine), but the numeric index is a catalogue slot, NOT a team id. Never infer
  participants from the symbol -- if `sel`/`event` are absent, say so in
  `reason` rather than guessing."""


def _has_text(row: dict) -> bool:
    return bool(row.get("cc_selection") or row.get("cc_event"))


def _ref(row: dict) -> str | None:
    return row.get("src_symbol")


def _side(row: dict) -> str | None:
    return None


def _text(row: dict) -> str | None:
    return " / ".join(p for p in (row.get("cc_selection"), row.get("cc_event")) if p) or None


def _line(row: dict) -> str:
    out = f"CRYPTO sym={mask_exchange_dates(row.get('src_symbol')) or ''} sel='{row.get('cc_selection') or ''}'"
    if row.get("cc_event"):
        out += f" event='{row['cc_event']}'"
    if row.get("cc_home") or row.get("cc_away"):
        out += f" home='{row.get('cc_home') or ''}' away='{row.get('cc_away') or ''}'"
    if row.get("cc_participant"):
        out += f" who='{row['cc_participant']}'"
    return out + _scope_suffix(row)


def _scope_suffix(row: dict) -> str:
    out = ""
    if row.get("cc_period"):
        out += f" period='{row['cc_period']}'"
    if row.get("cc_contract"):
        out += f" contract='{row['cc_contract']}'"
    if row.get("cc_family"):
        out += f" family='{row['cc_family']}'"
    return out


SPEC = ExchangeSpec(
    name="crypto.com",
    corroborated=False,
    lookback_days=CATALOGUE_LOOKBACK_DAYS,
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
