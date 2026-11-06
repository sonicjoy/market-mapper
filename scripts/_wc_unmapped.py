"""List unmapped World Cup fixtures and likely reasons."""

import json
import os
from collections import defaultdict
from pathlib import Path

from BigQuery.client import ro_client, ro_query

PROJECT = os.environ.get("GCP_PROJECT", "marketmaking-test")
DATA_DIR = Path("data/2026-06-15/09_27")

UNMAPPED_SQL = f"""
with wc_fixtures as (
  select
    game_id,
    start_date,
    home_team_display,
    away_team_display,
    status
  from `{PROJECT}.opticodds_us.opticodds_fixtures`
  where league.name = 'FIFA - World Cup'
    and date(start_date) between '2026-06-15' and '2026-06-25'
  qualify row_number() over (partition by game_id order by start_date desc) = 1
),
mapped as (
  select game_id, count(*) as mapping_rows
  from `{PROJECT}.markets_us.market_mapping`
  where league = 'world_cup'
    and date(start_date) between '2026-06-15' and '2026-06-25'
  group by 1
),
poly_prices as (
  select game_id, count(*) as poly_rows
  from `{PROJECT}.opticodds_us.prices_dedup_state`
  where league = 'FIFA - World Cup'
    and sportsbook = 'Polymarket'
    and date(start_date) between '2026-06-15' and '2026-06-25'
  group by 1
),
kalshi_prices as (
  select game_id, count(*) as kalshi_rows
  from `{PROJECT}.opticodds_us.prices_dedup_state`
  where league = 'FIFA - World Cup'
    and sportsbook = 'Kalshi'
    and date(start_date) between '2026-06-15' and '2026-06-25'
  group by 1
)
select
  o.start_date,
  o.home_team_display,
  o.away_team_display,
  o.status,
  o.game_id,
  m.mapping_rows,
  pp.poly_rows,
  kp.kalshi_rows,
  m.game_id is not null as mapped
from wc_fixtures o
left join mapped m using (game_id)
left join poly_prices pp using (game_id)
left join kalshi_prices kp using (game_id)
order by o.start_date
"""


def load_fetched_wc_games() -> dict[str, dict]:
    """game_id -> {home, away, start, has_poly, has_kalshi, mapping_lines}."""
    path = DATA_DIR / "optic_fixtures_odds.jsonl"
    if not path.exists():
        return {}
    games: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("league", {}).get("id") != "fifa_-_world_cup":
                continue
            gid = g["game_id"]
            poly = kalshi = 0
            for odd in g.get("odds", []):
                sb = odd.get("sportsbook") or ""
                src = odd.get("source_ids") or {}
                if sb == "Polymarket" and src:
                    poly += 1
                if sb == "Kalshi" and src:
                    kalshi += 1
            games[gid] = {
                "home": g["home_competitors"][0]["name"],
                "away": g["away_competitors"][0]["name"],
                "start": g["start_date"],
                "poly_odds": poly,
                "kalshi_odds": kalshi,
            }
    return games


def load_local_mappings() -> set[str]:
    path = DATA_DIR / "mappings.jsonl"
    if not path.exists():
        return set()
    gids: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("key", {}).get("league") != "world_cup":
                continue
            o = rec.get("optic_odds") or {}
            if o.get("game_id"):
                gids.add(o["game_id"])
    return gids


def kalshi_wc_events() -> dict[str, str]:
    """event_ticker suffix -> event_ticker for KXWCGAME."""
    path = DATA_DIR / "kalshi_markets.jsonl"
    events: dict[str, str] = {}
    if not path.exists():
        return events
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            et = r.get("event_ticker", "")
            # legacy: ticker parse — replace with the typed venue field, do not extend
            if et.startswith("KXWCGAME"):
                events[et] = et
    return events


def main() -> None:
    client = ro_client()
    all_rows = list(ro_query(client, UNMAPPED_SQL))
    unmapped = [r for r in all_rows if not r["mapped"]]
    mapped = [r for r in all_rows if r["mapped"]]
    fetched = load_fetched_wc_games()

    print(f"World Cup fixtures (Jun 15–25): {len(all_rows)} total, "
          f"{len(mapped)} mapped, {len(unmapped)} unmapped\n")

    if unmapped:
        print("UNMAPPED:")
        print(f"{'start':20} {'home':14} {'away':14} {'map':4} {'poly':4} {'kal':4} reason")
        print("-" * 110)

    for r in unmapped:
        gid = r["game_id"]
        reasons: list[str] = []

        if gid not in fetched:
            reasons.append("outside fetch horizon (96h from 2026-06-15 09:27 UTC)")
        else:
            fx = fetched[gid]
            if fx["poly_odds"] == 0 and fx["kalshi_odds"] == 0:
                reasons.append("no exchange source_ids in fetched Optic odds")
            if fx["poly_odds"] == 0:
                reasons.append("no Polymarket source_ids in fetch")
            if fx["kalshi_odds"] == 0:
                reasons.append("no Kalshi source_ids in fetch")

        if r["poly_rows"] is None and r["kalshi_rows"] is None:
            reasons.append("no Polymarket/Kalshi in prices_dedup_state")
        elif r["poly_rows"] is None:
            reasons.append("no Polymarket in prices_dedup_state")

        if r["status"] in ("completed", "cancelled"):
            reasons.append(f"status={r['status']}")

        if not reasons:
            reasons.append("has prices in BQ — investigate mapper/load")

        print(
            f"{str(r['start_date'])[:16]:20} "
            f"{r['home_team_display'][:14]:14} "
            f"{r['away_team_display'][:14]:14} "
            f"{'N':4} "
            f"{r['poly_rows'] or 0:4} "
            f"{r['kalshi_rows'] or 0:4} "
            f"{'; '.join(reasons)}"
        )
        print(f"  game_id: {gid}")

    print("\nMAPPED (summary):")
    for r in mapped:
        print(
            f"  {str(r['start_date'])[:16]}  {r['home_team_display']} vs "
            f"{r['away_team_display']}  rows={r['mapping_rows']}  "
            f"poly_prices={r['poly_rows'] or 0}"
        )


def main_next7() -> None:
    """Next-7-day view: fixture mapping + Polymarket-specific gaps."""
    client = ro_client()
    sql = f"""
    with wc as (
      select game_id, start_date, home_team_display, away_team_display, status
      from `{PROJECT}.opticodds_us.opticodds_fixtures`
      where league.name = 'FIFA - World Cup'
        and start_date between current_timestamp()
          and timestamp_add(current_timestamp(), interval 7 day)
      qualify row_number() over (partition by game_id order by start_date desc) = 1
    ),
    mapped as (
      select game_id,
        countif(sportsbook = 'Polymarket') as poly_map_rows,
        countif(sportsbook = 'Kalshi') as kalshi_map_rows,
        count(*) as total_rows
      from `{PROJECT}.markets_us.market_mapping`
      where league = 'world_cup'
        and date(start_date) between current_date()
          and date_add(current_date(), interval 7 day)
      group by 1
    ),
    poly_price as (
      select distinct game_id
      from `{PROJECT}.opticodds_us.prices_dedup_state`
      where sportsbook = 'Polymarket' and league = 'FIFA - World Cup'
        and start_date between current_timestamp()
          and timestamp_add(current_timestamp(), interval 7 day)
    )
    select w.start_date, w.home_team_display, w.away_team_display, w.status,
      w.game_id, m.total_rows, m.poly_map_rows, m.kalshi_map_rows,
      pp.game_id is not null as has_poly_prices,
      m.game_id is not null as any_mapped
    from wc w
    left join mapped m using (game_id)
    left join poly_price pp using (game_id)
    order by w.start_date
    """
    rows = list(ro_query(client, sql))
    fetched = load_fetched_wc_games()
    unmapped = [r for r in rows if not r["any_mapped"]]
    no_poly = [r for r in rows if r["any_mapped"] and (r["poly_map_rows"] or 0) == 0]
    poly_gap = [r for r in rows if r["has_poly_prices"] and (r["poly_map_rows"] or 0) == 0]

    print(f"WC next 7 days: {len(rows)} fixtures")
    print(f"  unmapped entirely: {len(unmapped)}")
    print(f"  mapped but no Polymarket rows: {len(no_poly)}")
    print(f"  Polymarket prices in Optic but no Polymarket mapping: {len(poly_gap)}\n")

    def explain(r, kind):
        gid = r["game_id"]
        reasons = []
        if kind == "unmapped":
            if gid not in fetched:
                reasons.append(
                    "outside 96h Optic fetch window at last run "
                    f"(fetched {len(fetched)} games on 2026-06-15)"
                )
            else:
                fx = fetched[gid]
                if fx["poly_odds"] + fx["kalshi_odds"] == 0:
                    reasons.append("no Kalshi/Polymarket source_ids in fetch")
            if not r["has_poly_prices"]:
                reasons.append("no Polymarket in prices_dedup_state")
            if r["status"] == "completed":
                reasons.append("match completed")
        if kind == "no_poly_map":
            if r["has_poly_prices"]:
                reasons.append(
                    "Optic has Polymarket prices but load used odds "
                    "without source_ids, or not re-loaded after fetch"
                )
            else:
                reasons.append("no Polymarket prices in prices_dedup_state")
            if (r["kalshi_map_rows"] or 0) > 0:
                reasons.append("Kalshi-only mapping present")
        if not reasons:
            reasons.append("needs investigation")
        return "; ".join(reasons)

    for label, items, kind in [
        ("UNMAPPED", unmapped, "unmapped"),
        ("NO POLYMARKET ROWS (but mapped)", no_poly, "no_poly_map"),
        ("POLY PRICES BUT NO POLY MAP", poly_gap, "no_poly_map"),
    ]:
        if not items:
            continue
        print(label + ":")
        for r in items:
            print(
                f"  {str(r['start_date'])[:16]}  {r['home_team_display']} vs "
                f"{r['away_team_display']}  ({explain(r, kind)})"
            )
            print(f"    game_id: {r['game_id']}")
        print()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--next7":
        main_next7()
    else:
        main()
