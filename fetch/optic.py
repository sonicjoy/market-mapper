import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from time import sleep

import requests

from fetch.gcloud_util import gcloud_cmd
from fetch.tip import optic_api_key_secret, supported_optic_leagues
from mappers.exchanges.optic import (
    EXCHANGE_SOURCE_ID_SPORTSBOOKS,
    PREDICTION_MARKET_SPORTSBOOK_IDS,
    OpticConfig,
)
from mappers.shared import FIXTURE_HORIZON_HOURS

BASE_URL = "https://api.opticodds.com/api/v3/"
GCP_PROJECT = os.environ["GCP_PROJECT"]
# requests with no timeout hung fetch.optic for days on a stalled
# Cloudflare/Optic TLS read (test VM, 2026-08-14..18).
GET_TIMEOUT = 60
# Optic 500 on sweden_-_damallsvenskan aborted the whole test tick
# (2026-09-04). 502-504 were already retried; 500 is the same class.
_RETRYABLE_HTTP = frozenset({500, 502, 503, 504})
# Truncated chunked bodies (test 2026-09-10) are the same class as a
# dropped TLS socket: retry, then skip the league/fixture.
_RETRYABLE_TRANSPORT = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Optic coverage: python registry + legacy tip overlay (tip is retiring).
SUPPORTED_LEAGUES: dict[str, OpticConfig] = supported_optic_leagues()

_headers_cache: dict[str, dict[str, str]] = {}


def init_headers(league: str) -> dict[str, str]:
    secret = optic_api_key_secret(league)
    if secret not in _headers_cache:
        _headers_cache[secret] = _init_headers(secret)
    return _headers_cache[secret]


def optic_config_for(league: str) -> OpticConfig | None:
    """Resolved OpticConfig for a league slug, or None when unknown."""
    return SUPPORTED_LEAGUES.get(league)


def _init_headers(secret: str):
    api_key = subprocess.check_output(
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            f"--secret={secret}", f"--project={GCP_PROJECT}",
        ),
        text=True,
    ).strip()
    return {
        "accept": "application/json",
        "X-Api-Key": api_key,
    }


def _optic_get(url, headers, params):
    """GET with timeout; retry transient transport errors."""
    attempts = 0
    while True:
        try:
            return requests.get(
                url, params, headers=headers, timeout=GET_TIMEOUT)
        except _RETRYABLE_TRANSPORT as exc:
            # Transient TLS/socket drops (prod 2026-08-11), stalled
            # reads with no timeout (test 2026-08-14..18), and
            # truncated chunked bodies (test 2026-09-10) used to abort
            # or freeze every league's mapping for that tick.
            attempts += 1
            if attempts > 3:
                raise
            backoff = 2 ** attempts
            print(f"  Request error from upstream ({exc}), "
                  f"retrying in {backoff}s (attempt {attempts}/3)...")
            sleep(backoff)


def _retryable_upstream(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE_TRANSPORT):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = exc.response
        return resp is not None and resp.status_code in _RETRYABLE_HTTP
    return False


def get_optic(url, headers, params=None):
    params = deepcopy(params) if params else {}
    datas = []
    page = 1
    server_error_attempts = 0
    while True:
        params["page"] = str(page)
        response = _optic_get(url, headers, params)
        if response.status_code == 429:
            print("  Rate limited, retrying in 5s...")
            sleep(5)
            continue
        if response.status_code in _RETRYABLE_HTTP:
            server_error_attempts += 1
            if server_error_attempts > 3:
                response.raise_for_status()
            backoff = 2 ** server_error_attempts
            print(f"  {response.status_code} from upstream, "
                  f"retrying in {backoff}s "
                  f"(attempt {server_error_attempts}/3)...")
            sleep(backoff)
            continue
        response.raise_for_status()
        data = response.json()
        datas += data["data"]
        # cutover to using has_more: March 10 at 5pm ET
        if "has_more" in data:
            if not data["has_more"]:
                break
        elif data.get("total_pages", 1) <= page:
            break
        page += 1
    return datas


# Each batch is one API request (max 5 sportsbooks per request).
# Batch 1 must include kalshi and prophet_x so the pipeline can
# cross-check mappings against their Optic source_ids.
# NOTE WELL, Nick says these are not the optimal set for getting
# the most complete PX coverage, so see him or investigate further
# before taking the below as optimal.  And I have commented out the
# last two rows to speed things up for now.
_SPORTSBOOKS_PER_REQUEST = 5


def _chunk_sportsbooks(ids: tuple[str, ...] | list[str]) -> list[list[str]]:
    """Split sportsbook ids into Optic request batches of at most 5."""
    items = list(ids)
    return [
        items[i:i + _SPORTSBOOKS_PER_REQUEST]
        for i in range(0, len(items), _SPORTSBOOKS_PER_REQUEST)
    ]


SPORTSBOOK_BATCHES = [
    ["kalshi", "prophet_x", "draftkings", "fanatics", "betmgm"],
    ["betano", "fanduel", "hard_rock", "betfair_exchange", "unibet"],
    *_chunk_sportsbooks(PREDICTION_MARKET_SPORTSBOOK_IDS),
    # ["bodog", "888sport", "bc_game", "dafabet"],
    # ["pinnacle", "bwin", "sbobet", "robinhood", "4cx"],
]

# Darts is priced by none of the books above but Unibet; these price PDC and
# MODUS moneylines on Optic (checked 2026-10-16). Fetched for darts only.
DARTS_SPORTSBOOK_BATCH = ["betway", "betsson", "betsafe", "rizk", "midnite"]

# Soccer 1st-half first team to score is priced only by these books, none in
# the batches above (checked 2026-10-19, La Liga + UCL fixtures). Asked for
# that one market and for soccer only, so no other soccer row changes.
SOCCER_1H_FTTS_BATCH = (
    ["pinnacle", "bwin", "dafabet", "ladbrokes"], "1st_half_first_team_to_score",
)

# NBA race to 30 points is priced only by these books, none in the batches
# above (checked 2026-10-23: boomers and superbet on 12/12 priced UDX games).
# Asked for that one market and for the NBA only. Off unless
# OPTIC_NBA_RACE_TO_30=1: its rows also map Poly US and Kalshi race-30 legs.
NBA_RACE_TO_30_BATCH = (
    ["boomers", "superbet", "rivalry", "playdoit", "spinbet"], "race_to_30_points",
)


def _nba_race_to_30_on() -> bool:
    return os.environ.get("OPTIC_NBA_RACE_TO_30", "").strip() == "1"

VOLATILE_FIELDS = ["is_main", "price", "timestamp", "limits", "order_book"]
# Kept on crypto.com odds so Optic vs FIX stamp conflicts can use
# latest-wins (Optic odd timestamp vs FIX catalogue publish_time).
_CRYPTO_KEEP_FIELDS = ("timestamp",)


def clean_odds(o1, o2, competitor_names=()):
    """Merge two odds entries for the same market.
    Values must be identical; if not, keep the longer one.
    Same-length strings that differ only by case keep the fixture
    competitor spelling. Assert on any other same-length mismatch.

    Refactored from Nick's notebook; verified output matches on 3 NCAAB
    fixtures via scripts/test_clean_odds.py (2026-03-06).
    """
    assert o1.keys() == o2.keys()
    output = {}
    conflicts = {}
    for k, v1 in o1.items():
        v2 = o2[k]
        if v1 == v2 or len(v1) > len(v2):
            v = v1
        elif len(v2) > len(v1):
            v = v2
        elif _case_only_strings(v1, v2):
            v = _prefer_fixture_spelling(v1, competitor_names)
            conflicts[k] = v
        else:
            raise AssertionError((k, v1, v2))
        output[k] = v
    return output, conflicts


def strip_odds_entry(entry):
    """Remove sportsbook from ID and drop volatile fields.
    Returns (clean entry, sportsbook name, source_ids).
    """
    entry = deepcopy(entry)

    # ID format: game_id:sportsbook:market_id:selection
    parts = entry["id"].split(":")
    del parts[1]
    entry["id"] = ":".join(parts)

    sportsbook = entry.get("sportsbook")
    kept = {
        field: entry[field]
        for field in _CRYPTO_KEEP_FIELDS
        if sportsbook == "crypto.com" and field in entry
    }
    for field in VOLATILE_FIELDS:
        entry.pop(field, None)
    entry.pop("deep_link", None)
    entry.update(kept)

    sportsbook = entry.pop("sportsbook")
    source_ids = entry.pop("source_ids")

    return entry, sportsbook, source_ids


def _merge_odds_across_books(stripped, existing, competitor_ids, competitor_names):
    """Merge two stripped odds rows; arbitrate timestamp/team_id/labels."""
    ts_a = stripped.pop("timestamp", None)
    ts_b = existing.pop("timestamp", None)
    team_a = stripped.pop("team_id", None)
    team_b = existing.pop("team_id", None)
    merged, label_conflicts = clean_odds(
        stripped, existing, competitor_names)
    kept_ts = _prefer_timestamp(ts_a, ts_b)
    if kept_ts is not None:
        merged["timestamp"] = kept_ts
    kept_team = _prefer_team_id(team_a, team_b, competitor_ids)
    if kept_team is not None:
        merged["team_id"] = kept_team
    return merged, _conflict_if_differ(team_a, team_b, kept_team), label_conflicts


def deduplicate_odds(
        odds,
        competitor_ids=frozenset(),
        competitor_names=(),
):
    """Merge odds entries across sportsbooks by clean_id.

    Collects source_ids from exchange sportsbooks (Kalshi, Prophet X,
    Polymarket, Novig, Polymarket (USA), crypto.com) for downstream mapping.
    """
    odds_map = {}
    conflicting_team_ids = {}
    conflicting_labels = {}
    for entry in odds:
        stripped, sportsbook, source_ids = strip_odds_entry(entry)
        clean_id = stripped["id"]

        existing = odds_map.get(clean_id, stripped)
        accumulated_source_ids = existing.pop("source_ids", {})
        merged, conflicting_team, label_conflicts = _merge_odds_across_books(
            stripped, existing, competitor_ids, competitor_names)
        if conflicting_team is not None:
            conflicting_team_ids[clean_id] = conflicting_team
        for kind, kept in label_conflicts.items():
            conflicting_labels.setdefault(kind, {})[clean_id] = kept
        merged["source_ids"] = accumulated_source_ids
        odds_map[clean_id] = merged

        assert sportsbook not in accumulated_source_ids
        if sportsbook in EXCHANGE_SOURCE_ID_SPORTSBOOKS and source_ids:
            accumulated_source_ids[sportsbook] = source_ids

    _log_duplicate_fields("team_id", conflicting_team_ids)
    for kind, kept_by_id in conflicting_labels.items():
        _log_duplicate_fields(kind, kept_by_id)
    return list(odds_map.values())


def _conflict_if_differ(a, b, kept):
    if kept is not None and None not in (a, b) and a != b:
        return kept
    return None


def _log_duplicate_fields(kind, kept_by_id):
    for clean_id, kept in kept_by_id.items():
        print(
            f"optic [{clean_id}]: dropped duplicate {kind}, "
            f"kept fixture competitor {kept}")


def _prefer_timestamp(a, b):
    """Keep the later numeric timestamp when both present."""
    if a is None:
        return b
    if b is None:
        return a
    try:
        return a if float(a) >= float(b) else b
    except (TypeError, ValueError):
        return a


def _case_only_strings(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.casefold() == b.casefold()


def _prefer_fixture_spelling(value, competitor_names):
    """Keep the fixture competitor spelling for a case-only label clash.

    Optic tennis books hit this on 2026-08-27 on both `name` (Kenny de
    Schepper) and `selection` (Andrea de Marchi).  Same length, so the
    longer-wins rule cannot merge them.  The fixture competitor list is
    the authority, same as _prefer_team_id.
    """
    by_fold = {name.casefold(): name for name in competitor_names}
    return by_fold.get(value.casefold(), value)


def _prefer_team_id(a, b, competitor_ids):
    """Keep the team_id that belongs to the fixture.

    Optic can quote one selection under two different competitor ids
    depending on the sportsbook, one of them a duplicate entity that is
    not in the fixture at all — six of nine books did this to Marina
    Spasic on UFC fixture 20260801BA4BBFF1 (2026-07-29), which
    clean_odds cannot merge because the ids are the same length.  The
    fixture's competitor list is the only authority: the mapper
    resolves sides through team_map, built from those competitors, and
    a majority vote picks the duplicate when most books carry it.
    """
    if b is None or a == b:
        return a
    if a is None:
        return b
    known = [team_id for team_id in (a, b) if team_id in competitor_ids]
    if len(known) != 1:
        raise AssertionError(("team_id", a, b))
    return known[0]


def process_fixture(fixture_odds):
    """Strip volatile fields and deduplicate odds across sportsbooks."""
    fixture_odds = deepcopy(fixture_odds)
    fixture_odds["odds"] = deduplicate_odds(
        fixture_odds["odds"],
        fixture_competitor_ids(fixture_odds),
        fixture_competitor_names(fixture_odds),
    )
    return fixture_odds


def fixture_competitor_ids(fixture) -> frozenset[str]:
    """The fixture's own competitor ids — see _prefer_team_id."""
    return frozenset(
        competitor["id"]
        for side in ("home_competitors", "away_competitors")
        for competitor in fixture.get(side) or ()
        if competitor.get("id")
    )


def fixture_competitor_names(fixture) -> tuple[str, ...]:
    """The fixture's own competitor names — see _prefer_name."""
    return tuple(
        competitor["name"]
        for side in ("home_competitors", "away_competitors")
        for competitor in fixture.get(side) or ()
        if competitor.get("name")
    )


# Restrict to active fixtures starting within the next horizon_hours
# (default FIXTURE_HORIZON_HOURS).  The override exists for testing
# leagues whose fixtures haven't entered the production horizon yet —
# e.g. the World Cup group stage before kickoff week.
def get_fixtures(headers, league, horizon_hours=None):
    if horizon_hours is None:
        horizon_hours = FIXTURE_HORIZON_HOURS
    cutoff = datetime.now(UTC) + timedelta(hours=horizon_hours)
    start_date_before = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    # include_sportradar_id surfaces source_ids.sportradar_id on each
    # fixture (e.g. "sr:fixture:66456904").  This is the exact event
    # join Huddle uses (its betradar.event.extId == this trailing
    # integer) — see docs/adding-huddle.md.  NB the flag only works on
    # /fixtures/active; /fixtures/odds carries no fixture-level
    # source_ids even with it set (verified 2026-06-07), so main()
    # carries the id over from the active-list fixture onto the
    # persisted odds record.
    return get_optic(
        BASE_URL + "fixtures/active", headers,
        {"league": league, "start_date_before": start_date_before,
         "include_sportradar_id": "true"},
    )


def get_fixtures_or_skip(headers, league, horizon_hours=None):
    """Active fixtures, or None when Optic is down for this league.

    One league's 500 must not abort fetch.optic (test 2026-09-04,
    sweden_-_damallsvenskan): the module is REQUIRED, so a raise unmaps
    every other league on that tick.
    """
    try:
        return get_fixtures(headers, league, horizon_hours)
    except requests.exceptions.RequestException as exc:
        if not _retryable_upstream(exc):
            raise
        return None


def get_fixture_odds(headers, fixture_id, extra_batches=()):
    combined_odds = []
    fixture_data = None
    for i, batch in enumerate([*SPORTSBOOK_BATCHES, *extra_batches]):
        if i > 0:
            sleep(0.2)
        # An extra batch is a book list, or (book list, one market id).
        batch, market = batch if isinstance(batch, tuple) else (batch, None)
        params = {"fixture_id": fixture_id}
        if market:
            params["market"] = market
        for sb in batch:
            params.setdefault("sportsbook", []).append(sb)
        result = get_optic(BASE_URL + "fixtures/odds", headers, params)
        assert len(result) == 1
        if fixture_data is None:
            fixture_data = result[0]
        combined_odds.extend(result[0]["odds"])
    assert fixture_data is not None
    fixture_data["odds"] = combined_odds
    return fixture_data


def fetch_processed_fixture(headers, fixture):
    """Fetch and clean one fixture's odds; None if its data is unusable.

    Optic data faults are per-fixture (conflicting competitor ids on one
    selection, a fixture that leaves the active set mid-run).  Losing
    one fixture is worth far more than losing the run: fetch.optic is
    REQUIRED, so raising here means no league gets mapped at all, which
    is what a single bad UFC fight did for five ticks on 2026-07-29.
    """
    fixture_id = fixture["id"]
    try:
        sport = fixture.get("sport")
        sport = sport.get("id") if isinstance(sport, dict) else sport
        league = fixture.get("league")
        league = league.get("id") if isinstance(league, dict) else league
        extra = {"darts": [DARTS_SPORTSBOOK_BATCH],
                 "soccer": [SOCCER_1H_FTTS_BATCH]}.get(str(sport), [])
        if league == "nba" and _nba_race_to_30_on():
            extra = [*extra, NBA_RACE_TO_30_BATCH]
        processed = process_fixture(get_fixture_odds(headers, fixture_id, extra))
    except (AssertionError, requests.exceptions.RequestException) as exc:
        if not (isinstance(exc, AssertionError) or _retryable_upstream(exc)):
            raise
        kind = ("unusable data" if isinstance(exc, AssertionError)
                else "upstream error")
        print(f"ALERT: skipping optic fixture {fixture_id} — {kind}: {exc}")
        return None
    # The /fixtures/odds endpoint drops fixture-level source_ids, so
    # carry the sportradar id over from the active-list fixture (fetched
    # with include_sportradar_id=true).  This is purely additive — the
    # odds record has no top-level source_ids of its own.
    processed["source_ids"] = fixture.get("source_ids") or {}
    return processed


# Bounded parallelism for per-fixture /fixtures/odds fan-out.  Serial
# fetching of ~50 leagues made the main pipeline ~40 min; workers cut
# wall time while existing 429 backoff + inter-batch sleeps stay intact.
# Override with OPTIC_FIXTURE_WORKERS when tuning against rate limits.
DEFAULT_FIXTURE_WORKERS = 8


def _fixture_workers() -> int:
    raw = os.environ.get("OPTIC_FIXTURE_WORKERS", "").strip()
    if not raw:
        return DEFAULT_FIXTURE_WORKERS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_FIXTURE_WORKERS


def fetch_fixtures_parallel(headers, fixtures, *, workers: int | None = None):
    """Fetch/clean fixtures with a bounded thread pool.

    Returns (results, skipped_count).  Each worker keeps the per-fixture
    trailing sleep so we do not remove pacing — only overlap it across
    fixtures.  Results are collected via as_completed (no shared list
    mutation from workers).
    """
    if not fixtures:
        return [], 0
    n_workers = workers if workers is not None else _fixture_workers()
    n_workers = max(1, min(n_workers, len(fixtures)))

    def _one(indexed):
        i, fixture = indexed
        print(f"  [{i}/{len(fixtures)}] {fixture['id']}")
        processed = fetch_processed_fixture(headers, fixture)
        sleep(0.2)
        return processed

    results = []
    skipped = 0
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = [pool.submit(_one, item) for item in enumerate(fixtures, 1)]
        for fut in as_completed(futs):
            processed = fut.result()
            if processed is None:
                skipped += 1
            else:
                results.append(processed)
    return results, skipped


def main():
    league_names = ", ".join(sorted(SUPPORTED_LEAGUES))
    parser = argparse.ArgumentParser(
        description="Fetch fixture odds from OpticOdds.",
    )
    parser.add_argument(
        "--league", nargs="+",
        help=f"Leagues to fetch (tip-only slugs ok when SoT=bq). "
             f"Wired: {league_names}",
    )
    parser.add_argument(
        "--max-items", type=int,
        help="Max fixtures to fetch odds for (for smoke testing)",
    )
    parser.add_argument(
        "--horizon-hours", type=float,
        help="Override the fixture horizon (default: "
             f"{FIXTURE_HORIZON_HOURS}h) — for testing leagues whose "
             "fixtures are further out",
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory (written by orchestrator)",
    )
    args = parser.parse_args()

    if not args.league:
        parser.error("--league is required for fetching")
    if not args.out_dir:
        parser.error("--out-dir is required for fetching")

    results = []
    skipped = 0
    skipped_leagues = 0
    for league in args.league:
        cfg = optic_config_for(league)
        if cfg is None:
            print(
                f"FATAL: unknown league {league!r} (not in tip / run set)",
                file=sys.stderr,
            )
            sys.exit(1)
        headers = init_headers(league)
        horizon = (args.horizon_hours if args.horizon_hours is not None
                   else cfg.horizon_hours)
        # A list value encodes as repeated league params, which the
        # endpoint accepts — one request covers the league and any
        # extra_league_ids (see OpticConfig.extra_league_ids).
        fixtures = get_fixtures_or_skip(
            headers, [cfg.league_id, *cfg.extra_league_ids], horizon)
        if fixtures is None:
            print(f"ALERT: skipping optic league {league} — upstream error")
            skipped_leagues += 1
            continue
        print(f"{league}: {len(fixtures)} fixtures")

        if args.max_items:
            fixtures = fixtures[:args.max_items]
        if fixtures:
            print(f"  fetching with {_fixture_workers()} workers")
        league_results, league_skipped = fetch_fixtures_parallel(
            headers, fixtures)
        results.extend(league_results)
        skipped += league_skipped

    if skipped_leagues:
        print(f"ALERT: skipped {skipped_leagues} optic league(s) "
              f"due to upstream errors")
    if skipped:
        print(f"ALERT: skipped {skipped} optic fixture(s) with unusable data")
    if (skipped or skipped_leagues) and not results:
        print("FATAL: every optic fixture was unusable", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "optic_fixtures_odds.jsonl")
    with open(out_path, "w") as f:
        for result in results:
            print(json.dumps(result), file=f)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
