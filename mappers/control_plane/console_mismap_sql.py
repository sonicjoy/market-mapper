"""BigQuery for Explore -> Mapping risk (mismapping detector, mmmapper#23).

One query returns every mapping we might serve in the next ``HORIZON_HOURS``
(plus in-play since ``INPLAY_HOURS`` ago) with the evidence the Python scorer
needs. Nothing is judged here: the SQL only lines up independent sources.

- ``m``      : ``opticodds_us.opticodds_mapping`` rows for the venues we quote.
               ``mapping_source = 'ORIGINAL'`` is Optic's own mapping of the
               venue id; everything else (GREG, overrides, PX external) is ours.
- ``keys``   : per venue key, how many distinct canonical selections each side
               claims -> source disagreement and one-to-many collisions.
- ``canons`` : per canonical selection, how many of OUR venue keys point at it
               -> many-to-one collisions.
- ``vp``     : the venue's own latest price for that venue key, as carried in
               Optic's feed (``opticodds_prices``; only venues Optic lists).
- ``fp``     : our latest de-vigged fair for the canonical selection we mapped.
- ``ai``     : the latest AI validator verdict for the row
               (``markets_us.market_mapping_ai_validation``), with the venue text.

Scans (dry-run 2026-09-26): opticodds_mapping ~0.9 GB (not partitioned on
start_date), opticodds_prices 30 min ~0.9 GB, parlay_fair_price_v2 30 min
~0.1 GB, ai_validation partition-pruned. The page caches for CACHE_TTL_SECONDS.
"""

from __future__ import annotations

HORIZON_HOURS = 48
INPLAY_HOURS = 4
PRICE_WINDOW_MINUTES = 30
CACHE_TTL_SECONDS = 3600.0  # owner, 2026-09-26: 1h; the UI says so and Refresh bypasses it

# Venues whose mappings we serve; lower-cased sportsbook values in opticodds_mapping.
VENUES = (
    "kalshi",
    "polymarket",
    "polymarket (usa)",
    "novig",
    "prophet x",
    "sx bet",
    "underdog",
    "crypto.com",
)
# Venues Optic carries a price for (opticodds_prices, checked 2026-09-26).
PRICED_VENUES = ("kalshi", "polymarket", "novig", "prophet x")

# Venue key: crypto.com is keyed by symbol; every other venue by its id triple.
_SRC_KEY = """case when lower({t}.sportsbook) = 'crypto.com'
      then coalesce(json_value({t}.source_ids, '$.symbol'), '')
      else concat(coalesce(json_value({t}.source_ids, '$.event_id'), ''), '|',
                  coalesce(json_value({t}.source_ids, '$.market_id'), ''), '|',
                  coalesce(json_value({t}.source_ids, '$.selection_id'), '')) end"""

# Market-level identity: the two sides of one market (over/under, yes/no, +/-
# spread) share it, so a venue key pointing at both is NOT a collision. When the
# side lives in selection_line (over/under), selection is the player/team the
# market is about and stays in the key; otherwise selection IS the side.
# Identity is the Optic fixture_id only: stable across a reschedule (game_id carries the
# start hour and is re-issued) and what the live fair-price cache is keyed on. No game_id
# fallback - mixing the two id spaces counted one market twice (298 false Prophet X
# "several markets" on 2026-09-27). A row with no fixture_id yields a NULL key, drops out
# of every grouping and is flagged by missing_fixture_id instead.
_MARKET = """concat({t}.fixture_id, '|', {t}.market_id, '|',
      if(lower(coalesce({t}.selection_line, '')) in ('over', 'under'), lower(coalesce({t}.selection, '')), ''),
      '|', format('%.2f', abs(coalesce({t}.points, 0))))"""

_CANON = """concat({t}.fixture_id, '|', {t}.market_id, '|', lower(coalesce({t}.selection, '')), '|',
      coalesce({t}.selection_line, ''), '|', format('%.2f', coalesce({t}.{pts}, 0)))"""


def _venue_list(values: tuple[str, ...]) -> str:
    """SQL string list literal from module constants (never caller input)."""
    return ", ".join(f"'{v}'" for v in values)


# opticodds_fixtures is a SNAPSHOT (one current game_id per fixture id, upcoming/live
# only). A row is a reschedule leftover when the snapshot lists its fixture_id under a
# DIFFERENT game_id (Optic re-keys a rescheduled game; the id carries the start hour) -
# the same rule fold+rank uses. A fixture missing from the snapshot (finished, out of
# window, completed / cancelled) is unknown, not stale. A 3-day lookback that let a
# COMPLETED listing define "current" flagged 876-901 live games in the first prod alert
# (2026-09-27 16:07; e.g. fixture 202609271F8EFA33, moved 09-26 -> 09-27, whose snapshot
# row is the old game marked completed). Same window + status rule as fold+rank.

_MAPPINGS = f"""
fx as (
  select id as fixture_id, game_id
  from `{{project}}.opticodds_us.opticodds_fixtures`
  where start_date between timestamp_sub(current_timestamp(), interval 4 hour)
                       and timestamp_add(current_timestamp(), interval 14 day)
    and status in ('unplayed', 'live', 'delayed')
  qualify row_number() over (partition by id order by publish_time desc) = 1
),
m as (
  select
    lower(o.sportsbook) as sb, o.sportsbook as book,
    {_SRC_KEY.format(t="o")} as src_key,
    {_CANON.format(t="o", pts="points")} as canon,
    {_MARKET.format(t="o")} as market_key,
    json_value(o.source_ids, '$.market_id') as src_market,
    json_value(o.source_ids, '$.selection_id') as src_selection,
    json_value(o.source_ids, '$.symbol') as src_symbol,
    o.game_id, o.fixture_id, o.start_date, o.sport, o.league, o.market_id, o.market,
    o.selection, o.selection_line, o.points, o.mapping_source, o.rank_class,
    coalesce(o.is_rfq_winner, false) as is_rfq_winner,
    coalesce(o.is_mapping_override, false) as is_override,
    o.market_match_method, o.verify_tier,
    -- Stale only when the snapshot lists THIS fixture under a different game_id (same rule as
    -- fold+rank). A fixture absent from the snapshot (finished / out of window) is unknown: NULL.
    if(fx.fixture_id is null, null, fx.game_id = o.game_id) as game_live
  from `{{project}}.opticodds_us.opticodds_mapping` as o
  left join fx on fx.fixture_id = o.fixture_id
  where o.start_date between timestamp_sub(current_timestamp(), interval {INPLAY_HOURS} hour)
                         and timestamp_add(current_timestamp(), interval {HORIZON_HOURS} hour)
    and lower(o.sportsbook) in ({_venue_list(VENUES)})
),
keys as (
  select sb, src_key,
    count(distinct if(mapping_source = 'ORIGINAL', canon, null)) as n_optic,
    count(distinct if(mapping_source != 'ORIGINAL', market_key, null)) as n_ours,
    array_agg(distinct if(mapping_source = 'ORIGINAL', canon, null) ignore nulls limit 3) as optic_canons,
    array_agg(distinct if(mapping_source != 'ORIGINAL', canon, null) ignore nulls limit 3) as our_canons
  from m
  group by sb, src_key
),
-- Many-to-one reads the mapper's raw output: opticodds_mapping keeps one of our
-- venue keys per canonical selection, so the collision is invisible there
-- (2026-09-26: 0 in opticodds_mapping vs 687 crypto.com / 306 Underdog / 196
-- Kalshi canonicals with two keys in market_mapping, next 48h).
canons as (
  select lower(mm.sportsbook) as sb, {_CANON.format(t="mm", pts="points")} as canon,
    count(distinct {_SRC_KEY.format(t="mm")}) as n_keys,
    array_agg(distinct {_SRC_KEY.format(t="mm")} limit 3) as canon_src_keys
  from `{{project}}.markets_us.market_mapping` as mm
  where mm.start_date between timestamp_sub(current_timestamp(), interval {INPLAY_HOURS} hour)
                          and timestamp_add(current_timestamp(), interval {HORIZON_HOURS} hour)
    and lower(mm.sportsbook) in ({_venue_list(VENUES)})
  group by sb, canon
),"""  # nosec B608 — interpolands are module constants, not caller input

_PRICES = f"""
vp as (
  select lower(p.sportsbook) as sb, {_SRC_KEY.format(t="p")} as src_key, p.price as venue_price
  from `{{project}}.opticodds_us.opticodds_prices` as p
  where p.publish_time > timestamp_sub(current_timestamp(), interval {PRICE_WINDOW_MINUTES} minute)
    and lower(p.sportsbook) in ({_venue_list(PRICED_VENUES)})
    and p.source_ids is not null and p.price > 1
  qualify row_number() over (partition by sb, src_key order by p.publish_time desc) = 1
),
fp as (
  select {_CANON.format(t="f", pts="selection_points")} as canon, f.fair_price
  from `{{project}}.opticodds_us.parlay_fair_price_v2` as f
  where f.publish_time > timestamp_sub(current_timestamp(), interval {PRICE_WINDOW_MINUTES} minute)
    and not coalesce(f.removed, false) and not coalesce(f.fair_price_is_null, false)
    and f.fair_price > 1
  qualify row_number() over (partition by canon order by f.publish_time desc) = 1
),"""  # nosec B608 — interpolands are module constants, not caller input

_AI = f"""
ai as (
  select lower(a.sportsbook) as sb, a.game_id, a.market_id, a.exchange_ref,
    lower(coalesce(a.exchange_side, '')) as side,
    a.mapping_ok, a.fixture_ok, a.market_ok, a.side_ok, a.line_ok, a.entity_ok,
    a.reason as ai_reason, a.exchange_text
  from `{{project}}.markets_us.market_mapping_ai_validation` as a
  where a.start_date between timestamp_sub(current_timestamp(), interval {INPLAY_HOURS} hour)
                         and timestamp_add(current_timestamp(), interval {HORIZON_HOURS} hour)
  qualify row_number() over (
    partition by sb, a.game_id, a.market_id, a.exchange_ref, side
    order by a.validated_at desc) = 1
)"""  # nosec B608 — interpolands are module constants, not caller input

_SELECT = """
select
  m.* except (canon, market_key), m.canon,
  k.n_optic, k.n_ours, k.optic_canons, k.our_canons,
  c.n_keys as canon_keys, c.canon_src_keys,
  vp.venue_price, fp.fair_price,
  ai.mapping_ok as ai_ok, ai.fixture_ok as ai_fixture_ok, ai.market_ok as ai_market_ok,
  ai.side_ok as ai_side_ok, ai.line_ok as ai_line_ok, ai.entity_ok as ai_entity_ok,
  ai.ai_reason, ai.exchange_text
from m
join keys k using (sb, src_key)
left join canons c using (sb, canon)
left join vp using (sb, src_key)
left join fp using (canon)
left join ai
  on ai.sb = m.sb and ai.game_id = m.game_id and ai.market_id = m.market_id
  and ai.exchange_ref = case m.sb when 'crypto.com' then m.src_symbol
                                  when 'polymarket' then m.src_selection
                                  else m.src_market end
  -- Kalshi verdicts are per ticker side; the other venues' refs already name the selection.
  and (m.sb != 'kalshi' or ai.side = lower(coalesce(m.src_selection, '')))
where m.mapping_source != 'ORIGINAL' or m.is_rfq_winner
"""

MISMAP_SQL = "with" + _MAPPINGS + _PRICES + _AI + _SELECT  # nosec B608 — module constants only
