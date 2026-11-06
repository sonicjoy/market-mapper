"""Mismapping risk signals for one mapping row (mmmapper#23). Pure: no BQ, no store.

Each signal returns ``None`` (clean) or a ``{code, tier, text}`` dict. A row's
tier is its worst signal. Thresholds were set against the live 48h book on
2026-09-26 (see console_mismap_sql.py) so the high tier stays short enough to
read: what each rule deliberately ignores is noted beside it.

Signals and the evidence they need (absent evidence = signal skipped, never guessed):
- ``optic_disagrees``  Optic maps the same venue id to a different selection.
- ``missing_fixture_id`` the row has no Optic fixture_id, so it joins no fixture-keyed
                       price or check (override-created rows: prices_state_merge drops it).
- ``stale_game``       the row's game_id is no longer an Optic fixture (a reschedule
                       re-keyed the game); served = quoting on a dead game.
- ``key_multi_market`` one venue id is mapped to 2+ different markets / Optic fixtures
                       (doubleheaders, cross-wired players). Keyed on fixture_id, so a
                       reschedule's stale game_id copy is not a second market.
- ``ai_flagged``       the AI validator judged the row wrong (per-dimension reason).
- ``name_mismatch``    the venue's own text does not name the mapped player/team.
- ``price_gap``        pre-match venue price vs our fair for the mapped selection.
- ``period_mismatch``  Kalshi ticker period (1H / 2Q ...) vs the Optic market's period.
- ``shared_selection`` 2+ venue ids feed one selection (informational).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

HIGH, MEDIUM, LOW = "high", "medium", "low"
TIER_RANK = {HIGH: 3, MEDIUM: 2, LOW: 1}

PRICE_GAP_HIGH = 0.25
PRICE_GAP_MEDIUM = 0.15
# Optic prices an empty venue book at ~1.01; implied probabilities past these
# bounds are book artefacts, not evidence (most 09-26 outliers were exactly that).
PRICE_PROB_MIN, PRICE_PROB_MAX = 0.03, 0.97

_SIDE_WORDS = frozenset({"", "over", "under", "yes", "no", "draw", "tie", "odd", "even"})
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})
# Optic canon fields, in the order console_mismap_sql._CANON concatenates them.
_CANON_FIELDS = ("fixture", "market", "selection", "selection_line", "points")
_KALSHI_PERIOD = re.compile(r"(?<=[A-Z])([1-4])([HQP])(?=[A-Z]|$)")
# Baseball first-five-innings series (KXMLBF5...) are Optic's "1st_half_" markets.
_KALSHI_F5 = re.compile(r"(?<=[A-Z])F5(?=[A-Z]|$)")
_OPTIC_PERIOD = re.compile(r"^(1st|2nd|3rd|4th)_(half|quarter|period)_")
_ORDINAL = {"1st": "1", "2nd": "2", "3rd": "3", "4th": "4"}
_UNIT = {"half": "H", "quarter": "Q", "period": "P"}


def _signal(code: str, tier: str, text: str) -> dict[str, str]:
    return {"code": code, "tier": tier, "text": text}


def fold(text: str) -> str:
    """Lower-case, strip accents and punctuation: 'Enzo Fernández' -> 'enzo fernandez'."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    plain = re.sub(r"['\u2019`]", "", plain.lower())  # "Hawai'i" -> "hawaii"
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def _is_ours(row: dict[str, Any]) -> bool:
    return str(row.get("mapping_source") or "") != "ORIGINAL"


def _canon_diff(ours: str, theirs: str) -> list[str]:
    """Canon fields that differ: ``fixture`` / ``selection`` are the expensive ones."""
    pairs = zip(_CANON_FIELDS, ours.split("|"), theirs.split("|"), strict=False)
    return [name for name, a, b in pairs if a != b]


def optic_disagrees(row: dict[str, Any]) -> dict[str, str] | None:
    """Optic independently maps this venue id, and not to our selection.

    A different fixture or selection is high. Market / line only is low: on
    2026-09-26 that was 581 of 707 rows, all equivalent markets named apart
    (Novig ``player_goals`` 0.5 vs Optic ``anytime_goal_scorer``).
    """
    optic = [str(c) for c in row.get("optic_canons") or []]
    canon = str(row.get("canon") or "")
    if not _is_ours(row) or not optic or canon in optic:
        return None
    diff = _canon_diff(canon, optic[0])
    tier = HIGH if {"fixture", "selection"} & set(diff) else LOW
    return _signal("optic_disagrees", tier, f"Optic maps this venue id to {optic[0]} ({', '.join(diff)} differ)")


def _is_true(value: Any) -> bool:
    """BigQuery BOOL, or its JSON / CLI string form."""
    return value is True or str(value).lower() == "true"


def missing_fixture_id(row: dict[str, Any]) -> dict[str, str] | None:
    """No fixture_id: every fixture-keyed check is blind; MEDIUM when the row is served."""
    if row.get("fixture_id"):
        return None
    tier = MEDIUM if _is_true(row.get("is_rfq_winner")) else LOW
    return _signal("missing_fixture_id", tier, f"no Optic fixture_id on game {row.get('game_id')}")


def stale_game(row: dict[str, Any]) -> dict[str, str] | None:
    """The mapped game_id is no longer an Optic fixture: HIGH when this row is the served winner."""
    if row.get("game_live") is None or _is_true(row.get("game_live")):
        return None
    tier = HIGH if _is_true(row.get("is_rfq_winner")) else LOW
    return _signal("stale_game", tier, f"game {row.get('game_id')} is no longer an Optic fixture (rescheduled?)")


def key_multi_market(row: dict[str, Any]) -> dict[str, str] | None:
    """One venue id, several markets or Optic fixtures on our side."""
    if int(row.get("n_ours") or 0) < 2:
        return None
    ours = ", ".join(str(c) for c in (row.get("our_canons") or [])[:3])
    return _signal("key_multi_market", HIGH, f"venue id mapped to {row['n_ours']} markets/fixtures: {ours}")


def ai_flagged(row: dict[str, Any]) -> dict[str, str] | None:
    """The AI validator's verdict, with the dimensions it failed."""
    if row.get("ai_ok") is not False:
        return None
    dims = [d for d in ("fixture", "market", "side", "line", "entity") if row.get(f"ai_{d}_ok") is False]
    why = str(row.get("ai_reason") or "judged wrong")
    return _signal("ai_flagged", HIGH, f"AI validator: {why}" + (f" ({', '.join(dims)})" if dims else ""))


def _is_person_market(market_id: str) -> bool:
    """Player markets must match on surname; team markets on any name token."""
    return market_id.startswith("player_") or "goal_scorer" in market_id


def _names_it(name: str, venue: str, person: bool) -> bool:
    tokens = [t for t in name.split() if t not in _NAME_SUFFIXES]
    padded = f" {venue} "
    if f" {' '.join(tokens)} " in padded:
        return True
    if person:
        return bool(tokens) and len(tokens[-1]) >= 3 and f" {tokens[-1]} " in padded
    return any(len(t) >= 3 and f" {t} " in padded for t in tokens)


def _names_only_one_side(row: dict[str, Any]) -> bool:
    """Venue text that names one side, so the other side's selection never appears in it.

    Kalshi No sides (a Tie ticker's No is "Germany or Greece") and two-sided
    handicaps (Polymarket "Spread: Alcorn State (-3.5)" also carries Texas
    Southern +3.5; 3,273 of 3,704 Polymarket name hits on 2026-09-26).
    """
    market = str(row.get("market_id") or "")
    if row.get("sb") == "kalshi" and str(row.get("src_selection") or "").lower() == "no":
        return True
    return any(word in market for word in ("spread", "handicap", "run_line", "puck_line"))


def name_mismatch(row: dict[str, Any]) -> dict[str, str] | None:
    """The venue text never names the mapped player (surname) or team (any name token).

    Skipped for side words, "A or B" / draw selections and one-sided venue text.
    """
    venue = fold(str(row.get("exchange_text") or ""))
    name = fold(str(row.get("selection") or ""))
    if not venue or name in _SIDE_WORDS or " or " in f" {name} " or "draw" in name.split():
        return None
    if _names_only_one_side(row):
        return None
    if _names_it(name, venue, _is_person_market(str(row.get("market_id") or ""))):
        return None
    tier = HIGH if row.get("ai_entity_ok") is False else MEDIUM
    return _signal("name_mismatch", tier, f"venue text does not name {row.get('selection')!r}")


def _started(row: dict[str, Any], now: datetime) -> bool:
    start = row.get("start_date")
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if not isinstance(start, datetime):
        return False
    return (start if start.tzinfo else start.replace(tzinfo=UTC)) <= now


def price_gap(row: dict[str, Any], now: datetime) -> dict[str, str] | None:
    """Venue implied probability vs our fair, pre-match, real books only."""
    venue, fair = row.get("venue_price"), row.get("fair_price")
    if not venue or not fair or float(venue) <= 1 or float(fair) <= 1 or _started(row, now):
        return None
    p_venue, p_fair = 1 / float(venue), 1 / float(fair)
    if not PRICE_PROB_MIN <= p_venue <= PRICE_PROB_MAX:
        return None
    gap = abs(p_venue - p_fair)
    if gap < PRICE_GAP_MEDIUM:
        return None
    corroborated = row.get("canon") in [str(c) for c in row.get("optic_canons") or []]
    # Optic agreeing on the mapping makes a price gap a book problem, not a mapping one.
    tier = LOW if corroborated else (HIGH if gap >= PRICE_GAP_HIGH else MEDIUM)
    text = f"venue {p_venue:.0%} vs fair {p_fair:.0%}" + (" (Optic agrees on the mapping)" if corroborated else "")
    return _signal("price_gap", tier, text)


def _kalshi_period(ticker: str) -> str:
    series = ticker.split("-")[0]
    if _KALSHI_F5.search(series):
        return "1H"
    match = _KALSHI_PERIOD.search(series)
    return f"{match.group(1)}{match.group(2)}" if match else ""


def _optic_period(market_id: str) -> str:
    match = _OPTIC_PERIOD.match(market_id)
    return f"{_ORDINAL[match.group(1)]}{_UNIT[match.group(2)]}" if match else ""


def period_mismatch(row: dict[str, Any]) -> dict[str, str] | None:
    """Kalshi only: the ticker series names a period the Optic market does not (or vice versa)."""
    if row.get("sb") != "kalshi" or not row.get("src_market"):
        return None
    venue = _kalshi_period(str(row["src_market"]))
    optic = _optic_period(str(row.get("market_id") or ""))
    if venue == optic:
        return None
    return _signal("period_mismatch", MEDIUM, f"ticker period {venue or 'full game'} vs Optic {optic or 'full game'}")


def _yes_no_pair(keys: list[str]) -> bool:
    """Two tickers, one Yes and one No: the designed 2-way complement, not a collision."""
    return len(keys) == 2 and {k.rsplit("|", 1)[-1] for k in keys} == {"yes", "no"}


def shared_selection(row: dict[str, Any]) -> dict[str, str] | None:
    """Several venue ids feed one selection; usually a duplicate listing, worth a look."""
    keys = [str(k) for k in row.get("canon_src_keys") or []]
    if int(row.get("canon_keys") or 0) < 2 or _yes_no_pair(keys):
        return None
    return _signal("shared_selection", LOW, f"{row['canon_keys']} venue ids share this selection")


def score_row(row: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Every signal that fires on one row, and the row's tier (worst signal) or ``None``."""
    at = now or datetime.now(UTC)
    found = [
        sig
        for sig in (
            optic_disagrees(row),
            missing_fixture_id(row),
            stale_game(row),
            key_multi_market(row),
            ai_flagged(row),
            name_mismatch(row),
            price_gap(row, at),
            period_mismatch(row),
            shared_selection(row),
        )
        if sig is not None
    ]
    tier = max((s["tier"] for s in found), key=TIER_RANK.__getitem__, default=None)
    return {"tier": tier, "signals": found}
