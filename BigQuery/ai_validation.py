"""AI validation of our exchange mappings (yes/no verdicts per mapping row).

Reads `markets_us.market_mapping` for a fixture window, joins each row to the
**exchange-native text** for the id we mapped it to (Kalshi market title,
Polymarket question + outcome label, crypto.com FIX catalogue meta, Novig market
+ outcome description), asks Gemini whether that listing really carries the same
contract, and MERGEs the verdicts into `markets_us.market_mapping_ai_validation`.

This is the semantic complement to the deterministic checks: `verify_source_ids`
(mappers/exchanges/optic.py) catches disagreement with Optic, and the gap checks
catch missing coverage — neither catches a structurally valid mapping that is
simply wrong (right fixture, wrong side / line / period / player).

Ported from mm-huddle's `mapping/ai_validation.py`; the Kalshi ticker-grammar
rules in the prompt are that repo's, kept verbatim because they already encode
the recurring false-positive classes.

Token frugality, biggest lever first:
- a mapping is judged ONCE EVER: `row_fingerprint` (the MERGE key + source_ids,
  hashed) is anti-joined against the verdict table INSIDE the input SQL, so
  already-judged rows never leave BigQuery. `--revalidate` overrides; bumping
  `PROMPT_VERSION` re-judges everything.
- rows Optic independently corroborates are skipped (Optic maps the same
  selection to the same exchange id we did -> already double-sourced, the model
  adds nothing). This is also how Polymarket/Novig *passthrough* rows (source_ids
  copied straight from Optic, never touched by our own matcher) get skipped —
  judging Optic against its own claim proves nothing. `--include-corroborated`
  overrides.
- four sportsbooks only (Kalshi / Polymarket / crypto.com / Novig — the ones we
  match ourselves); many rows per call; batches partitioned by sportsbook so each
  call carries only that exchange's rule block.
- gemini-3.6-flash with dynamic thinking (mm-huddle proved thinking_budget=0
  breaks the threshold arithmetic and the polarity rules). Override with
  GEMINI_MODEL; the model id is recorded per verdict row, so a switch is
  visible when comparing flag rates across runs.

Usage:
    .venv/bin/python -m BigQuery.ai_validation --dry-run       # SQL + prompt, no spend
    .venv/bin/python -m BigQuery.ai_validation --max-rows 50   # cap spend
    .venv/bin/python -m BigQuery.ai_validation --sportsbook Kalshi
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from google.cloud import bigquery
from pydantic import BaseModel

from BigQuery import ai_validation_exchanges as exchanges
from BigQuery.ai_validation_exchanges.base import ExchangeSpec
from BigQuery.ai_validation_exchanges.base import mask_exchange_dates as mask_exchange_dates
from BigQuery.ai_validation_exchanges.base import strip_slug_date as strip_slug_date
from BigQuery.alerts import build_publisher
from BigQuery.load_mappings import KEY_COLUMNS
from BigQuery.polymarket_bq_util import bq_client, ensure_table, qualify, stage_and_merge

logger = logging.getLogger(__name__)

TABLE = "markets_us.market_mapping_ai_validation"
STAGE = "markets_us.market_mapping_ai_validation_stage"
KEY_COL = "row_fingerprint"
PARTITION_FIELD = "start_date"
CLUSTERING = ["sportsbook", "league", "mapping_ok"]

#: Bump on ANY change to the prompt or the verdict semantics. The anti-join is
#: keyed on (row_fingerprint, prompt_version), so a bump re-judges everything —
#: verdicts from different rule sets are not comparable.
#: v1: initial release. Ported from mm-huddle, then hardened against six
#:     false-positive classes found on real data before shipping (dates removed
#:     entirely, winner-anchored correct score, Kalshi s=no substitution,
#:     Polymarket 3-way legs, crypto.com spread signs, derived mapping_ok).
#:     Those iterations are documented in docs/ai-validation.md; they all
#:     predate release, so the shipped ruleset is v1.
#: v2: `grp` is not a line. _ours_line renders grouping_key, whose number on
#:     spread/handicap rows is the MIRROR of the real line (line=+4.5 carries
#:     grp='default:-4.5'), and v1 documented the field only as a player-name
#:     carrier. The first prod run flagged 3 correct crypto.com run_line rows
#:     with reason "OURS is -4.5" — the only -4.5 in the row was the grouping
#:     key. 1,660 rows in one prod window carry an inverted grp, concentrated in
#:     point_spread/set_handicap across every book, so this was a standing
#:     false-positive source rather than one bad fixture.
PROMPT_VERSION = 2

#: The exchanges whose ids OUR matcher produces. Prophet X / Runshop are out of
#: scope (Optic passthrough or a different consumer). SX Bet has a spec that is
#: off unless AI_VALIDATION_SXBET=1 (ai_validation_exchanges/sx_bet.py). Novig is a
#: partial passthrough (Optic hands us its own ids directly, per
#: mappers/exchanges/novig.py) but our matcher still id-joins and constructs
#: rows Optic never mapped itself, so it belongs here like Polymarket.
SPORTSBOOKS = exchanges.sportsbooks()

#: Sportsbooks where Optic publishes its own id for the same selection, so a
#: match can be corroborated without the model. crypto.com is absent on purpose:
#: our symbol is decoded from Optic's market_id via the catalogue, so Optic is
#: not an independent witness for it. Novig included: like Polymarket, most rows
#: are Optic's own source_ids passed straight through (mappers/exchanges/optic.py
#: OPTIC_MAPPED_SPORTSBOOKS), and judging Optic's claim against Optic's own
#: listing text is a tautology, not a check — only the constructed (id-joined)
#: Novig rows Optic never mapped are worth a model call.
CORROBORATED_SPORTSBOOKS = exchanges.corroborated_sportsbooks()

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
#: Same Secret Manager entry mm-huddle / mm-mapping-bot use (test and prod).
GEMINI_SECRET = "mm-mapping-bot-gemini-key"  # nosec B105 — a Secret Manager entry name, not a credential
BATCH_ROWS = int(os.getenv("AI_BATCH_ROWS", "25"))
CONCURRENCY = int(os.getenv("AI_CONCURRENCY", "8"))
#: -1 = dynamic (the model decides per batch); 0 disables thinking, which
#: demonstrably breaks the Kalshi threshold arithmetic and the polarity rules.
THINKING_BUDGET = int(os.getenv("AI_THINKING_BUDGET", "-1"))
#: Verdicts buffered before a MERGE. Flushing in chunks bounds the loss when a
#: long run dies, without the per-batch staging-table collisions parallel MERGEs
#: would cause (one fixed stage table, flushed from the main thread).
FLUSH_EVERY = int(os.getenv("AI_FLUSH_EVERY", "500"))
#: Days of slack when looking up fixture display names. Optic's start_date for a
#: fixture can sit outside the mapping window (reschedules, boundary kickoffs);
#: without the pad those rows lose their readable matchup entirely.
FIXTURE_PAD_DAYS = 3


def _fingerprint_expr(alias: str = "") -> str:
    """SQL expression hashing a mapping row's identity: MERGE key + source_ids.

    Derived from `load_mappings.KEY_COLUMNS` so it cannot drift from the table's
    own uniqueness key. `source_ids` is part of the hash on purpose: a canonical
    bet re-mapped to a DIFFERENT ticker/token/symbol must be re-judged, while the
    same row republished every 15 minutes must not.
    """
    p = f"{alias}." if alias else ""
    parts: list[str] = []
    for col in KEY_COLUMNS:
        if col == "start_date":
            # Millis, not the formatted timestamp: no locale/precision drift.
            parts.append(f"CAST(UNIX_MILLIS({p}start_date) AS STRING)")
        elif col == "line":
            parts.append(f"IFNULL(FORMAT('%.4f', {p}line), '')")
        else:
            parts.append(f"IFNULL({p}{col}, '')")
    # BigQuery's JSON type normalises key order on ingestion, so the string form
    # is stable across loads of the same object.
    parts.append(f"IFNULL(TO_JSON_STRING({p}source_ids), '')")
    return f"TO_HEX(SHA256(ARRAY_TO_STRING([{', '.join(parts)}], '|')))"


INPUT_SQL = """\
WITH map AS (
  SELECT * FROM (
    SELECT
      {fingerprint} AS row_fingerprint,
      sportsbook, sport, league, start_date, home, away, market_type, entity,
      line, side, group_key,
      -- Kept for triage in the verdict table even though the prompt shows no
      -- dates: when a human does need to check an exchange's date convention,
      -- the US-Eastern date is the one to compare against.
      DATE(start_date, 'America/New_York') AS et_date,
      game_id, market_id, selection, selection_line, points, grouping_key,
      JSON_VALUE(TO_JSON_STRING(source_ids), '$.market_id')    AS src_market_id,
      JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id') AS src_selection_id,
      JSON_VALUE(TO_JSON_STRING(source_ids), '$.symbol')       AS src_symbol,
      last_updated
    FROM `{project}.markets_us.market_mapping`
    WHERE start_date BETWEEN @date_from AND @date_to
      AND sportsbook IN UNNEST(@sportsbooks)
  )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY row_fingerprint ORDER BY last_updated DESC
  ) = 1
), fx AS (
  -- Padded by {fixture_pad} days on both sides ON PURPOSE. Filtering fixtures by
  -- the SAME window as the mapping rows drops any fixture whose Optic start_date
  -- has drifted (reschedule, or a kickoff either side of the boundary), and the
  -- LEFT JOIN then yields a NULL name -- which cost us the whole readable
  -- matchup for 55 tennis rows and made the model fall back to the slug date.
  -- IFNULL because CONCAT() with one NULL argument returns NULL, not a partial
  -- string.
  SELECT game_id,
         NULLIF(
           CONCAT(IFNULL(home_team_display, ''), ' v ', IFNULL(away_team_display, '')),
           ' v '
         ) AS fixture_name
  FROM `{project}.opticodds_us.opticodds_fixtures`
  WHERE start_date BETWEEN TIMESTAMP_SUB(@date_from, INTERVAL {fixture_pad} DAY)
                       AND TIMESTAMP_ADD(@date_to, INTERVAL {fixture_pad} DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY publish_time DESC) = 1
), {exchange_ctes}, corr AS (
  -- Optic's OWN id for the same selection: the deterministic witness that makes
  -- an LLM verdict redundant.
  -- points is FLOAT64, which BigQuery refuses to PARTITION BY, so the whole
  -- key (here and in the join below) compares it as a fixed-precision string.
  SELECT game_id, market_id, selection, sportsbook,
         LOWER(IFNULL(selection_line, ''))    AS sl,
         FORMAT('%.2f', IFNULL(points, 0))    AS pts,
         IFNULL(grouping_key, '')             AS gk,
         JSON_VALUE(TO_JSON_STRING(source_ids), '$.market_id')    AS o_market_id,
         JSON_VALUE(TO_JSON_STRING(source_ids), '$.selection_id') AS o_selection_id
  FROM `{project}.opticodds_us.prices_dedup_state`
  WHERE start_date BETWEEN @date_from AND @date_to
    AND sportsbook IN UNNEST(@corroborated)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY game_id, market_id, selection, sportsbook,
                 LOWER(IFNULL(selection_line, '')),
                 FORMAT('%.2f', IFNULL(points, 0)),
                 IFNULL(grouping_key, '')
    ORDER BY last_updated DESC
  ) = 1
)
SELECT m.* EXCEPT (last_updated),
       f.fixture_name,
       {exchange_selects}
FROM map m
LEFT JOIN fx f ON f.game_id = m.game_id
{exchange_joins}
LEFT JOIN corr o
  ON o.game_id = m.game_id AND o.market_id = m.market_id AND o.selection = m.selection
 AND o.sportsbook = m.sportsbook
 AND o.sl = LOWER(IFNULL(m.selection_line, ''))
 AND o.pts = FORMAT('%.2f', IFNULL(m.points, 0))
 AND o.gk = IFNULL(m.grouping_key, '')
 AND IFNULL(o.o_market_id, '') = IFNULL(m.src_market_id, '')
 AND IFNULL(o.o_selection_id, '') = IFNULL(m.src_selection_id, '')
LEFT JOIN `{project}.{table}` v
  ON v.row_fingerprint = m.row_fingerprint
 AND v.prompt_version = {prompt_version}
 AND v.start_date BETWEEN @date_from AND @date_to
WHERE ({revalidate} = 1 OR v.row_fingerprint IS NULL)
  AND ({include_corroborated} = 1 OR o.game_id IS NULL)
ORDER BY m.sportsbook, m.start_date, m.game_id, m.market_type, m.line
"""  # nosec B608 — every interpolated value is a module constant or an int flag


SCHEMA = [
    bigquery.SchemaField(
        "row_fingerprint", "STRING", "REQUIRED",
        description="SHA256 of the market_mapping MERGE key + source_ids; MERGE key, judged once per prompt_version",
    ),
    bigquery.SchemaField("start_date", "TIMESTAMP", "REQUIRED", description="Fixture start (partition key)"),
    bigquery.SchemaField("sportsbook", "STRING", "REQUIRED", description="Kalshi / Polymarket / crypto.com / Novig"),
    bigquery.SchemaField("sport", "STRING", "NULLABLE", description="Our canonical sport"),
    bigquery.SchemaField("league", "STRING", "NULLABLE", description="Our canonical league"),
    bigquery.SchemaField("home", "STRING", "NULLABLE", description="Our canonical home abbreviation"),
    bigquery.SchemaField("away", "STRING", "NULLABLE", description="Our canonical away abbreviation"),
    bigquery.SchemaField("market_type", "STRING", "NULLABLE", description="Our canonical market type"),
    bigquery.SchemaField("entity", "STRING", "NULLABLE", description="Player/entity for props"),
    bigquery.SchemaField("line", "FLOAT", "NULLABLE", description="Our canonical line"),
    bigquery.SchemaField("side", "STRING", "NULLABLE", description="Our canonical side"),
    bigquery.SchemaField("group_key", "STRING", "NULLABLE", description="Our disambiguation group"),
    bigquery.SchemaField("game_id", "STRING", "NULLABLE", description="Optic game_id"),
    bigquery.SchemaField("market_id", "STRING", "NULLABLE", description="Optic market_id"),
    bigquery.SchemaField("selection", "STRING", "NULLABLE", description="Optic selection"),
    bigquery.SchemaField("selection_line", "STRING", "NULLABLE", description="Optic selection_line (over/under)"),
    bigquery.SchemaField("points", "FLOAT", "NULLABLE", description="Optic points"),
    bigquery.SchemaField("grouping_key", "STRING", "NULLABLE", description="Optic grouping_key"),
    bigquery.SchemaField("fixture_name", "STRING", "NULLABLE", description="'Home v Away' display names from Optic"),
    bigquery.SchemaField(
        "exchange_ref", "STRING", "NULLABLE",
        description="The id judged: Kalshi ticker / Polymarket clob_token_id / crypto.com FIX symbol / Novig outcome_id",
    ),
    bigquery.SchemaField(
        "exchange_side", "STRING", "NULLABLE", description="Kalshi yes/no side or Polymarket outcome label"
    ),
    bigquery.SchemaField(
        "exchange_text", "STRING", "NULLABLE", description="The exchange-native text the model was shown"
    ),
    bigquery.SchemaField("fixture_ok", "BOOLEAN", "NULLABLE", description="Same game/participants"),
    bigquery.SchemaField("market_ok", "BOOLEAN", "NULLABLE", description="Same market and scope/period"),
    bigquery.SchemaField("side_ok", "BOOLEAN", "NULLABLE", description="Same side/polarity"),
    bigquery.SchemaField("line_ok", "BOOLEAN", "NULLABLE", description="Same threshold"),
    bigquery.SchemaField("entity_ok", "BOOLEAN", "NULLABLE", description="Player props only; null otherwise"),
    bigquery.SchemaField("mapping_ok", "BOOLEAN", "NULLABLE", description="Whole mapping correct"),
    bigquery.SchemaField("reason", "STRING", "NULLABLE", description="One clause naming the contradiction; null if ok"),
    bigquery.SchemaField("prompt_version", "INTEGER", "REQUIRED", description="PROMPT_VERSION that produced this row"),
    bigquery.SchemaField("model", "STRING", "NULLABLE", description="Gemini model id"),
    bigquery.SchemaField("validated_at", "TIMESTAMP", "NULLABLE", description="When the verdict was written"),
]


# === Prompt ===

_PROMPT_CORE = """\
You audit prediction-market mappings. Each numbered row pairs OURS (a bet as our
mapper resolved it, in OpticOdds terms) with the EXCHANGE listing we mapped it to.
Return one verdict per row: same `i`, the booleans, and `reason` (null when all
pass; one short clause naming the contradiction otherwise). No other prose.

Reason step by step before deciding. Return false ONLY on a clear, nameable
contradiction. Uncertain = true -- false alarms cost more than misses. Judge ONLY
internal consistency between OURS and the EXCHANGE text; ignore stale
roster/transfer/schedule knowledge. Same player/team named on both sides = match
regardless of what you believe.

fixture_ok -- same game/participants, ignoring market, side, line. Spelling,
diacritics, abbreviations and national aliases (USA=United States, China=China PR)
are fine; OURS names teams by short code (BOS, NAK) and the exchange spells them
out. Different teams or a different game = false. Correct fixture with a wrong
market/side/line is still fixture_ok=true -- mapping_ok carries that failure.

THERE ARE NO DATES IN THIS TASK. No date is shown on either side and every date
inside a ticker or symbol is blanked to `*`, because the exchange's date is what
the matcher used to FIND this fixture -- re-checking it here would be circular,
and tournament schedules shift anyway. Judge the fixture on WHO IS PLAYING.
Never write a date-based `reason`; there is no date to disagree about.

When OURS `ev` is empty, the fixture is only available as the short codes in
parentheses (e.g. (YPU6 v ZHA)). Match those against the exchange's names as
prefixes/initials -- ZHA vs 'Zhang' is a match -- and pass unless the exchange
clearly names DIFFERENT people. An empty `ev` is missing data on our side, not
evidence of a wrong mapping.

market_ok -- same market AND same scope. Moneyline~winner, spread~handicap,
total~over/under of the same statistic. Different period or scope (1st half vs
full game, 1st inning vs game, regulation vs including overtime) = false.
Binary occurrence markets (yes/no) are equivalent to over/under 0.5.

MARKET SHAPE IS NOT A SCOPE. Every OURS row is ONE LEG of its market, so a 3-way
market's leg IS a binary question and matching them is correct, not a "3-way vs
2-way" mismatch. OURS mkt=2h_winner_3way side=LEV == POLY 'PFK Levski Sofia to win
the second half?' outcome=Yes; side=_TIE == 'Second half draw?' outcome=Yes. Judge
whether THIS LEG and the exchange contract settle together -- never compare how
many legs each market has.

side_ok -- same side. OURS `side` is a team code, OVER/UNDER, YES/NO, or a player.
It must agree with the exchange's side. pts=0 on a yes/no market is a placeholder,
not a real line.

CORRECT SCORE / EXACT SCORE is WINNER-ANCHORED on our side, and this is the
single most common thing to get wrong. OURS `sl`/`line` reads
<WINNER's goals>:<LOSER's goals> and OURS `side` names the WINNER (`_TIE` for a
draw) -- it is NOT home:away. Exchanges write the score in FIXTURE order
(home - away). So OURS side=SLO sl='2:1' == POLY 'Exact Score: Central Cordoba 1
- 2 San Lorenzo?' -- San Lorenzo scored 2, the opponent 1, San Lorenzo won.
REORDER the exchange's two numbers around the winner before comparing: the
contract matches when the winner's count, the loser's count, and which team holds
the higher count all agree. A reversed-looking pair is only a real mismatch when
the two numbers themselves differ (2:1 vs 3:1), or when OURS `side` is not the
team with the exchange's higher number.

line_ok -- same threshold, per that exchange's encoding (below). A market with no
threshold (moneyline, winner, yes/no occurrence) is line_ok=true. A missing line
on one side alone is NEVER by itself a mismatch.

OURS `grp` IS NOT THE BET'S LINE. It is the mapper's pairing key, used to group
the legs of one market together, and on spread/handicap rows its number is
routinely the MIRROR of the real line: a row with line=+4.5 carries
grp='default:-4.5'. Read the side and the threshold from `pts`, `line` and `sl`
ONLY. Never take a number out of `grp`, and never write a `reason` whose
disagreement rests on one -- if `grp` is the only place a conflicting sign
appears, there is no contradiction and the row passes. The sole judgeable content
in `grp` is the player name it can carry (see entity_ok).

entity_ok -- player props only: OURS `entity` (or the player named in
grouping_key) matches the player in the exchange text. Spelling, diacritics, name
order and suffixes are fine. Different player = false. Not a player prop = null.

mapping_ok -- all of the above hold. False if any of them is false."""

_EXAMPLES = """\
EXAMPLES (all valid, true):
- OURS mkt=moneyline sel='Brandon Nakashima' side=NAK || KALSHI t=<opaque> s=yes
  title='Will Brandon Nakashima win the Nakashima vs Mensik: Round Of 16 match?'
- OURS sl=under pts=1.5 || KALSHI s=no title='Vladimir Guerrero Jr.: 2+ hits?':
  2+ = over 1.5, s=no = under 1.5.
- OURS sel='Cincinnati Reds' pts=-3.5 || KALSHI s=yes title='Cincinnati wins by
  more than 3.5 runs?': Cincinnati -3.5.
- OURS sel='Houston Astros' pts=1.5 || KALSHI s=no title='Athletics wins by more
  than 1.5 runs?': complement = Houston +1.5 (correct underdog shape).
- OURS mkt=moneyline side=GEN || POLY q='Bonn: Tom Gentzsch vs Max Dahlin' outcome='Tom Gentzsch'
  slug=atp-gentzsc-dahlin-2026-07-30.
- OURS mkt=moneyline side=NAK || CRYPTO sel='Brandon Nakashima to win' event='Nakashima vs Mensik'.
- OURS mkt=point_spread side=SLO line=8.5 || CRYPTO sel='SK Slovan Bratislava 8.5 to win'
  contract='Spread': no minus, so this is the +8.5 side and OURS +8.5 agrees.
- OURS entity='Jonquel Jones' side=under line=2.5 mkt=player_rebounds || NOVIG
  sel='Under 2.5' mkt='Total Rebounds' who='Jonquel Jones': `sel` alone names no
  player, but `who` does -- entity_ok compares OURS entity against `who`, not `sel`.
"""

#: Per-sportsbook rule block (each exchange's own `prompt`); batches are
#: partitioned by sportsbook so a call only ever carries the one it needs.
EXCHANGE_PROMPTS = exchanges.prompts()


class Verdict(BaseModel):
    """One model verdict for the row at index `i` of the batch."""

    i: int
    fixture_ok: bool
    market_ok: bool
    side_ok: bool
    line_ok: bool
    #: player props only; null on any other row
    entity_ok: bool | None = None
    mapping_ok: bool
    #: short clause naming the contradiction; null when every verdict passes
    reason: str | None = None


def system_prompt_for(sportsbook: str) -> str:
    """Assemble the system prompt for a single-sportsbook batch."""
    spec = exchanges.get(sportsbook)
    block = spec.prompt if spec else ""
    return f"{_PROMPT_CORE}\n\n{block}\n\n{_EXAMPLES}"


def _num(value: Any) -> str:
    """Compact float rendering (2.5 not 2.50, 1 not 1.0)."""
    return f"{float(value):g}"


def has_exchange_text(row: dict) -> bool:
    """True when the row carries exchange-native text worth judging.

    Without it the model has only our own side of the pair and can do nothing but
    guess, so such rows are dropped before batching (they cost tokens and produce
    noise). Cause is usually stale upstream data: a Kalshi ticker older than the
    raw stash window, a Polymarket token absent from the bridge, or a crypto
    symbol not in the catalogue.
    """
    spec = exchanges.get(row.get("sportsbook"))
    return spec.has_text(row) if spec else False


def exchange_ref(row: dict) -> str | None:
    """The exchange id under judgement (ticker / clob token / FIX symbol)."""
    spec = exchanges.get(row.get("sportsbook"))
    return spec.ref(row) if spec else None


def exchange_side(row: dict) -> str | None:
    """The exchange's own side label, where it has one."""
    spec = exchanges.get(row.get("sportsbook"))
    return spec.side(row) if spec else None


def exchange_text(row: dict) -> str | None:
    """The exchange-native text shown to the model, kept for triage."""
    spec = exchanges.get(row.get("sportsbook"))
    return spec.text(row) if spec else None


def _ours_line(row: dict) -> str:
    """Render our side of the pair: the canonical bet in OpticOdds terms.

    No date appears here, deliberately — see `mask_exchange_dates`. Fixture
    identity is judged on participants; dates are the matcher's join key.
    """
    out = (
        f"OURS ev='{row.get('fixture_name') or ''}' ({row.get('home') or ''} v {row.get('away') or ''})"
        f" sport={row.get('sport') or ''} league={row.get('league') or ''}"
        f" mkt={row.get('market_type') or ''} optic_mkt={row.get('market_id') or ''}"
        f" sel='{row.get('selection') or ''}'"
    )
    if row.get("selection_line"):
        out += f" sl={row['selection_line']}"
    if row.get("points") is not None:
        out += f" pts={_num(row['points'])}"
    out += f" side={row.get('side') or ''}"
    if row.get("entity"):
        out += f" entity='{row['entity']}'"
    if row.get("line") is not None:
        out += f" line={_num(row['line'])}"
    if row.get("grouping_key") and row["grouping_key"] != "default":
        out += f" grp='{row['grouping_key']}'"
    return out


def _exchange_line(row: dict) -> str:
    """Render the exchange side of the pair, in that exchange's own terms."""
    spec = exchanges.get(row.get("sportsbook"))
    return spec.line(row) if spec else str(row.get("sportsbook") or "")


def row_line(i: int, row: dict) -> str:
    """One compact prompt line pairing our bet with the exchange listing."""
    return f"{i}. {_ours_line(row)} || {_exchange_line(row)}"


def build_prompt(chunk: list[dict]) -> str:
    """Render a batch as numbered prompt lines."""
    return "\n".join(row_line(i, r) for i, r in enumerate(chunk))


def chunked(rows: list[dict], size: int) -> list[list[dict]]:
    """Split rows into fixed-size batches."""
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def partition_chunks(rows: list[dict], size: int) -> list[list[dict]]:
    """Batch rows per sportsbook, then INTERLEAVE the batches round-robin.

    Every batch stays single-sportsbook (that is what lets a call carry only one
    rule block), but the batches are dealt out one per exchange in turn rather
    than all of Kalshi, then all of Polymarket, then all of crypto.com.

    Grouping them by exchange meant the smallest book was always judged last, so
    for the whole of a re-judge crypto.com held no rows at the current
    prompt_version and vanished from every version-filtered dashboard panel --
    which read exactly like a broken mapping. Interleaving makes progress roughly
    proportional across exchanges instead.
    """
    per_book = [chunked([r for r in rows if r.get("sportsbook") == book], size) for book in SPORTSBOOKS]
    out: list[list[dict]] = []
    for i in range(max((len(chunks) for chunks in per_book), default=0)):
        for chunks in per_book:
            if i < len(chunks):
                out.append(chunks[i])
    return out


def derive_mapping_ok(verdict: Verdict, *, is_prop: bool) -> bool:
    """`mapping_ok` as a pure function of the component verdicts.

    fixture / market / side / line (+ entity on props) are exhaustive over what a
    mapping can get wrong, so an all-in "false" with every component passing names
    no contradiction at all -- and the model produced exactly that on 51 rows,
    every one with a `reason` we had already ruled out (a date). Deriving the
    all-in verdict makes it coherent by construction; the model's prose still
    reaches the reviewer through `reason`.
    """
    components: list[bool | None] = [
        verdict.fixture_ok,
        verdict.market_ok,
        verdict.side_ok,
        verdict.line_ok,
    ]
    if is_prop:
        components.append(verdict.entity_ok)
    return all(c is not False for c in components)


def verdict_rows(chunk: list[dict], verdicts: list[Verdict], model: str, validated_at: str) -> list[dict]:
    """Join verdicts back onto their rows, ready for the MERGE.

    A missing or out-of-range `i` drops that row: the anti-join only skips
    written verdicts, so it simply re-enters on the next run.
    """
    by_i = {v.i: v for v in verdicts}
    out: list[dict] = []
    incoherent = 0
    for i, row in enumerate(chunk):
        verdict = by_i.get(i)
        if verdict is None:
            continue
        start: Any = row.get("start_date")
        is_prop = bool(row.get("entity"))
        mapping_ok = derive_mapping_ok(verdict, is_prop=is_prop)
        if mapping_ok != verdict.mapping_ok:
            incoherent += 1
        out.append(
            {
                "row_fingerprint": row["row_fingerprint"],
                "start_date": start.isoformat() if hasattr(start, "isoformat") else start,
                "sportsbook": row.get("sportsbook"),
                "sport": row.get("sport"),
                "league": row.get("league"),
                "home": row.get("home"),
                "away": row.get("away"),
                "market_type": row.get("market_type"),
                "entity": row.get("entity"),
                "line": row.get("line"),
                "side": row.get("side"),
                "group_key": row.get("group_key"),
                "game_id": row.get("game_id"),
                "market_id": row.get("market_id"),
                "selection": row.get("selection"),
                "selection_line": row.get("selection_line"),
                "points": row.get("points"),
                "grouping_key": row.get("grouping_key"),
                "fixture_name": row.get("fixture_name"),
                "exchange_ref": exchange_ref(row),
                "exchange_side": exchange_side(row),
                "exchange_text": exchange_text(row),
                "fixture_ok": verdict.fixture_ok,
                "market_ok": verdict.market_ok,
                "side_ok": verdict.side_ok,
                "line_ok": verdict.line_ok,
                # no entity -> not a player prop, whatever the model said
                "entity_ok": verdict.entity_ok if is_prop else None,
                "mapping_ok": mapping_ok,
                "reason": verdict.reason or None,
                "prompt_version": PROMPT_VERSION,
                "model": model,
                "validated_at": validated_at,
            }
        )
    if incoherent:
        logger.info(
            "%d/%d verdicts had an all-in value contradicting their own components; using the derived one",
            incoherent,
            len(out),
        )
    dropped = len(chunk) - len(out)
    if dropped:
        logger.warning(
            "verdict join dropped %d/%d rows (model returned missing/bad indices); they re-enter next run",
            dropped,
            len(chunk),
        )
    return out


# === Alert rollup ===

FAILED_CHECKS = ("fixture_ok", "market_ok", "side_ok", "line_ok", "entity_ok")


@dataclass(frozen=True, slots=True)
class FlagSummaryRow:
    """One grouped row of flagged mappings for the alert body."""

    sportsbook: str
    league: str
    failed_check: str
    count: int
    sample_ref: str


def summarize_flags(rows: list[dict]) -> list[FlagSummaryRow]:
    """Group flagged verdicts by sportsbook, league and the check that failed.

    Rows with `mapping_ok` true are ignored even if a sub-check failed: the
    all-in verdict is the one the review queue is sorted on.
    """
    counts: Counter[tuple[str, str, str]] = Counter()
    samples: dict[tuple[str, str, str], str] = {}
    for row in rows:
        if row.get("mapping_ok") is not False:
            continue
        failed = [c for c in FAILED_CHECKS if row.get(c) is False] or ["mapping_ok"]
        key = (str(row.get("sportsbook") or "?"), str(row.get("league") or "?"), failed[0])
        counts[key] += 1
        samples.setdefault(key, str(row.get("exchange_ref") or ""))
    return [
        FlagSummaryRow(sportsbook=k[0], league=k[1], failed_check=k[2], count=n, sample_ref=samples.get(k, ""))
        for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def format_summary(flagged: list[FlagSummaryRow], judged: int) -> str:
    """Format flagged verdicts as human-readable alert text."""
    total = sum(row.count for row in flagged)
    header = f"AI mapping validation: {total} flagged of {judged} judged (prompt v{PROMPT_VERSION})"
    lines = [header]
    for row in flagged:
        sample = f" e.g. {row.sample_ref}" if row.sample_ref else ""
        lines.append(f"- [{row.sportsbook}/{row.league}] {row.failed_check}=false: {row.count}{sample}")
    lines.append("")
    review = f"SELECT * FROM {TABLE} WHERE NOT mapping_ok AND prompt_version = {PROMPT_VERSION}"  # nosec B608 — alert text for a human to paste, never executed
    lines.append(f"Review: {review}")
    return "\n".join(lines)


# === Model plumbing ===


def _gemini_api_key(project: str) -> str:
    """GOOGLE_API_KEY wins (local .env); otherwise Secret Manager over ADC.

    The client library, not the gcloud CLI: the GKE image has no gcloud, and
    Workload Identity supplies the credentials there.
    """
    key = os.getenv("GOOGLE_API_KEY")
    if key:
        return key
    from google.cloud import secretmanager

    name = f"projects/{project}/secrets/{GEMINI_SECRET}/versions/latest"
    return secretmanager.SecretManagerServiceClient().access_secret_version(name=name).payload.data.decode().strip()


def validate_chunk(client: Any, model: str, chunk: list[dict]) -> list[Verdict]:
    """Ask the model for one verdict per row in `chunk`."""
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=build_prompt(chunk),
        config=types.GenerateContentConfig(
            system_instruction=system_prompt_for(str(chunk[0].get("sportsbook") or "")),
            temperature=0,
            response_mime_type="application/json",
            response_schema=list[Verdict],
            thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
            # dynamic thinking can run long; a stuck call must not hold a worker
            # slot forever (the retry/drop path below handles the timeout)
            http_options=types.HttpOptions(timeout=180_000),
        ),
    )
    parsed = resp.parsed
    if parsed is None:
        parsed = [Verdict.model_validate(v) for v in json.loads(resp.text or "[]")]
    return list(parsed)


def _join_specs(piece: Callable[[ExchangeSpec], str], sep: str) -> str:
    """Join one SQL fragment per registered exchange, in registry order."""
    return sep.join(piece(spec) for spec in exchanges.EXCHANGES.values())


def build_sql(project: str, *, revalidate: bool, include_corroborated: bool) -> str:
    """Render the input SQL for this run."""
    return INPUT_SQL.format(
        exchange_ctes=_join_specs(lambda x: x.render_cte(project), ", "),
        exchange_joins=_join_specs(lambda x: x.join_sql, "\n"),
        exchange_selects=_join_specs(lambda x: x.select_sql, ",\n       "),
        project=project,
        table=TABLE,
        fingerprint=_fingerprint_expr(),
        prompt_version=PROMPT_VERSION,
        revalidate=1 if revalidate else 0,
        include_corroborated=1 if include_corroborated else 0,
        fixture_pad=FIXTURE_PAD_DAYS,
    )


def fetch_rows(
    client: bigquery.Client,
    sql: str,
    *,
    date_from: datetime,
    date_to: datetime,
    sportsbooks: list[str],
) -> list[dict]:
    """Run the input SQL and return candidate rows as plain dicts."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("date_from", "TIMESTAMP", date_from),
            bigquery.ScalarQueryParameter("date_to", "TIMESTAMP", date_to),
            bigquery.ArrayQueryParameter("sportsbooks", "STRING", sportsbooks),
            bigquery.ArrayQueryParameter("corroborated", "STRING", list(CORROBORATED_SPORTSBOOKS)),
        ],
        maximum_bytes_billed=50 * 1024**3,
    )
    return [dict(row) for row in client.query(sql, job_config=job_config).result()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="AI-validate our Kalshi/Polymarket/crypto.com/Novig mappings")
    parser.add_argument("--sportsbook", default="all", choices=["all", *SPORTSBOOKS])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-rows", type=int, default=BATCH_ROWS)
    parser.add_argument("--max-rows", type=int, help="cap rows sent to the model")
    parser.add_argument("--date-from", help="fixture window start (YYYY-MM-DD, inclusive). Default: yesterday.")
    parser.add_argument("--date-to", help="fixture window end (YYYY-MM-DD, inclusive). Default: +14 days.")
    parser.add_argument(
        "--revalidate", action="store_true", help="ignore existing verdicts and re-judge the whole window"
    )
    parser.add_argument(
        "--include-corroborated",
        action="store_true",
        help="also judge rows where Optic publishes the same exchange id (skipped by default: pure spend)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="run the SQL, print counts + the first prompt; no model call, no write"
    )
    parser.add_argument("--print-sql", action="store_true", help="print the rendered input SQL and exit")
    parser.add_argument("--no-alert", action="store_true", help="skip the Pub/Sub rollup")
    return parser.parse_args(argv)


def _window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    """Resolve the fixture window from the CLI args."""
    now = datetime.now(UTC)
    date_from = (
        datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.date_from
        else (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    date_to = (
        datetime.strptime(args.date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)
        if args.date_to
        else (now + timedelta(days=14)).replace(hour=23, minute=59, second=59, microsecond=0)
    )
    return date_from, date_to


def main(argv: list[str] | None = None) -> None:
    """Judge every not-yet-judged mapping in the window and MERGE the verdicts."""
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    args = _parse_args(argv)
    client = bq_client()
    project = client.project
    sql = build_sql(project, revalidate=args.revalidate, include_corroborated=args.include_corroborated)

    if args.print_sql:
        print(sql)
        return

    target = qualify(client, TABLE)
    stage = qualify(client, STAGE)
    # Idempotent: a no-op once Terraform owns the table, but keeps the module
    # runnable standalone (first run, dry runs, a fresh project).
    ensure_table(client, target, SCHEMA, PARTITION_FIELD, CLUSTERING)

    date_from, date_to = _window(args)
    books: list[str] = [str(b) for b in (SPORTSBOOKS if args.sportsbook == "all" else [args.sportsbook])]
    rows = fetch_rows(client, sql, date_from=date_from, date_to=date_to, sportsbooks=books)

    with_text = [r for r in rows if has_exchange_text(r)]
    if len(with_text) != len(rows):
        by_book = Counter(str(r.get("sportsbook")) for r in rows if not has_exchange_text(r))
        logger.warning(
            "skipping %d/%d rows with no exchange text (%s) — upstream listing text missing, not a mapping verdict",
            len(rows) - len(with_text),
            len(rows),
            ", ".join(f"{k}: {v}" for k, v in sorted(by_book.items())),
        )
    rows = with_text
    if args.max_rows:
        rows = rows[: args.max_rows]

    per_book = Counter(str(r.get("sportsbook")) for r in rows)
    logger.info(
        "rows to judge (prompt v%d): %d (%s)",
        PROMPT_VERSION,
        len(rows),
        ", ".join(f"{k}: {v}" for k, v in sorted(per_book.items())) or "none",
    )
    if not rows:
        return

    chunks = partition_chunks(rows, args.batch_rows)
    if args.dry_run:
        logger.info("--dry-run: %d model calls of <= %d rows", len(chunks), args.batch_rows)
        print(build_prompt(chunks[0]))
        return

    from google import genai

    model_client = genai.Client(api_key=_gemini_api_key(project))
    pending: list[dict] = []
    written: list[dict] = []

    def judge(chunk: list[dict]) -> list[dict]:
        """Judge one batch, retrying once before dropping it to the next run."""
        try:
            verdicts = validate_chunk(model_client, args.model, chunk)
        except Exception as exc:  # noqa: BLE001 — any model/transport error retries once
            logger.warning("chunk failed (%s); retrying once", exc)
            try:
                verdicts = validate_chunk(model_client, args.model, chunk)
            except Exception as exc2:  # noqa: BLE001
                logger.error("chunk dropped after retry: %s", exc2)
                return []
        return verdict_rows(chunk, verdicts, args.model, datetime.now(UTC).isoformat())

    def flush(batch: list[dict]) -> None:
        """Stage + MERGE one buffer of verdicts."""
        if batch:
            stage_and_merge(client, target, stage, SCHEMA, batch, KEY_COL)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(judge, chunk) for chunk in chunks]
        for done, future in enumerate(as_completed(futures), 1):
            batch = future.result()
            pending.extend(batch)
            written.extend(batch)
            if len(pending) >= FLUSH_EVERY:
                flush(pending)
                pending = []
            if done % 10 == 0 or done == len(futures):
                logger.info("judged %d/%d batches (%d verdicts)", done, len(futures), len(written))
    flush(pending)

    flagged = summarize_flags(written)
    logger.info(
        "done — %d verdicts merged into %s, %d flagged",
        len(written),
        target,
        sum(row.count for row in flagged),
    )
    if flagged:
        text = format_summary(flagged, len(written))
        logger.warning(text)
        if not args.no_alert:
            publisher = build_publisher()
            try:
                publisher.publish("warning", text)
            finally:
                publisher.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
