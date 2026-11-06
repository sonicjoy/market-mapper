"""SX Bet RFQ gaps: say WHY each unmapped (marketHash, side) key is unmapped; draft no pins.

What maps SX is code, not the tip: the leagues (``mappers/exchanges/sxbet_leagues.py``),
the market types (``mappers/vocab/sxbet_markets.py``) and any name pin are tables
in the repo, so a console card has nothing to approve.  Gap-propose still walks
every SX key so the ledger and the card say what the fix is:

* ``league_not_wired`` -- SX's league is not in ``SLUG_BY_LEAGUE_ID`` (or a tennis
  prefix): add it with the evidence (docs/adding-sxbet.md).
* ``type_not_mapped`` -- the league maps, the SX market type does not: extend the
  sport's crosswalk after reading what Optic maps it to.
* ``not_in_sx_catalogue`` -- SX no longer lists the hash (settled / pulled).
* ``needs_name_or_optic`` -- league and type map, so the fixture match (a name no
  rule fits) or Optic pricing that line is the gap.

The key is Optic's SX ``selection_id`` (``<hash>|one|two``); the market comes
from SX's public ``GET /markets/find`` (no key; at most 30 hashes per call,
docs.sx.bet/api-reference/get-markets-find).  Each skipped entry carries a
``detail`` with the SX sport, league, teams and type so a card is readable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

import requests

from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.exchanges import sxbet
from mappers.exchanges.sxbet_leagues import SX_SPORT_LABEL, config_for, slug_for

logger = logging.getLogger(__name__)

BOOK = "sxbet"
SX_API = "https://api.sx.bet"
#: ``GET /markets/find`` caps ``marketHashes`` at 30.
FIND_BATCH = 30
TIMEOUT_S = 20

LEAGUE_NOT_WIRED = "league_not_wired"
TYPE_NOT_MAPPED = "type_not_mapped"
NOT_IN_SX_CATALOGUE = "not_in_sx_catalogue"
NEEDS_NAME_OR_OPTIC = "needs_name_or_optic"

#: SX ``sportLabel`` -> mmmapper sport value (the inverse of ``SX_SPORT_LABEL``).
_SPORT_BY_LABEL = {label: sport for sport, label in SX_SPORT_LABEL.items()}

FetchFn = Callable[[list[str]], dict[str, dict[str, Any]]]


def sport_of_label(label: str) -> str:
    """mmmapper sport value for an SX ``sportLabel`` ("" when SX's sport is not mapped)."""
    return _SPORT_BY_LABEL.get(label, "")


def market_hash_of(key: str) -> str:
    """The marketHash of an SX gap key (``<hash>|one|two``), lowercased."""
    return key.split("|", 1)[0].strip().lower()


def fetch_sx_markets(hashes: Iterable[str], *, session: Any = None) -> dict[str, dict[str, Any]]:
    """``{hash -> /markets/find row}`` for the hashes SX still lists (an unknown hash is absent)."""
    wanted = sorted({h.strip().lower() for h in hashes if h and h.strip()})
    http = session or requests.Session()
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(wanted), FIND_BATCH):
        batch = wanted[start:start + FIND_BATCH]
        resp = http.get(f"{SX_API}/markets/find", params={"marketHashes": ",".join(batch)}, timeout=TIMEOUT_S)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"SX /markets/find status {body.get('status')!r}")
        for row in body.get("data") or []:
            mh = str((row or {}).get("marketHash") or "").strip().lower()
            if mh:
                out[mh] = row
    return out


def describe(m: sxbet.SxMarket) -> str:
    """One readable line for a card: sport, league (id), teams, type and outcomes."""
    return (
        f"{m.sport} · {m.league_label} ({m.league_id}) · {m.team_one} v {m.team_two} · "
        f"type {m.type}: {m.outcome_one} / {m.outcome_two}"
    )


def classify(raw: dict[str, Any] | None) -> tuple[str, str]:
    """(reason, detail) for one SX market; see the module docstring for each reason."""
    m = sxbet.market_from_row(raw) if raw else None
    if m is None:
        return NOT_IN_SX_CATALOGUE, "" if raw is None else "unreadable SX row"
    detail = describe(m)
    slug = slug_for(m.league_id, m.league_label, m.sport)
    if slug is None:
        return LEAGUE_NOT_WIRED, detail
    cfg = config_for(slug, sport_of_label(m.sport))
    if cfg is None or cfg.market_type(m) is None:
        return TYPE_NOT_MAPPED, f"{slug}: {detail}"
    return NEEDS_NAME_OR_OPTIC, f"{slug}: {detail}"


def league_slug(raw: dict[str, Any] | None) -> str:
    """The tip slug SX's league maps to ("" when unmapped) -- seats a key on a league card."""
    m = sxbet.market_from_row(raw) if raw else None
    if m is None:
        return ""
    return slug_for(m.league_id, m.league_label, m.sport) or ""


def harvest_sxbet_rfq(
    items: list[RfqGapItem],
    skipped: list[dict[str, str]],
    walked: set[tuple[str, str]] | None = None,
    *,
    fetch_fn: FetchFn | None = None,
) -> None:
    """Record one reason per SX key.  An SX outage walks nothing, so the keys are retried."""
    keys = [item.key for item in items if item.book == BOOK and item.key]
    if not keys:
        return
    try:
        markets = (fetch_fn or fetch_sx_markets)([market_hash_of(k) for k in keys])
    except Exception as exc:  # noqa: BLE001 — isolate the SX API from the other books
        logger.warning("gap harvest sxbet: SX /markets/find failed (%s); keys left unwalked", exc)
        skipped.append({"book": BOOK, "reason": f"harvest_error:{exc}"[:160]})
        return
    for key in keys:
        reason, detail = classify(markets.get(market_hash_of(key)))
        skipped.append({"book": BOOK, "key": key, "reason": reason, "detail": detail})
        if walked is not None:
            walked.add((BOOK, key))
    logger.info("pipeline gap-fix stage=probe book=sxbet keys=%d (classified, no pins)", len(keys))
