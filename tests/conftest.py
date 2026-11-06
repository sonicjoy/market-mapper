"""Keep mapper unit tests independent of a developer's live SoT env."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sot" / "tip.json"
if _FIXTURE.is_file():
    os.environ.setdefault("MAPPING_SOT_FIXTURE", str(_FIXTURE))


@pytest.fixture(autouse=True)
def _isolate_mapping_sot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the offline SoT fixture; tests that need python mode set it explicitly."""
    monkeypatch.delenv("MAPPING_SOT", raising=False)
    monkeypatch.delenv("MAPPING_CP_BOOTSTRAP", raising=False)
    if _FIXTURE.is_file():
        monkeypatch.setenv("MAPPING_SOT_FIXTURE", str(_FIXTURE))
    from mappers.seed.sot import reset_sot_cache

    reset_sot_cache()


def us_gateway_market(
    slug: str,
    *,
    league: str = "",
    teams: tuple[tuple[str, str], ...] = (),
    smt: str = "",
    start: str = "",
    closed: bool = False,
) -> dict:
    """A raw gateway market for the fake ``/v1/markets`` (``us_gateway``).

    ``teams`` = ((abbreviation, name), ...), home first; a team-less market
    (a player prop) names no league, as on the venue.
    """
    sides = [
        {"team": {
            "id": str(i + 1), "abbreviation": abbr, "name": name,
            "league": league, "ordering": "home" if i == 0 else "away",
        }}
        for i, (abbr, name) in enumerate(teams)
    ] or [{"description": "Yes"}, {"description": "No"}]
    return {
        "slug": slug, "sportsMarketType": smt, "gameStartTime": start,
        "question": slug, "active": not closed, "closed": closed,
        "marketSides": sides,
    }


@pytest.fixture(autouse=True)
def us_gateway(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, dict]]:
    """Offline Polymarket US gateway: {symbol -> raw market}; empty = unknown."""
    from fetch import polymarket_usa_gateway as gw

    class _Known(dict):
        def __setitem__(self, key: str, value: dict) -> None:
            super().__setitem__(key, value)
            gw.clear_cache()  # a newly listed symbol is visible at once

    known: dict[str, dict] = _Known()
    gw.clear_cache()
    monkeypatch.setattr(
        gw, "_fetch_batch", lambda symbols: [known[s] for s in symbols if s in known],
    )
    yield known
    gw.clear_cache()
