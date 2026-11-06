"""Fetch the DKEX (DraftKings Exchange) market catalogue.

Usage:
    python -m fetch.dkex --out-dir data/2026-09-15/12_00
    python -m fetch.dkex --source reports --out-dir data/... # dev seed only

Writes ``dkex_markets.jsonl`` -- one row per DKEX market symbol, in the
same shape whichever source produced it, so the mapper never learns which
one ran.

Two sources, and the distinction matters:

``api`` (the default, and the only production path)
    The venue's own REST catalogue: ``GET /api/v1/markets`` then
    ``POST /api/v1/markets/queries`` for singles.  Combos are filtered
    out of ``/markets``; ``--combos`` pages ``GET /api/v1/combos`` and
    fills legs with ``POST /api/v1/combos/queries``.  Both list calls
    page with ``limit`` (500 default, 1000 max) and an opaque ``cursor``
    taken from the previous response's ``nextCursor``.  This is live: it
    is the only source that sees a market on the day it opens, and the
    only one that can ever carry in-play state.

``reports`` (development seed, NOT for production mapping)
    The public daily CSV reports at ``railbirdexchange.com/reports`` --
    unauthenticated, but **T+1**: the file for business date D lands after
    D closes, so the catalogue it describes is up to a day stale and never
    contains a market created today.  It is in here because it is what we
    could seed the test table from before the venue issued API access, and
    it stays useful for backfill and for regression fixtures.  It refuses
    to run without ``--source reports`` so it is never the accidental
    default.  A report row carries only the symbol: its typed identity
    fields (``stat_achievement``, ``competition_id``, ``participants``,
    ...) are left None rather than parsed out of the ticker, so the
    mapper counts such rows as ``untyped`` and skips them.  The reports
    source seeds the raw table; it does not feed the mapper.

Market identity comes from the typed REST fields, never from the ticker.
The ticker is an opaque id and is never inspected, not even at discovery:
every listed ticker goes to the markets batch, which returns singles and
lists anything else under ``missingTickers``.  A combo is recognised by
its typed ``marketProductTypeName`` / ``legs``.

The prod and staging catalogues are unauthenticated.
``DKEX_API_BASE`` defaults to prod, ``https://api.railbirdexchange.com``;
set it to ``STAGING_API_BASE`` for the staging catalogue.
A key is sent only when ``DKEX_API_KEY`` is set, or when
``DKEX_USE_API_KEY_SECRET=1`` reads ``dkex_api_key`` from Secret Manager.
"""

import argparse
import csv
import io
import json
import os
import subprocess  # nosec B404 — gcloud secret read, the repo-wide pattern (fetch/novig.py)
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import requests

from fetch.dkex_api import (
    fetch_combo_metadata,
    fetch_market_metadata,
    fetch_single_market,
    page_combos,
    page_market_tickers,
)
from fetch.gcloud_util import gcloud_cmd
from mappers.exchanges.dkex import SETTLEMENT_LAG, is_combo

# --- API source -------------------------------------------------------

#: Prod catalogue (verified 2026-10-02: same endpoints and row shape as
#: staging, no key). DKEX_API_BASE overrides it, e.g. with STAGING_API_BASE.
API_BASE_ENV = "DKEX_API_BASE"
PROD_API_BASE = "https://api.railbirdexchange.com"
STAGING_API_BASE = "https://api.staging.railbirdexchange.com"
#: Set to 1 to read API_KEY_SECRET from Secret Manager. Neither env needs a key.
USE_API_KEY_SECRET_ENV = "DKEX_USE_API_KEY_SECRET"  # nosec B105
#: Secret Manager id holding the REST credential (shape TBC with venue).
#: nosec B105 — this is the name of a Secret Manager entry, not a credential.
API_KEY_SECRET = "dkex_api_key"  # nosec B105
#: Header the credential is sent in; overridable because the venue has
#: not published the scheme yet.
API_KEY_HEADER_ENV = "DKEX_API_KEY_HEADER"
DEFAULT_API_KEY_HEADER = "X-API-Key"
MAX_TRIES = 3
#: Set to 1 to GET each ticker the markets batch reports under
#: ``missingTickers`` (DK batch bug: NCAAB-WIN-* is listed but never returned).
MISSING_SINGLE_FALLBACK_ENV = "DKEX_MISSING_SINGLE_FALLBACK"
#: Max single-ticker GETs per run; the rest are dropped with a warning.
MISSING_FALLBACK_CAP = 500

# --- Reports source ---------------------------------------------------

REPORTS_BASE = "https://railbirdexchange.com/reports"
DAILY_MARKET = "daily-market"
ET = ZoneInfo("America/New_York")
#: Reports name their own timezone in the timestamp; map to real zones.
_TZ_SUFFIXES = (" EDT", " EST")

GCP_PROJECT = os.environ.get("GCP_PROJECT", "")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "wsd-mmmapper/1.0 (market mapping)"
    return s


def _api_base() -> str:
    return os.environ.get(API_BASE_ENV, PROD_API_BASE).rstrip("/")


def _apply_api_key(session: requests.Session) -> None:
    """Attach a key only when one is configured. Prod and staging are open."""
    header = os.environ.get(API_KEY_HEADER_ENV, DEFAULT_API_KEY_HEADER)
    inline = os.environ.get("DKEX_API_KEY", "").strip()
    if inline:
        session.headers[header] = inline
        return
    if os.environ.get(USE_API_KEY_SECRET_ENV, "").strip() != "1":
        return
    session.headers[header] = _api_key()


def _api_key() -> str:
    """Read the REST credential from Secret Manager via the gcloud CLI."""
    project = os.environ.get("GCP_PROJECT", "").strip() or GCP_PROJECT
    if not project:
        sys.exit("GCP_PROJECT must be set to read the DKEX API credential")
    out = subprocess.run(  # nosec B603 — fixed argv, no shell
        gcloud_cmd(
            "secrets", "versions", "access", "latest",
            f"--secret={API_KEY_SECRET}", f"--project={project}",
        ),
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        sys.exit(f"could not read secret {API_KEY_SECRET}: {out.stderr.strip()}")
    return out.stdout.strip()


def fetch_api(statuses: tuple[str, ...], with_combos: bool) -> list[dict]:
    """Page tickers, then batch-fetch market metadata (REST v0.6.1)."""
    base = _api_base()
    session = _session()
    _apply_api_key(session)
    # The listing is bare ticker strings.  Every one goes to the markets
    # batch; a combo comes back under ``missingTickers`` and drops out, so
    # nothing here has to tell a combo from a single by its ticker.
    tickers = page_market_tickers(session, base, statuses)
    if os.environ.get(MISSING_SINGLE_FALLBACK_ENV, "").strip() == "1":
        missing: list[str] = []
        markets = fetch_market_metadata(session, base, tickers, missing=missing)
        markets.extend(_recover_missing(session, base, missing))
    else:
        markets = fetch_market_metadata(session, base, tickers)
    if with_combos:
        complete, bare = page_combos(session, base, statuses)
        if bare:
            complete.extend(fetch_combo_metadata(session, base, bare))
        markets.extend(complete)
    return markets


def _recover_missing(
    session: requests.Session, base: str, missing: list[str]
) -> list[dict]:
    """GET each batch-missing ticker singly; combos and unknowns stay dropped."""
    todo = list(dict.fromkeys(missing))
    if len(todo) > MISSING_FALLBACK_CAP:
        print(
            f"warning: {len(todo)} missing tickers exceed cap "
            f"{MISSING_FALLBACK_CAP}; fetching the first {MISSING_FALLBACK_CAP}",
            file=sys.stderr,
        )
        todo = todo[:MISSING_FALLBACK_CAP]
    recovered = []
    for ticker in todo:
        row = fetch_single_market(session, base, ticker)
        if row is not None:
            recovered.append(row)
    print(
        f"dkex missing-ticker fallback: missing={len(missing)} "
        f"recovered={len(recovered)}",
        file=sys.stderr,
    )
    return recovered


def _get_json(session: requests.Session, url: str, params: dict) -> dict:
    for attempt in range(1, MAX_TRIES + 1):
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if attempt == MAX_TRIES or resp.status_code < 500:
            sys.exit(f"GET {url} -> {resp.status_code}: {resp.text[:300]}")
    return {}


# --- Reports source ---------------------------------------------------

def _parse_report_timestamp(raw: str) -> datetime | None:
    """Parse a report's "10/19/26 12:00 PM EDT" into an aware datetime."""
    text = (raw or "").strip()
    if not text:
        return None
    for suffix in _TZ_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    try:
        naive = datetime.strptime(text, "%m/%d/%y %I:%M %p")
    except ValueError:
        return None
    # The report prints wall-clock Eastern and names the offset; attaching
    # the zone (rather than the literal offset) keeps DST correct across
    # the EST/EDT boundary that every winter NFL market crosses.
    return naive.replace(tzinfo=ET)


def fetch_reports(date: str | None, statuses: tuple[str, ...]) -> list[dict]:
    """Read one public daily market report (T+1).  Development seed only."""
    session = _session()
    manifest = _get_json(session, f"{REPORTS_BASE}/{DAILY_MARKET}/manifest.json", {})
    reports = manifest.get("reports") or []
    if not reports:
        sys.exit("daily-market manifest listed no reports")
    chosen = next((r for r in reports if r.get("date") == date), None) if date else reports[-1]
    if chosen is None:
        sys.exit(f"no daily market report for {date}")
    resp = session.get(f"https://railbirdexchange.com{chosen['href']}", timeout=180)
    if resp.status_code != 200:
        sys.exit(f"GET {chosen['href']} -> {resp.status_code}")

    wanted = {s.lower() for s in statuses}
    rows: list[dict] = []
    for row in csv.DictReader(io.StringIO(resp.text)):
        status = (row.get("Status") or "").strip()
        if wanted and status.lower() not in wanted:
            continue
        maturity = _parse_report_timestamp(row.get("Maturity Date and Time (ET)", ""))
        rows.append({
            "ticker": (row.get("Symbol") or "").strip(),
            "status": status,
            # The report has no event-start column: maturity is the event
            # start plus exactly 30 days (see mappers/exchanges/dkex.py).
            "marketCloseTimestamp": maturity.isoformat() if maturity else None,
            "businessDate": (row.get("Business Date") or "").strip(),
            "openInterest": row.get("Open Interest"),
            "tradeVolume": row.get("Trade Volume"),
        })
    return rows


# --- Normalization ----------------------------------------------------

def normalize(raw: dict, source: str) -> dict:
    """One catalogue row, in the shape the mapper consumes.

    The mapper identifies a market ONLY from the typed fields below
    (``stat_achievement``, ``time_period``, ``competition_id``,
    ``participants`` with their ``role``, ``strike_price``,
    ``outcome_type``, ``sub_topic``).  ``symbol`` is kept as the venue's
    opaque market id -- it is what an RFQ leg names -- and is never
    parsed for identity.  A ``reports`` row has only the symbol, so its
    typed fields are all None and the mapper counts it as untyped.
    """
    ticker = str(raw.get("ticker") or raw.get("marketTicker") or "").strip()
    close_raw = raw.get("marketCloseTimestamp") or raw.get("closeTime")
    close = _as_datetime(close_raw)
    meta_raw = raw.get("metadata")
    meta = meta_raw if isinstance(meta_raw, dict) else {}
    params_raw = raw.get("parameters")
    params = params_raw if isinstance(params_raw, dict) else {}
    participants = _participants(meta)
    participant_id, participant_name = _participant_fields(participants, params)
    start = _event_start(raw, source, close, meta)
    return {
        "symbol": ticker,
        "is_combo": is_combo(raw),
        "status": raw.get("status"),
        "name": raw.get("name"),
        "event_ticker": raw.get("eventTicker"),
        "market_close": close.astimezone(UTC).isoformat() if close else None,
        "event_start": start.astimezone(UTC).isoformat() if start else None,
        "competition_name": meta.get("competitionName"),
        "participant_id": participant_id,
        "participant_name": participant_name,
        # --- typed identity (REST only; None on a reports row) ---
        "stat_achievement": _text(params.get("statAchievement")),
        "time_period": _text(params.get("timePeriod")),
        "strike_price": _as_float(params.get("strikePrice")),
        "outcome_type": _text(params.get("outcomeType")),
        "competition_id": _text(meta.get("competitionId")),
        "league_id": _text(meta.get("leagueId")),
        "league_name": _text(meta.get("leagueName")),
        "sub_topic": _text(raw.get("subTopic")),
        "intake_event_id": _text(meta.get("intakeEventId")),
        "participants": participants,
        "product_ticker": raw.get("productTicker"),
        "open_interest": raw.get("openInterest"),
        "trade_volume": raw.get("tradeVolume"),
        "legs": raw.get("legs"),
        "source": source,
        "business_date": raw.get("businessDate"),
    }


def _event_start(
    raw: dict,
    source: str,
    close: datetime | None,
    meta: dict,
) -> datetime | None:
    if source == "api":
        live = _as_datetime(meta.get("competitionStartTime"))
        if live is not None:
            return live
    if close is None:
        return None
    return close - SETTLEMENT_LAG


def _participants(meta: dict) -> list[dict]:
    """``metadata.participants`` as ``[{id, name, role}]``; role may be None.

    Team markets carry the team with ``role`` home/away; player props
    carry the player with no role.  Kept verbatim -- never inferred.
    """
    out: list[dict] = []
    for row in meta.get("participants") or []:
        if not isinstance(row, dict):
            continue
        pid = _text(row.get("id"))
        if pid is None:
            continue
        role = _text(row.get("role"))
        out.append({
            "id": pid,
            "name": _text(row.get("name")),
            "role": role.casefold() if role else None,
        })
    return out


def _participant_fields(
    participants: list[dict], params: dict,
) -> tuple[str | None, str | None]:
    """(``parameters.participant``, its name from ``metadata.participants``)."""
    participant_id = _text(params.get("participant"))
    if not participant_id:
        return None, None
    for row in participants:
        if row["id"] == participant_id:
            return participant_id, row["name"]
    return participant_id, None


def _text(value: object) -> str | None:
    """Stripped string, or None when absent or blank."""
    text = str(value).strip() if value is not None else ""
    return text or None


def _as_float(value: object) -> float | None:
    """strikePrice arrives as a decimal string ("3.5"); None when absent."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _write(out_dir: str | None, rows: list[dict]) -> None:
    if not out_dir:
        for row in rows:
            print(json.dumps(row))
        return
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dkex_markets.jsonl")
    with open(path, "w") as handle:
        for row in rows:
            print(json.dumps(row), file=handle)
    print(f"wrote {len(rows)} rows -> {path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=("api", "reports"), default="api",
        help="api: venue REST catalogue (live, production). "
             "reports: public daily CSV (T+1, development seed only).",
    )
    parser.add_argument("--out-dir", help="directory for dkex_markets.jsonl")
    parser.add_argument(
        "--status", nargs="*", default=None,
        help="market statuses to keep (api default: active; reports default: Open)",
    )
    parser.add_argument(
        "--date", help="reports source only: business date YYYY-MM-DD (default: latest)",
    )
    parser.add_argument(
        "--combos", action="store_true",
        help="api source only: also page /api/v1/combos (opt-in at the venue too)",
    )
    args = parser.parse_args()

    if args.status is not None:
        statuses = tuple(args.status)
    elif args.source == "api":
        statuses = ("active",)
    else:
        statuses = ("Open",)
    if args.source == "api":
        raw = fetch_api(statuses, with_combos=args.combos)
    else:
        if args.combos:
            sys.exit("--combos needs --source api: the CSV reports carry no leg metadata")
        print(
            "WARNING: --source reports is a T+1 development seed, not a live "
            "catalogue; production mapping must use --source api.",
            file=sys.stderr,
        )
        raw = fetch_reports(args.date, statuses)

    rows = [normalize(item, args.source) for item in raw]
    _write(args.out_dir, rows)


if __name__ == "__main__":
    main()
