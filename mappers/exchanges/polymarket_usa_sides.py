"""Which venue side of a Polymarket US symbol each bet prices: ``yes`` / ``no``.

The maker must never work a side out from the symbol, so every row names
it. It is read from the gateway's typed fields only: ``marketSides[].long``
(the side the contract pays on = YES), the side's ``team.id`` bound onto a
fixture side, and its Over / Under / Yes / No description. A bet no single
typed side accounts for gets no side, and the caller drops it.
"""

from __future__ import annotations

from mappers.exchanges.polymarket_usa_records import UsMarket, UsSide
from mappers.exchanges.polymarket_usa_structured import Bet, EventBind
from mappers.exchanges.polymarket_usa_titles import TITLE_KINDS
from mappers.market_types import MarketType, Shape
from mappers.vocab.poly_usa_smt import smt_spec

_OVER = frozenset({"over", "yes"})
_UNDER = frozenset({"under", "no"})
_YES_NO = frozenset({"yes", "no"})
_FLIP = {"yes": "no", "no": "yes"}

# Sides named by the side's team (two-team winner, spread).
_TEAM_KINDS = frozenset({"winner", "spread"})
# Sides named by Over / Under (Yes / No read as over / under).
_OU_KINDS = frozenset({"total", "team_total", "player_ou", "at_least"})
# Sides named by their own Yes / No.
_YN_KINDS = frozenset({"game_yn", "any_yn", "odd_even"})


def _label(kind: str, side: UsSide, bind: EventBind) -> str | None:
    """The bet side this venue side stands for under ``kind``, or None."""
    word = side.description.strip().casefold()
    if kind in _TEAM_KINDS:
        return bind.team_sides.get(side.team_id) if side.team_id else None
    if kind in _OU_KINDS:
        return "over" if word in _OVER else "under" if word in _UNDER else None
    if kind in _YN_KINDS:
        return word if word in _YES_NO else None
    if kind == "rof":  # venue Yes (ends before round N) = Optic to_start No
        return _FLIP.get(word)
    return None


def _yes_only(kind: str, mt: MarketType, market: UsMarket, bet: Bet) -> bool:
    """True when ``bet`` is the market's one outcome, priced by its long side.

    A per-outcome market (atc team or draw, team outcome, race, player Yes,
    title-read outcome) is "this happens": one bet, the contract's YES.
    """
    teams = {s.team_id for s in market.sides if s.team_id}
    if kind == "winner":
        return len(teams) <= 1
    if kind == "player_ou":
        return mt.shape is Shape.YES_NO and bet[3] == "yes"
    if kind in ("team_outcome", "race", "player_yn"):
        return True
    # Title-read outcomes (method, round, exact score …) are Yes-only; rof
    # and odd/even map both sides and are read off their descriptions.
    return kind in TITLE_KINDS and kind not in ("rof", "odd_even")


def _priced_type(spec_mt: MarketType, bet: Bet) -> MarketType | None:
    """The bet's canonical. ``market_bets`` already applied any tip remap."""
    if bet[0] == spec_mt.value:
        return spec_mt
    try:
        return MarketType(bet[0])
    except ValueError:
        return None


def venue_side(market: UsMarket, bind: EventBind, bet: Bet) -> str | None:
    """``yes`` / ``no``: the venue side of ``market`` that ``bet`` prices."""
    spec = smt_spec(market.sports_market_type)
    if spec is None:
        return None
    mt = _priced_type(spec[0], bet)
    if mt is None:
        return None
    kind = spec[1]
    long = market.long_side()
    if long is None or len(market.sides) != 2:
        return None
    if _yes_only(kind, mt, market, bet):
        return "yes"
    hits = [s for s in market.sides if _label(kind, s, bind) == bet[3]]
    if len(hits) != 1:
        return None
    return "yes" if hits[0].long else "no"
