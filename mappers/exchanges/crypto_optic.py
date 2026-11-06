"""Decode Optic crypto.com source_ids.market_id to FIX Symbol/SecurityID.

Optic encodes the FIX symbol inside a descriptive market_id, e.g.:

    MLB-00001-260727-M-TOT11P5Over-O139_261130-2300_1_PM.NPO
    → NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130

Slot lengths after ``O`` are not fixed: generate every split and accept
only the candidate that exists uniquely in the latest FIX catalogue.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mappers.exchanges.optic import CRYPTO_COM_SPORTSBOOK, Odd
from mappers.shared import CanonicalRow, lines

_OPTIC_MARKET_ID_RE = re.compile(
    r"^(?P<event>.+)-O(?P<slots>\d+)_(?P<maturity>\d{6})-"
)


@dataclass(frozen=True)
class CatalogueEntry:
    """Latest FIX catalogue row for one Symbol."""
    symbol: str
    security_id: str
    publish_time: str | None = None


@dataclass(frozen=True)
class DecodeResult:
    """Successful Optic market_id → FIX catalogue resolve."""
    market_id: str
    symbol: str
    security_id: str
    publish_time: str | None = None


def candidate_symbols(market_id: str) -> list[str]:
    """All FIX Symbol candidates encoded by an Optic crypto market_id."""
    match = _OPTIC_MARKET_ID_RE.match(market_id)
    if match is None:
        return []
    event = match.group("event")
    # Descriptor segment (TOT… / SPD…) sits after the event base
    # ``LEAGUE-#####-YYMMDD-M``; keep only the first four hyphen parts.
    # legacy: ticker parse — replace with the typed venue field, do not extend
    parts = event.split("-")
    if len(parts) < 4:
        return []
    event_base = "-".join(parts[:4])
    slots = match.group("slots")
    maturity = "20" + match.group("maturity")
    out: list[str] = []
    for i in range(1, len(slots)):
        out.append(
            f"NX.F.OPT.{event_base}.O.{slots[:i]}.{slots[i:]}.{maturity}"
        )
    return out


def decode_market_id(
    market_id: str | None,
    catalogue: dict[str, CatalogueEntry],
) -> DecodeResult | None:
    """Resolve Optic market_id to exactly one catalogue Symbol, else None."""
    if not market_id:
        return None
    hits = [
        catalogue[sym]
        for sym in candidate_symbols(market_id)
        if sym in catalogue
    ]
    if len(hits) != 1:
        return None
    hit = hits[0]
    return DecodeResult(
        market_id=market_id,
        symbol=hit.symbol,
        security_id=hit.security_id,
        publish_time=hit.publish_time,
    )


def load_catalogue_index(source: Path | Iterable[str]) -> dict[str, CatalogueEntry]:
    """Build Symbol → latest catalogue entry from crypto_com_markets.jsonl."""
    index: dict[str, CatalogueEntry] = {}
    if isinstance(source, Path):
        if not source.exists():
            return index
        line_iter = lines(source)
    else:
        line_iter = source
    for line in line_iter:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        symbol = row.get("Symbol")
        security_id = row.get("SecurityID")
        if not symbol or not security_id:
            continue
        publish_time = row.get("publish_time")
        prev = index.get(symbol)
        if prev is None or _is_fresher(security_id, publish_time, prev):
            index[symbol] = CatalogueEntry(
                symbol=symbol,
                security_id=security_id,
                publish_time=_as_str(publish_time),
            )
    return index


def _as_str(value) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _is_fresher(
    security_id: str,
    publish_time,
    prev: CatalogueEntry,
) -> bool:
    """Prefer newer publish_time; fall back to lexicographic SecurityID."""
    new_ts = _parse_ts(publish_time)
    old_ts = _parse_ts(prev.publish_time)
    if new_ts is not None and old_ts is not None:
        return new_ts > old_ts
    return security_id > prev.security_id


def _parse_ts(value) -> float | None:
    """Parse Optic epoch float or ISO/catalogue publish_time to epoch seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def stamp_from_optic_odds(
    rows: Iterable[CanonicalRow],
    odd_lookup: dict[str, Odd],
    catalogue: dict[str, CatalogueEntry],
    *,
    league: str,
) -> dict[str, int]:
    """Stamp Optic-decoded FIX ids onto rows that already carry optic_id.

    Returns counts: stamped / no_source / decode_miss / no_optic_id.
    Missing or ambiguous IDs are skipped (FIX semantic path may fill).
    """
    stats = {
        "stamped": 0, "no_source": 0, "decode_miss": 0, "no_optic_id": 0,
    }
    for row in rows:
        _stamp_one_optic_row(row, odd_lookup, catalogue, stats)
    _log_optic_stamp_stats(league, stats)
    return stats


def _stamp_one_optic_row(
    row: CanonicalRow,
    odd_lookup: dict[str, Odd],
    catalogue: dict[str, CatalogueEntry],
    stats: dict[str, int],
) -> None:
    """Attempt one Optic→FIX crypto stamp; update stats in place."""
    if not row.optic_id:
        stats["no_optic_id"] += 1
        return
    odd = odd_lookup.get(row.optic_id)
    if odd is None:
        stats["no_optic_id"] += 1
        return
    src = (odd.source_ids or {}).get(CRYPTO_COM_SPORTSBOOK) or {}
    market_id = src.get("market_id") if isinstance(src, dict) else None
    if not market_id:
        stats["no_source"] += 1
        return
    decoded = decode_market_id(market_id, catalogue)
    if decoded is None:
        stats["decode_miss"] += 1
        return
    _apply_optic_stamp(row, decoded, odd)
    stats["stamped"] += 1


def _log_optic_stamp_stats(league: str, stats: dict[str, int]) -> None:
    """Print Optic crypto stamp summary for this league."""
    if stats["decode_miss"]:
        print(
            f"  crypto-optic [{league}]: {stats['decode_miss']} Optic "
            f"market_id(s) failed unique FIX symbol decode "
            f"(FIX semantic path may fill)",
            file=sys.stderr,
        )
    if stats["stamped"]:
        print(
            f"  crypto-optic [{league}]: {stats['stamped']} stamped from "
            f"Optic source_ids",
            file=sys.stderr,
        )


def _apply_optic_stamp(
    row: CanonicalRow,
    decoded: DecodeResult,
    odd: Odd,
) -> None:
    """Write Optic-decoded crypto fields and comparable source timestamp."""
    row.crypto_security_id = decoded.security_id
    row.crypto_symbol = decoded.symbol
    row.crypto_market_id = decoded.market_id
    row.crypto_source_ts = _parse_ts(getattr(odd, "timestamp", None))
    if row.crypto_source_ts is None:
        row.crypto_source_ts = _parse_ts(decoded.publish_time)


def stamp_ts_from_catalogue(publish_time: str | None) -> float | None:
    """Convert FIX catalogue publish_time to epoch seconds for latest-wins."""
    return _parse_ts(publish_time)


def prefer_candidate_stamp(
    candidate_ts: float | None,
    incumbent_ts: float | None,
) -> bool | None:
    """True if candidate wins, False if incumbent wins, None if undecided."""
    if candidate_ts is None or incumbent_ts is None:
        return None
    if candidate_ts == incumbent_ts:
        return None
    return candidate_ts > incumbent_ts
