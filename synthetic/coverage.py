"""Three-way coverage gate.

For each Kalshi event we decide one of:
  * SKIP     — a Kalshi ORIGINAL mapping already exists (Optic covers it).
  * BACKFILL — no Kalshi mapping, but a real Optic fixture exists for the event
               → write a mapping onto the REAL fixture (no synthetic fixture).
  * SYNTH    — nothing exists → mint both a synthetic fixture and a mapping.

The point of the module is "add fixtures+mappings where NOTHING exists from
Optic", so we must robustly confirm a fixture doesn't already exist before
minting one (else we create a duplicate). Since there's no shared id between a
Kalshi event and an Optic fixture, existence is matched on date + participant
surnames (the reconcile_itf_fixtures.py approach).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

SYNTHETIC_PREFIX = "wsdsyn-"


@dataclass(frozen=True)
class OpticFixture:
    """A real (non-synthetic) Optic fixture, slimmed for backfill matching."""
    id: str
    game_id: str
    start_date: date
    home_u: str   # UPPER(home_team_display)
    away_u: str   # UPPER(away_team_display)
    league_id: str = ""   # Optic league, for league-scoped matching (see below)


def load_covered_tickers(client, tickers: list[str], window_start_iso: str) -> set[str]:
    """Kalshi tickers already mapped by ORIGINAL *or* GREG — the SKIP set.

    Two sources, both requiring a real Optic fixture (which is what we must NOT
    duplicate):
      * ORIGINAL — `opticodds_us.prices_dedup_state` (Optic's own auto-classification).
      * GREG     — `markets_us.market_mapping`, NON-synthetic rows (game_id not
                   `wsdsyn-`), i.e. the mapping pipeline's own leagues (e.g. itf_men
                   maps KXITFMATCH where an Optic fixture exists).
    We synthesize only the residual — tickers with no fixture anywhere. This is what
    keeps us out of GREG's lane: a KXITFMATCH the GREG itf_men league already mapped
    lands here and is skipped; a no-fixture KXITFMATCH (e.g. Davis Cup Group III) does
    not, so we synthesize it. source_ids is a JSON column in both tables.

    ``tickers`` are the exact market tickers this run listed; they are matched
    whole, never by prefix.
    """
    if not tickers:
        return set()
    from google.cloud import bigquery
    sql = f"""
        SELECT DISTINCT JSON_VALUE(source_ids,'$.market_id') AS ticker
        FROM `{client.project}.opticodds_us.prices_dedup_state`
        WHERE sportsbook = 'Kalshi'
          AND JSON_VALUE(source_ids,'$.market_id') IN UNNEST(@tickers)
          -- Exclude OUR OWN synthetic rows. We publish mapping_override for the
          -- wsdsyn fixtures, which the prices_state_merge folds into
          -- prices_dedup_state (game_id `wsdsyn-…`, is_mapping_override=TRUE). Without
          -- this the gate would count our own overrides as ORIGINAL "coverage" and
          -- skip the very tickers we synthesize — retiring live fixtures every run
          -- (self-cannibalisation). Mirrors the GREG branch's wsdsyn- exclusion below.
          AND NOT STARTS_WITH(COALESCE(game_id, ''), '{SYNTHETIC_PREFIX}')
        UNION DISTINCT
        SELECT DISTINCT JSON_VALUE(source_ids,'$.market_id') AS ticker
        FROM `{client.project}.markets_us.market_mapping`
        WHERE sportsbook = 'Kalshi'
          AND start_date >= TIMESTAMP(@window_start)
          AND NOT STARTS_WITH(COALESCE(game_id, ''), '{SYNTHETIC_PREFIX}')
          AND JSON_VALUE(source_ids,'$.market_id') IN UNNEST(@tickers)
    """  # nosec B608 - project is code-derived; values are bound parameters
    params = [
        bigquery.ArrayQueryParameter("tickers", "STRING", sorted(set(tickers))),
        bigquery.ScalarQueryParameter("window_start", "STRING", window_start_iso),
    ]
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    return {r.ticker for r in job.result() if r.ticker}


def load_optic_fixtures(client, sport_id: str, window_start_iso: str,
                        window_end_iso: str) -> list[OpticFixture]:
    """Real (non-synthetic) Optic fixtures for the sport in the date window."""
    sql = f"""
        SELECT id, game_id, DATE(start_date) AS d,
               UPPER(home_team_display) AS home_u,
               UPPER(away_team_display) AS away_u,
               league_id
        FROM `{client.project}.opticodds_us.opticodds_fixtures`
        WHERE start_date BETWEEN TIMESTAMP('{window_start_iso}')
                             AND TIMESTAMP('{window_end_iso}')
          AND sport_id = '{sport_id}'
          AND NOT STARTS_WITH(COALESCE(id, ''), '{SYNTHETIC_PREFIX}')
        QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY publish_time DESC) = 1
    """
    out: list[OpticFixture] = []
    for r in client.query(sql).result():
        if r.id and r.d:
            out.append(OpticFixture(r.id, r.game_id, r.d,
                                    r.home_u or "", r.away_u or "",
                                    r.league_id or ""))
    return out


_WORD_RE = re.compile(r"[A-Za-z]+")


def _surnames(name: str) -> set[str]:
    """Alpha tokens length>=3, upper-cased — a cheap surname proxy.

    For doubles ("A / B") this yields tokens from both players; matching wants
    at least one strong token per side, so we keep all.
    """
    return {w.upper() for w in _WORD_RE.findall(name or "") if len(w) >= 3}


def find_existing_fixture(name_a: str, name_b: str, event_day: date,
                          fixtures: list[OpticFixture],
                          league_id: str | None = None) -> tuple[str, str] | None:
    """Return (game_id, fixture_id) of a real Optic fixture for this event, else None.

    Match = same league (when `league_id` is given) AND date within +/-1 day AND
    each side's surname set overlaps a distinct side of the fixture (either
    orientation). Conservative: requires both sides to hit, so a coincidental
    single-token match (e.g. "Andre" vs "Andrea") can't false-positive on its own.

    `league_id` IS LOAD-BEARING, not cosmetic. `load_optic_fixtures` is scoped by
    SPORT, so for tennis the candidate pool is every atp / wta / atp_challenger /
    utr_men / utr_women / itf_men / itf_women / *_doubles fixture in the window —
    791 of them on 2026-09-01. Without a league filter an ITF singles event can
    match a same-day UTR or Challenger fixture carrying the same two surnames, and
    a mis-route is worse than the duplicate fixture backfill exists to avoid: our
    Kalshi orderbook prices would publish under a DIFFERENT match's fixture id.
    Pass the series' league_id whenever backfill is enabled.
    """
    a, b = _surnames(name_a), _surnames(name_b)
    if not a or not b:
        return None
    for fx in fixtures:
        if league_id is not None and fx.league_id != league_id:
            continue
        if abs((fx.start_date - event_day).days) > 1:
            continue
        home_hit_a = bool(a & _surnames_from_display(fx.home_u))
        away_hit_b = bool(b & _surnames_from_display(fx.away_u))
        home_hit_b = bool(b & _surnames_from_display(fx.home_u))
        away_hit_a = bool(a & _surnames_from_display(fx.away_u))
        if (home_hit_a and away_hit_b) or (home_hit_b and away_hit_a):
            return fx.game_id, fx.id
    return None


def _surnames_from_display(display_upper: str) -> set[str]:
    """Alpha tokens (len>=3) from an already-upper-cased team display string."""
    return {w for w in _WORD_RE.findall(display_upper or "") if len(w) >= 3}


def window(past_days: int = 3, future_days: int = 12) -> tuple[str, str]:
    """(start_iso, end_iso) date strings for the scan/partition window."""
    from datetime import UTC, datetime
    now = datetime.now(UTC).date()
    return (
        (now - timedelta(days=past_days)).isoformat(),
        (now + timedelta(days=future_days)).isoformat(),
    )
