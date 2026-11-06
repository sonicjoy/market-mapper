"""Build optic_fixtures_odds.jsonl from BigQuery instead of the OpticOdds API.

Drop-in replacement for `python -m fetch.optic` for leagues whose fixtures are
not on the API-fetch subscription but whose streaming odds ARE in BigQuery
(opticodds_us.opticodds_fixtures + opticodds_us.opticodds_prices). Emits one
JSON line per fixture in the exact `mappers.exchanges.optic.Game` schema, so
`mappers.run` consumes it identically to the API-fetched file.

Odds source = opticodds_prices (the only BQ table carrying team_id/player_id,
which optic.build_rows requires). Deduped to the latest tick per
(fixture_id, market_id, selection, selection_line, points, team_id, player_id).
selection_line ("over"/"under") is taken verbatim from BQ — never reconstructed
— so there is no over/under flip risk introduced here. normalized_selection is
set to lower(selection) so game-scoped YES_NO (soccer BTTS) resolves via
build_rows' normalized_selection branch.

Usage:
    GCP_PROJECT=... python -m BigQuery.optic_from_bq <out_path> [--sport soccer]
"""
import argparse
import json
import os
import re
import sys

from google.cloud import bigquery

DEFAULT_SPORTS = ["soccer"]
# Poly combos reference the forward book; keep the window wide.
#
# WIN_FWD_HOURS is the FIXTURE forward window. At its 7d default it silently
# overrode every per-league OpticConfig.horizon_hours=24*60 in this route's
# league set, so no BQ-optic league ever mapped a fixture more than 7 days
# out however wide its own config was. Override with OPTIC_BQ_WIN_FWD_HOURS.
WIN_BACK_HOURS = int(os.environ.get("OPTIC_BQ_WIN_BACK_HOURS") or 36)
WIN_FWD_HOURS = int(os.environ.get("OPTIC_BQ_WIN_FWD_HOURS") or 24 * 7)
# Odds lookback is INDEPENDENT of the fixture window. A fixture N days out is
# priced by the live streaming book, so its latest tick is recent regardless
# of N — coupling the two would multiply the opticodds_prices scan (~1 GB per
# soccer-day) for no extra coverage. Defaults to the historical coupled value
# so behaviour is unchanged unless explicitly overridden.
ODDS_LOOKBACK_HOURS = int(
    os.environ.get("OPTIC_BQ_ODDS_LOOKBACK_HOURS") or (WIN_FWD_HOURS + WIN_BACK_HOURS)
)


def _client() -> bigquery.Client:
    return bigquery.Client(project=os.environ["GCP_PROJECT"])


def _fixtures_sql(project: str) -> str:
    return f"""
    SELECT id, game_id, start_date, status, is_live,
           home_competitors, away_competitors, sport, league,
           TO_JSON_STRING(source_ids) AS source_ids_json
    FROM `{project}.opticodds_us.opticodds_fixtures`
    WHERE LOWER(sport_id) IN UNNEST(@sports)
      AND start_date BETWEEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {WIN_BACK_HOURS} HOUR)
                         AND TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {WIN_FWD_HOURS} HOUR)
    """  # nosec B608 — @sports is a bound param; project + window ints are code-derived, no user input


def _odds_sql(project: str) -> str:
    return f"""
    WITH ranked AS (
      SELECT id, fixture_id, market_id, market, selection, selection_line,
             points, name, team_id, player_id, grouping_key,
             TO_JSON_STRING(source_ids) AS source_ids_json,
             ROW_NUMBER() OVER (
               PARTITION BY fixture_id, market_id, selection, selection_line,
                            CAST(points AS STRING), team_id, player_id
               ORDER BY publish_time DESC
             ) AS rn
      FROM `{project}.opticodds_us.opticodds_prices`
      WHERE LOWER(sport) IN UNNEST(@sports)
        AND publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(),
                                          INTERVAL {ODDS_LOOKBACK_HOURS} HOUR)
    )
    SELECT * FROM ranked WHERE rn = 1
    """  # nosec B608 — @sports is a bound param; project + window ints are code-derived, no user input


def _run(client, sql, sports):
    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("sports", "STRING", sports)]
    )
    return client.query(sql, job_config=cfg).result()


def _nz(v):
    """BQ empty string -> None (team_id/player_id/selection_line must be None, not '')."""
    return v if (v is not None and str(v) != "") else None


# Raw opticodds_prices carries a second, aggregate copy of some line/score
# selections with selection_line + points NULL and the whole thing crammed
# into `selection` as a lowercase slug ("under_8_5", "csd_defensa_y_justicia_4_2",
# "lewis_morgan_over_0_5"). The properly-formed rows (selection_line populated)
# always coexist, so these slugs are redundant duplicates — and optic.build_rows
# asserts on their NULL selection_line for TOTAL/OVER_UNDER/CORRECT_SCORE shapes,
# aborting the whole league. Display-name selections (moneyline teams, "Yes"/"No",
# "Draw", player names) never match this pattern, so legit selection_line-null
# markets (moneyline, BTTS, 3-way, goal-scorer) survive. We DROP, never parse the
# slug — reconstructing over/under from a string is the exact flip risk the
# verbatim-selection_line design avoids.
_ALT_SLUG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)+")


def _is_alt_slug(sel: str) -> bool:
    return bool(_ALT_SLUG.fullmatch(sel))


def _competitors(raw):
    out = []
    for c in (raw or []):
        name = (c.get("name") or "").strip()
        abbr = (c.get("abbreviation") or "").strip()
        # build_rows/_canonical_abbr raises on an empty abbreviation (some
        # lower-tier optic teams ship none). Fall back to name -> id.
        out.append({
            "id": c.get("id") or "",
            "abbreviation": abbr or name or (c.get("id") or ""),
            "name": name,
        })
    return out


def _odd_row(r) -> dict:
    """One optic-schema odd from a BQ prices row (selection_line verbatim)."""
    sel = r["selection"] or ""
    return {
        "id": r["id"] or f'{r["fixture_id"]}:{r["market_id"]}:{sel}:{r["selection_line"]}:{r["points"]}',
        "market": r["market"] or "",
        "market_id": r["market_id"] or "",
        "name": r["name"] or "",
        "selection": sel,
        "normalized_selection": sel.strip().lower(),
        "selection_line": _nz(r["selection_line"]),
        "points": r["points"],
        "team_id": _nz(r["team_id"]),
        "player_id": _nz(r["player_id"]),
        "grouping_key": r["grouping_key"] or "",
        "source_ids": (json.loads(r["source_ids_json"]) if r["source_ids_json"] else None) or {},
    }


def _load_odds(client, project: str, sports: list[str]) -> dict[str, list]:
    """Fetch deduped odds keyed by fixture_id, dropping alt-slug rows."""
    odds_by_fx: dict[str, list] = {}
    n_odds = n_dropped = 0
    for r in _run(client, _odds_sql(project), sports):
        fid = r["fixture_id"]
        if not fid:
            continue
        if _nz(r["selection_line"]) is None and _is_alt_slug(r["selection"] or ""):
            n_dropped += 1
            continue
        odds_by_fx.setdefault(fid, []).append(_odd_row(r))
        n_odds += 1
    print(f"[optic_from_bq] {n_odds} deduped odds across {len(odds_by_fx)} fixtures"
          f" ({n_dropped} alt-slug rows dropped)", file=sys.stderr)
    return odds_by_fx


def _game_row(r, odds: list) -> dict:
    """One optic-schema Game (fixture + its odds) from a BQ fixtures row."""
    lg = r["league"] or {}
    return {
        "id": r["id"],
        "game_id": r["game_id"],
        "start_date": r["start_date"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": r["status"] or "unplayed",
        "is_live": bool(r["is_live"]),
        "home_competitors": _competitors(r["home_competitors"]),
        "away_competitors": _competitors(r["away_competitors"]),
        "league": {"id": lg.get("id") or "", "name": lg.get("name") or ""},
        "odds": odds,
        "source_ids": (json.loads(r["source_ids_json"]) if r["source_ids_json"] else None) or {},
    }


def build(out_path: str, sports: list[str] = DEFAULT_SPORTS) -> None:
    project = os.environ["GCP_PROJECT"]
    sports = [s.lower() for s in sports]
    client = _client()
    print(f"[optic_from_bq] project={project} sports={sports}", file=sys.stderr)

    odds_by_fx = _load_odds(client, project, sports)

    n_written = 0
    with open(out_path, "w") as f:
        for r in _run(client, _fixtures_sql(project), sports):
            odds = odds_by_fx.get(r["id"], [])
            if not odds:
                continue
            f.write(json.dumps(_game_row(r, odds)) + "\n")
            n_written += 1
    print(f"[optic_from_bq] wrote {n_written} fixtures with odds -> {out_path}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out_path", help="Output optic_fixtures_odds.jsonl path")
    p.add_argument("--sport", nargs="+", default=DEFAULT_SPORTS,
                   help="One or more optic sports (default: soccer)")
    args = p.parse_args()
    build(args.out_path, args.sport)


if __name__ == "__main__":
    main()
