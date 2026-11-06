"""Runshop fixture chain load + Optic schedule matching."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mappers.exchanges import optic

_TITLE_SPLIT = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
_START_TOLERANCE_SEC = 3 * 3600


@dataclass(frozen=True)
class FixtureLink:
    """One Optic fixture joined to a Runshop tx id, plus whether the title is crossed."""

    tx_odds_fixture_id: int
    flipped: bool


@dataclass(frozen=True)
class FixtureChainRecord:
    tx_odds_fixture_id: int
    tx_legacy_fixture_id: int
    poly_game_id: str
    poly_title: str | None = None
    poly_start_time: str | None = None


def load_fixture_chain(path: Path) -> list[FixtureChainRecord]:
    if not path.exists():
        return []
    records: list[FixtureChainRecord] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            records.append(FixtureChainRecord(
                tx_odds_fixture_id=int(obj["tx_odds_fixture_id"]),
                tx_legacy_fixture_id=int(obj["tx_legacy_fixture_id"]),
                poly_game_id=str(obj["poly_game_id"]),
                poly_title=obj.get("poly_title"),
                poly_start_time=obj.get("poly_start_time"),
            ))
    return records


def _parse_poly_title(title: str | None) -> tuple[str, str] | None:
    if not title:
        return None
    parts = _TITLE_SPLIT.split(title.strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def _parse_start(ts: str | None) -> datetime | None:
    if not ts:
        return None
    text = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _name_matches(poly_name: str, optic_name: str, optic_abbr: str) -> bool:
    pn = poly_name.casefold()
    on = optic_name.casefold()
    oa = optic_abbr.casefold()
    return pn in on or on in pn or pn.startswith(oa) or oa in pn.split()


def _title_flipped(fixture: optic.Fixture, record: FixtureChainRecord) -> bool | None:
    """False when the title order is Optic's, True when it is crossed, None on no match."""
    poly_start = _parse_start(record.poly_start_time)
    optic_start = _parse_start(fixture.start_date)
    if poly_start and optic_start:
        delta = abs((poly_start - optic_start).total_seconds())
        if delta > _START_TOLERANCE_SEC:
            return None
    teams = _parse_poly_title(record.poly_title)
    if teams is None:
        return None
    poly_home, poly_away = teams
    aligned = (
        _name_matches(poly_home, fixture.home_name, fixture.home)
        and _name_matches(poly_away, fixture.away_name, fixture.away)
    )
    if aligned:
        return False
    crossed = (
        _name_matches(poly_away, fixture.home_name, fixture.home)
        and _name_matches(poly_home, fixture.away_name, fixture.away)
    )
    return True if crossed else None


def build_fixture_chain_index(
    chain_records: list[FixtureChainRecord],
    fixtures: list[optic.Fixture],
) -> dict[str, FixtureLink]:
    """Map Optic fixture_id → tx id and whether the title lists Optic's sides crossed."""
    index: dict[str, FixtureLink] = {}
    claimed = {link.tx_odds_fixture_id for link in index.values()}
    for fixture in fixtures:
        for record in chain_records:
            if record.tx_odds_fixture_id in claimed:
                continue
            flipped = _title_flipped(fixture, record)
            if flipped is None:
                continue
            index[fixture.fixture_id] = FixtureLink(record.tx_odds_fixture_id, flipped)
            claimed.add(record.tx_odds_fixture_id)
            break
    return index
