"""Series config + typed-field helpers for the synthetic-fixture job.

The job is GENERAL: it synthesizes fixtures+mappings for ANY Kalshi market that
OpticOdds has no fixture for. What to run on is data, not code — the series live
in `series.toml` (see `load_series`); onboard a new league/market by adding a
block there, no code change. ITF singles + doubles are just the first entries.

Identity is carried by the Kalshi market ticker (an opaque id, never parsed)
and settled Kalshi-side, so we do NOT resolve players against any external
system — names are read from the market subtitles for display only. That is
why same-surname collisions (Koffi vs Koffi) are a non-problem here.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).with_name("series.toml")


@dataclass(frozen=True)
class SyntheticSeries:
    """One Kalshi series we may synthesize fixtures/mappings for (from series.toml)."""
    series_ticker: str   # exact Kalshi series ticker, e.g. "KXITFDOUBLES"
    sport_id: str        # MUST match the in-play ALLOWED_SPORTS gate, e.g. "tennis"
    sport_name: str      # display, e.g. "Tennis"
    league_id: str       # cosmetic grouping, e.g. "itf_men_doubles"
    league_name: str     # display, e.g. "ITF Men Doubles"
    optic_market_id: str = "moneyline"  # Optic market-type slug for match-winner
    # Attach to a real Optic fixture (matched by date+names) instead of minting one.
    # OFF by default: no-fixture events have nothing to attach to, and a false-match
    # (e.g. a doubles player's same-day singles fixture) would mis-route.
    allow_backfill: bool = False
    # Only synthesize events estimated to start within this many hours.
    # None = no gate (synthesize everything). Used with start_bias_minutes
    # to estimate real kickoff from Kalshi's expected_expiration_time.
    ttko_hours: float | None = None
    # Kalshi's expected_expiration_time offset from real start, in minutes.
    # For ITF tennis this is ~346 min (measured on n=354 mapped singles).
    start_bias_minutes: int = 0
    # Shape of the market: a 2-competitor match-winner ("match_winner"), or an
    # N-runner outright ("outright" — F1/NASCAR race winner, golf). Selects the
    # builder pair in run.py; "outright" takes start_date from Kalshi's
    # expected_expiration_time (an outright has no milestone start) and writes
    # yes-side-only mapping rows, one per runner.
    market_type: str = "match_winner"
    # Also write markets_us.market_mapping ("GREG") rows.
    #
    # NOT needed for RFQ leg mapping or for orderbook pricing. With no GREG row
    # the loader's `greg_fixture_id` is NULL and its fixture join falls to
    # `f.game_id = c.game_id`, which resolves because a synthetic fixture sets
    # id == game_id. The manual F1/NASCAR process wrote none and took 210
    # confirmed bets (trading_us.rfq, 2026-07).
    #
    # Not an in-play switch: in-play eligibility comes from the tenant's
    # allowed_sports, no registration needed (R_080). The one known consumer is
    # MMOpticOdds inplay_producer/selection_resolver.py, which resolves
    # fixture -> tenant from it. UNVERIFIED whether that gates anything for a
    # Kalshi RFQ.
    # Leaving it True also carries the split-fixture exposure (G5/G8/G9), which
    # can only occur when greg_fixture_id is non-NULL.
    #
    # Default True so existing ITF behaviour is unchanged.
    write_greg_rows: bool = True


def load_series(path: Path | str = DEFAULT_CONFIG) -> list[SyntheticSeries]:
    """Load the [[series]] blocks from series.toml into SyntheticSeries objects."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    known = {fld.name for fld in fields(SyntheticSeries)}
    out: list[SyntheticSeries] = []
    for entry in data.get("series", []):
        unknown = set(entry) - known
        if unknown:
            raise ValueError(f"series.toml entry {entry.get('series_ticker')!r} has unknown keys: {unknown}")
        out.append(SyntheticSeries(**entry))
    if not out:
        raise ValueError(f"no [[series]] entries found in {path}")
    return out


def estimated_start(market: dict, bias_minutes: int = 0) -> datetime | None:
    """Estimate kickoff from Kalshi's expected_expiration_time minus bias.

    For ITF tennis, expected_expiration_time is ~346 min after real start.
    Subtracting that gives an estimate usable for a time-to-kickoff gate.
    Returns None if the field is missing or unparseable (caller should skip
    the gate, not reject the event).
    """
    raw = market.get("expected_expiration_time")
    if not raw:
        return None
    try:
        exp = datetime.fromisoformat(raw)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return exp - timedelta(minutes=bias_minutes)
    except (ValueError, TypeError):
        return None


def estimated_start_for_event(markets: list[dict],
                             bias_minutes: int = 0) -> datetime | None:
    """estimated_start over a whole outright event, using the MODAL expiration.

    An outright's contracts should all carry the same expected_expiration_time,
    but they do not always: 1 of 21 settled KXNASCARRACE events had a single
    runner an hour out of line with the other 38. Taking markets[0] would make
    the fixture's start_date a coin flip on those events, so use the value the
    field agrees on, earliest wins a tie.

    Erring EARLY is the safe direction: a start_date before the real start risks
    treating a leg as in-play too soon, whereas a late one leaves us quoting
    pre-off prices into a race that has already started.
    """
    raw = [m.get("expected_expiration_time") for m in markets]
    raw = [r for r in raw if r]
    if not raw:
        return None
    top = max(raw.count(v) for v in set(raw))
    modal = min(v for v in set(raw) if raw.count(v) == top)
    return estimated_start({"expected_expiration_time": modal}, bias_minutes)


def match_day(start_date: str | None) -> datetime | None:
    """00:01 UTC on the day of Kalshi's milestone ``start_date``.

    00:01 (not the milestone's own time) so `is_inplay_leg` (start_time < now)
    is False until match day, then True all day: Kalshi's tennis start times
    are not reliable enough to switch a leg in-play on.
    """
    if not start_date:
        return None
    try:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    day = dt.astimezone(UTC)
    return datetime(day.year, day.month, day.day, 0, 1, tzinfo=UTC)
