"""Harvest skips decided from the key alone, before crypto catalogue HTTP.

``offline_dead`` marks a whole-series verdict (no Optic league):
the walk retires the bucket at once. A kickoff beyond the horizon is only this
key's verdict, so the rest of the series keeps probing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from mappers.control_plane.chat_tools_crypto_gap import (
    _horizon,
    _infer_leagues,
    _parse_symbol,
    _time_kind,
)
from mappers.control_plane.gap_inventory import _kickoff_date


def try_crypto_offline_probe(
    store: Any,
    symbol: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Probe row when the symbol can only end missing_optic / outside_horizon.

    An unwired token is left to the live probe: ``league_not_wired`` drives
    crypto league onboarding.
    """
    parsed = _parse_symbol(symbol)
    if parsed is None or parsed.get("futures"):
        return None
    slugs = _infer_leagues(store, parsed["token"], None)
    if not slugs:
        return None
    if not _any_optic_league(store, slugs):
        return _crypto_row(symbol, parsed["token"], slugs, "missing_optic", dead=True)
    hours = _hours_until(_kickoff_date("crypto", symbol), now)
    if hours is not None and _time_kind(hours, _horizon(store, slugs)) == "outside_horizon":
        return _crypto_row(symbol, parsed["token"], slugs, "outside_horizon", dead=False)
    return None


def _hours_until(kick: date | None, now: datetime | None) -> float | None:
    """Hours to the kickoff day's midnight UTC — never later than the real kickoff."""
    if kick is None:
        return None
    clock = now or datetime.now(UTC)
    start = datetime(kick.year, kick.month, kick.day, tzinfo=UTC)
    return (start - clock).total_seconds() / 3600.0


def _any_optic_league(store: Any, slugs: list[str]) -> bool:
    rid = store.current_rule_set_id
    if not rid:
        return False
    wired = {r.league for r in store.leagues_for(rid) if r.optic_league_id}
    return any(slug in wired for slug in slugs)


def _crypto_row(
    symbol: str, token: str, slugs: list[str], kind: str, *, dead: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "offline_skip": True,
        "offline_dead": dead,
        "symbol": symbol,
        "sportsbook": "crypto.com",
        "league": slugs[0] if slugs else "",
        "leagues": slugs,
        "token": token,
        "meta_league": "",
        "kind": kind,
        "crypto_ids": [],
        "tip": [],
        "optic": {},
        "mapped_rows": [],
    }
