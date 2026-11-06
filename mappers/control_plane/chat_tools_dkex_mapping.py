"""DKEX ticker classify + catalogue anatomy for Mapper Chat.

A pasted token is a DKEX ticker when the typed catalogue
(``dkex_markets.jsonl`` under ``MAPPING_DATA_DIR``) holds a row with that
exact ``symbol``; its shape is never inspected.  The anatomy -- league,
market, period, participant, line -- is read from that row, never sliced
out of the ticker.  A token the catalogue does not hold is not DKEX.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any

from mappers.exchanges.dkex import league_token

# Characters a human wraps a pasted id in; stripped before the lookup.
_WRAP = "`'\"()[]{}<>,;:."


def find_dkex_symbol(text: str, path: Path | None = None) -> str:
    """First whitespace token of ``text`` that the DKEX catalogue lists, or ``""``."""
    tokens = [t.strip(_WRAP) for t in (text or "").split()]
    wanted = [t for t in tokens if t]
    if not wanted:
        return ""
    found = _catalogue_symbols(set(wanted), path)
    return next((t for t in wanted if t in found), "")


def classify_dkex_symbol(text: str) -> dict[str, str] | None:
    """Return classify_source_id fields when ``text`` names a DKEX ticker."""
    dkex_sym = find_dkex_symbol(text)
    if not dkex_sym:
        return None
    return {
        "id": dkex_sym,
        "norm_id": dkex_sym,
        "sportsbook": "dkex",
        "id_kind": "dkex_symbol",
    }


def _catalogue_path() -> Path | None:
    raw = os.environ.get("MAPPING_DATA_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw) / "dkex_markets.jsonl"
    return path if path.is_file() else None


def _catalogue_symbols(wanted: set[str], path: Path | None = None) -> set[str]:
    """The members of ``wanted`` that are a catalogue row's ``symbol``."""
    source = path or _catalogue_path()
    if source is None or not wanted:
        return set()
    found: set[str] = set()
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            if not any(w in line for w in wanted):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = rec.get("symbol") if isinstance(rec, dict) else None
            if sym in wanted:
                found.add(sym)
                if found == wanted:
                    break
    return found


def catalogue_row(ticker: str, path: Path | None = None) -> dict[str, Any] | None:
    """The normalized catalogue row whose ``symbol`` is ``ticker``, or None."""
    source = path or _catalogue_path()
    want = ticker.strip()
    if source is None or not want:
        return None
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            if want not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("symbol") == want:
                return rec
    return None


def dkex_league_token(symbol: str, path: Path | None = None) -> str:
    """Venue league token ("NFL", "EPL") of a listed DKEX symbol, else ``""``.

    Read from the catalogue row's typed ``subTopic`` through
    ``league_token`` -- the symbol itself is only the lookup key.  The
    catalogue is indexed once per file version, since the gap batch asks
    for many keys and the book is ~600k rows.
    """
    source = path or _catalogue_path()
    want = (symbol or "").strip()
    if source is None or not want:
        return ""
    stat = source.stat()
    return _league_index(str(source), stat.st_mtime_ns, stat.st_size).get(want, "")


@functools.lru_cache(maxsize=2)
def _league_index(path: str, _mtime_ns: int, _size: int) -> dict[str, str]:
    """{symbol -> league token} for every typed catalogue row."""
    index: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            sym, token = rec.get("symbol"), league_token(rec.get("sub_topic"))
            if isinstance(sym, str) and sym and token:
                index[sym] = token
    return index


def dkex_symbol_fields(source_id: str, path: Path | None = None) -> dict[str, Any]:
    """Typed anatomy for a DKEX ticker from the catalogue -- no network."""
    rec = catalogue_row(source_id, path)
    if rec is None or not rec.get("stat_achievement"):
        return {}
    return {
        "seen": True,
        "sportsbook": "dkex",
        "id_kind": "dkex_symbol",
        "title": str(rec.get("name") or source_id),
        "league": league_token(rec.get("sub_topic")),
        "market": rec.get("stat_achievement") or "",
        "period": rec.get("time_period") or "",
        "event_id": rec.get("competition_id") or "",
        "participant_id": rec.get("participant_id") or "",
        "participant_name": rec.get("participant_name") or "",
        "strike_price": rec.get("strike_price"),
        "outcome_type": rec.get("outcome_type") or "",
        "competition_name": rec.get("competition_name") or "",
        "event_start": rec.get("event_start") or "",
    }
