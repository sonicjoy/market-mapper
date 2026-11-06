"""Top confirmed Kalshi RFQs by payout.

Joins confirmed RFQs against OpticOdds fixtures to build a
human-readable leg summary and classifies each RFQ as SGP
(same-game parlay) or UNC (uncorrelated — all legs on different
fixtures).

Usage:
    python BigQuery/scripts/top-payouts.py
    python BigQuery/scripts/top-payouts.py --minutes 120 --limit 20
    python BigQuery/scripts/top-payouts.py --dry-run
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")
from BigQuery.client import ro_client, ro_query

QUERY = """\
WITH confirmed AS (
  SELECT *
  FROM `rs-marketmaking.reporting_us.rfq_latest`
  WHERE platform = "kalshi"
    AND status = "confirmed"
    AND first_publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {minutes} MINUTE)
),
latest_fixtures AS (
  SELECT * FROM `rs-marketmaking.opticodds_us.opticodds_fixtures`
  WHERE start_date > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY publish_time DESC) = 1
),
legs_with_fixtures AS (
  SELECT
    rfq.external_rfq_id,
    STRING_AGG(
      CONCAT(
        COALESCE(f.home_team_display, "?"), " v ", COALESCE(f.away_team_display, "?"),
        ": ", leg.selection, " ", leg.market,
        IFNULL(CONCAT(" ", CAST(leg.line AS STRING)), ""),
        " (", IFNULL(leg.side_id, "yes"), ")"
      ),
      " + "
    ) AS Leg_Summary,
    IF(COUNT(leg.optic_fixture_id) = COUNT(DISTINCT leg.optic_fixture_id),
       "UNC", "SGP") AS Type
  FROM confirmed rfq,
  UNNEST(rfq.legs) AS leg
  LEFT JOIN latest_fixtures f ON leg.optic_fixture_id = f.id
  GROUP BY rfq.external_rfq_id
)
SELECT
  FORMAT_TIMESTAMP("%Y-%m-%d %H:%M:%S", rfq.publish_time) AS Time,
  rfq.external_rfq_id AS RFQ_ID,
  lf.Type,
  rfq.num_of_legs AS Legs,
  lf.Leg_Summary,
  ROUND(rfq.requested_stake, 2) AS Stake,
  ROUND(rfq.best_price, 4) AS Fair_Price,
  ROUND(rfq.offer_price, 4) AS Offer_Price,
  ROUND(rfq.requested_stake * rfq.offer_price, 2) AS Payout,
  ROUND(1 - rfq.offer_price / rfq.best_price, 4) AS Edge,
  ROUND(rfq.requested_stake * (1 - rfq.offer_price / rfq.best_price), 2) AS EV
FROM confirmed rfq
LEFT JOIN legs_with_fixtures lf ON rfq.external_rfq_id = lf.external_rfq_id
ORDER BY Payout DESC
LIMIT {limit}
"""


def format_row(i: int, row: dict) -> str:
    """Format a single RFQ as a compact multiline block."""
    lines = [
        f"#{i}  {row['RFQ_ID']}  {row['Time']}  {row['Type']}  {row['Legs']}L"
        f"  stake=${row['Stake']:,.2f}  fair={row['Fair_Price']:.4f}"
        f"  offer={row['Offer_Price']:.4f}  payout=${row['Payout']:,.2f}"
        f"  edge={row['Edge'] * 100:.1f}%  ev=${row['EV']:,.2f}",
    ]
    # Split the " + "-delimited leg summary into one line per leg.
    leg_summary = row["Leg_Summary"] or ""
    for leg in leg_summary.split(" + "):
        if leg:
            lines.append(f"    {leg}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Top confirmed Kalshi RFQs by payout.")
    parser.add_argument(
        "--minutes", type=int, default=360,
        help="Lookback window in minutes (default: 360)")
    parser.add_argument(
        "--limit", type=int, default=10,
        help="Number of results (default: 10)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the query without executing")
    args = parser.parse_args()

    sql = QUERY.format(minutes=args.minutes, limit=args.limit)

    if args.dry_run:
        print(sql)
        return

    client = ro_client()
    rows = ro_query(client, sql)
    for i, row in enumerate(rows, 1):
        print(format_row(i, dict(row)))
        print()


if __name__ == "__main__":
    main()
