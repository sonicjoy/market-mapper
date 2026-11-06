"""Place a DKEX event on an Optic fixture whose start sits a little off DKEX's."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from mappers.exchanges.dkex_catalogue_read import DkexEvent, start_key

#: How far a DKEX start may sit from Optic's and still name the same game.
#: DKEX lists LA Dodgers @ MIL Brewers at 22:00 UTC where Optic has 00:00 the
#: next UTC day, which neither the exact minute nor the day lookup reaches.
NEAR_START = timedelta(hours=3)


def near_start_fixture(
    event: DkexEvent,
    by_day: dict[str, list],
    fixture_sides: Callable[[Any], dict[str, str] | None],
) -> tuple[Any, dict[str, str]] | None:
    """The one fixture within ``NEAR_START`` of a DKEX start that both teams name.

    Reached only after the exact minute and the UTC day found nothing.
    ``fixture_sides`` returns {participant id -> fixture side} when both event
    teams land on a fixture.  Exactly one fixture may qualify, so a
    back-to-back series (or a doubleheader) inside the window resolves to
    nothing.
    """
    hits: dict[int, tuple[Any, dict[str, str]]] = {}
    for start in event.starts:
        at = datetime.fromisoformat(start)
        for shift in (-1, 0, 1):
            day = (at.date() + timedelta(days=shift)).isoformat()
            for entry in by_day.get(day, []):
                key = start_key(entry.fixture.start_date)
                if not key or abs(datetime.fromisoformat(key) - at) > NEAR_START:
                    continue
                sides = fixture_sides(entry.fixture)
                if sides is not None:
                    hits[id(entry)] = (entry, sides)
    return next(iter(hits.values())) if len(hits) == 1 else None
