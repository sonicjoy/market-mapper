"""Polymarket US Path 2 from structured gateway fields — no symbol parsing.

Input is ``polymarket_usa_markets.jsonl`` (``fetch.polymarket_usa``): one
line per gateway market with its event context. Everything that identifies
a market comes from typed fields, as the venue docs require ("never parse
instrument symbols"):

* **event → Optic fixture**, first unique hit wins, any disagreement drops:
  1. Sportradar id — only where the gateway carries the ``sr:…:<int>`` form
     Optic also uses (soccer / tennis). US leagues carry a Sportradar-US
     UUID that never equals Optic's integer, so they fall through;
  2. Optic's own ``Polymarket (USA)`` passthrough — a fixture whose odds
     already carry one of this event's market symbols;
  3. kickoff (``startTime`` ±2h) + both gateway ``teams`` binding onto the
     fixture sides by abbreviation (tip aliases) or team name.
* **market** → ``sportsMarketType`` (``mappers.vocab.poly_usa_smt``);
  line → ``line``; side → ``marketSides[].long`` + ``marketSides[].team``;
  player → ``metadata.playerName``.

The instrument symbol (``slug``) is only ever the value we stamp
(``polymarket_usa_market_id``), never an input to matching. The one
exception to typed-only is ``polymarket_usa_titles``: a few per-outcome
enums carry their outcome nowhere but ``title``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mappers.canonical_codes import names_fit, person_surname_initials, tokens
from mappers.exchanges.polymarket_usa_match import parse_kickoff, resolve_team_code
from mappers.exchanges.polymarket_usa_pairs import pair_fits
from mappers.exchanges.polymarket_usa_records import (  # noqa: F401 - re-exported
    UsMarket,
    UsSide,
    UsTeam,
    load_markets,
    parse_market,
)
from mappers.exchanges.polymarket_usa_titles import TITLE_KINDS, title_bets
from mappers.market_types import MarketType, Shape
from mappers.optic_abbr_bind import code_fits_side, optic_abbr
from mappers.shared import TIE_SIDE, CanonicalRow, normalize_line, normalize_player_name
from mappers.vocab.poly_usa_name_aliases import optic_names_for
from mappers.vocab.poly_usa_smt import smt_spec

# (market_type, entity, line, side[, grouping_key]); the 5th only for the
# fight-method kinds, whose method is Optic's grouping_key.
Bet = (
    tuple[str, str | None, float | None, str]
    | tuple[str, str | None, float | None, str, str | None]
)

# Series games sit ~24h apart, a same-day
# doubleheader ~6h. Two fixtures inside it → drop.
_INSTANT_TOLERANCE_S = 2 * 3600
_OVER_WORDS = frozenset({"over", "yes"})
_UNDER_WORDS = frozenset({"under", "no"})


# === Event → fixture bind ===


@dataclass
class EventBind:
    """One gateway event bound to an Optic fixture, plus team → side."""

    fixture: Any
    team_sides: dict[str, str] = field(default_factory=dict)  # team_id → fx side
    via: str = ""


def sportradar_int(value: str) -> str:
    """Trailing integer of an ``sr:<kind>:<int>`` id; '' for UUIDs etc."""
    text = (value or "").strip()
    if not text.startswith("sr:"):
        return ""
    tail = text.rsplit(":", 1)[-1]
    return tail if tail.isdigit() else ""


@dataclass(frozen=True)
class TeamAliases:
    """Book code → canonical code maps (Polymarket US first, Kalshi fallback)."""

    usa: Mapping[str, str]
    kalshi: Mapping[str, str]


def _club_name_contained(left: str, right: str) -> bool:
    """One club name's tokens all inside the other's ("Nueva Chicago" / "CA Nueva Chicago")."""
    lt = {t.casefold() for t in tokens(left)}
    rt = {t.casefold() for t in tokens(right)}
    short, long_ = (lt, rt) if len(lt) <= len(rt) else (rt, lt)
    return bool(short) and short <= long_ and any(len(t) >= 4 for t in short)


def _name_fits(name: str, optic_name: str, *, person: bool) -> bool:
    """names_fit, plus token containment for clubs and Optic's
    ``Surname I.`` short form for people (most Optic boxers)."""
    if person and "/" in optic_name:
        return pair_fits(name, optic_name, lambda o, t: _name_fits(o, t, person=True))
    if names_fit(name, optic_name, player=person):
        return True
    if person:
        return person_surname_initials(name, optic_name)
    return _club_name_contained(name, optic_name)


def team_side(team: UsTeam, fx: Any, aliases: TeamAliases, *, person: bool) -> str | None:
    """Fixture side this gateway team is, or None unless exactly one fits."""
    home, away = fx.home, fx.away
    home_oa, away_oa = optic_abbr(fx, home=True), optic_abbr(fx, home=False)
    sides = {home, away, home_oa, away_oa}
    hits: set[str] = set()
    if team.abbreviation:
        code = resolve_team_code(
            team.abbreviation, aliases.usa, aliases.kalshi, fixture_sides=sides,
        )
        for token in (code, team.abbreviation):
            if code_fits_side(token, home, home_oa):
                hits.add(home)
            if code_fits_side(token, away, away_oa):
                hits.add(away)
    if not hits:
        names = [n for n in (team.name, *team.alt_names) if n]
        names += optic_names_for(names)
        for side, optic_name in ((home, fx.home_name), (away, fx.away_name)):
            if optic_name and any(_name_fits(n, optic_name, person=person) for n in names):
                hits.add(side)
    return next(iter(hits)) if len(hits) == 1 else None


def _team_sides(
    teams: Iterable[UsTeam], fx: Any, aliases: TeamAliases, *, person: bool,
    eliminate: bool = True,
) -> dict[str, str]:
    """team_id → side for teams that bind uniquely and to distinct sides.

    Once the event is bound to ``fx``, with two teams one bound side names
    the other by elimination ("Dubai Basketball" / "BC Dubai"). Binding
    itself passes ``eliminate=False``: both teams must fit on their own.
    """
    teams = list(teams)
    out: dict[str, str] = {}
    for team in teams:
        side = team_side(team, fx, aliases, person=person)
        if side is not None:
            out[team.team_id] = side
    if len(set(out.values())) != len(out):
        return {}
    if eliminate and len(teams) == 2 and len(out) == 1:
        (known,) = out.values()
        other = next(t for t in teams if t.team_id not in out)
        out[other.team_id] = fx.away if known == fx.home else fx.home
    return out


def _in_window(fx: Any, instant: datetime | None) -> bool:
    """True when the fixture kicks off within the tolerance of ``instant``."""
    fx_start = parse_kickoff(getattr(fx, "start_date", None))
    if instant is None or fx_start is None:
        return False
    return abs((fx_start - instant).total_seconds()) <= _INSTANT_TOLERANCE_S


def fixture_ref(fx: Any) -> str:
    """Stable id for an Optic fixture (Optic fixture_id)."""
    return str(getattr(fx, "fixture_id", "") or id(fx))


def _pick(
    sr_hits: set[str] | None, timed: set[str], passthrough: set[str],
) -> tuple[str | None, str]:
    """(fixture id, via|reason) by signal priority.

    The venue's own fields outrank Optic's passthrough: 2026-09-25 prod,
    Optic hung BAL@NYY props on the wrong doubleheader game while the
    gateway kickoff named the right one. Sportradar and teams+kickoff must
    agree when both hit; passthrough only decides when neither hits, or
    breaks a teams+kickoff tie it sits inside.
    """
    if sr_hits is not None and len(sr_hits) > 1:
        return None, "ambiguous_sportradar"
    sr = next(iter(sr_hits)) if sr_hits else None
    tk = next(iter(timed)) if len(timed) == 1 else None
    if sr and tk and sr != tk:
        return None, "conflict_sportradar_vs_teams_kickoff"
    if sr:
        return sr, "sportradar"
    if tk:
        return tk, "teams_kickoff"
    pt = next(iter(passthrough)) if len(passthrough) == 1 else None
    if len(timed) > 1:
        if pt in timed:
            return pt, "optic_passthrough"
        return None, "ambiguous_teams_kickoff"
    if pt:
        return pt, "optic_passthrough"
    return None, "ambiguous_optic_passthrough" if passthrough else "no_fixture"


def bind_event(
    event: UsMarket,
    fixtures: list[Any],
    aliases: TeamAliases,
    optic_fixtures_for_event: set[str],
    *,
    person: bool = False,
) -> tuple[EventBind | None, str]:
    """(bind, via|reason). ``event`` is any market of the event (context fields)."""
    by_id = {fixture_ref(fx): fx for fx in fixtures}
    sr = sportradar_int(event.sportradar_game_id)
    sr_hits = {
        fid for fid, fx in by_id.items()
        if str(getattr(fx, "sportradar_id", "") or "") == sr
    } if sr else None
    instant = parse_kickoff(event.event_start)
    timed = {
        fid for fid, fx in by_id.items()
        if _in_window(fx, instant)
        and len(_team_sides(
            event.teams, fx, aliases, person=person, eliminate=False,
        )) == 2
    }
    fid, via = _pick(sr_hits, timed, set(optic_fixtures_for_event) & set(by_id))
    if fid is None:
        return None, via
    fx = by_id[fid]
    return EventBind(
        fixture=fx,
        team_sides=_team_sides(event.teams, fx, aliases, person=person),
        via=via,
    ), via


# === Market → bets ===


def _direction(desc: str) -> str | None:
    """Over/Yes → ``over``, Under/No → ``under``, else None."""
    word = desc.strip().casefold()
    if word in _OVER_WORDS:
        return "over"
    if word in _UNDER_WORDS:
        return "under"
    return None


def _yes_no(desc: str) -> str | None:
    """``yes`` / ``no`` for a Yes/No side description, else None."""
    word = desc.strip().casefold()
    return word if word in {"yes", "no"} else None


def _signed_spread(market: UsMarket, long: UsSide) -> float | None:
    """Long side's handicap from its numeric description (``"-10.50"``).

    ``line`` is signed on some leagues (NFL ``-10.5``) and unsigned on
    others (MLB ``2.5`` with long ``"+2.50"``); the long side's description
    is the one field that always carries the sign. It must agree with
    ``|line|`` or the market is dropped.
    """
    try:
        signed = float(long.description)
    except ValueError:
        return None
    if market.line is not None and abs(abs(signed) - abs(market.line)) > 1e-9:
        return None
    return normalize_line(signed)


def _player_line(market: UsMarket) -> float | None:
    """``N+`` (at least N) is over N−0.5; a half line stands as is."""
    if market.line is None:
        return None
    if market.line_label.endswith("+"):
        return normalize_line(market.line - 0.5)
    if market.line % 1:
        return market.line
    return None


def _side_team(side: UsSide | None, bind: EventBind) -> str | None:
    """Fixture side of the team this venue side names, if bound."""
    if side is None or not side.team_id:
        return None
    return bind.team_sides.get(side.team_id)


def _one_team(market: UsMarket, bind: EventBind) -> str | None:
    """The single team every side of a team-scoped market names."""
    teams = {s.team_id for s in market.sides if s.team_id}
    if len(teams) != 1:
        return None
    return bind.team_sides.get(next(iter(teams)))


def _winner_bets(
    mt: MarketType, market: UsMarket, bind: EventBind, draw_ids: frozenset[str],
) -> list[Bet]:
    """Two-team market → both teams; per-outcome market → its team or the draw."""
    long, short = market.long_side(), market.short_side()
    two_team = (
        long is not None and short is not None
        and long.team_id and short.team_id and long.team_id != short.team_id
    )
    if two_team:
        out: list[Bet] = [
            (mt.value, None, None, side)
            for side in (_side_team(long, bind), _side_team(short, bind))
            if side is not None
        ]
        return out if len(out) == 2 else []
    # Per-outcome group (``atc``): this market is one outcome, Yes = it happens.
    team = _one_team(market, bind)
    if team is not None:
        return [(mt.value, None, None, team)]
    if market.market_id in draw_ids and mt.shape is Shape.THREE_WAY:
        return [(mt.value, None, None, TIE_SIDE)]
    return []


def _spread_bets(mt: MarketType, market: UsMarket, bind: EventBind) -> list[Bet]:
    """Long team at the signed handicap; short team at its negation (half lines)."""
    long, short = market.long_side(), market.short_side()
    if long is None:
        return []
    signed = _signed_spread(market, long)
    long_team = _side_team(long, bind)
    if signed is None or long_team is None:
        return []
    out: list[Bet] = [(mt.value, None, signed, long_team)]
    short_team = _side_team(short, bind)
    # Integer handicap: the short side also wins the push — not one selection.
    if short_team is not None and short_team != long_team and _half_line(signed):
        out.append((mt.value, None, normalize_line(-signed), short_team))
    return out


def _half_line(line: float) -> bool:
    """x.5 cannot push, so the NO side of the contract is exactly one selection."""
    return abs(line) % 1 == 0.5


def _over_under(
    mt: MarketType, market: UsMarket, entity: str | None, line: float | None,
) -> list[Bet]:
    """Over/under at ``line``; the short side only at a half line.

    Sides must be exactly one over + one under. At an integer line the NO
    side also wins the push, so it is not Optic's under — only the long
    (paying) side is stamped there.
    """
    if line is None:
        return []
    out: list[Bet] = []
    for side in market.sides:
        direction = _direction(side.description)
        if direction is None:
            return []
        if side.long or _half_line(line):
            out.append((mt.value, entity, line, direction))
    directions = {_direction(s.description) for s in market.sides}
    return out if directions == {"over", "under"} else []


def _game_yn_bets(mt: MarketType, market: UsMarket) -> list[Bet]:
    """Game-wide Yes and No; the line is kept only for a line-bearing shape."""
    line = market.line if mt.shape is Shape.YES_NO_LINE else None
    out: list[Bet] = []
    for side in market.sides:
        yn = _yes_no(side.description)
        if yn is None:
            return []
        out.append((mt.value, None, line, yn))
    return out if {b[3] for b in out} == {"yes", "no"} else []


def _player_bets(mt: MarketType, market: UsMarket, kind: str) -> list[Bet]:
    """Player prop from ``metadata.playerName``: Yes only, or over/under at the line."""
    if not market.player_name:
        return []
    entity = normalize_player_name(market.player_name)
    if kind == "player_yn" or mt.shape is Shape.YES_NO:
        return [(mt.value, entity, None, "yes")]
    return _over_under(mt, market, entity, _player_line(market))


def _race_bets(
    mt: MarketType, market: UsMarket, bind: EventBind, draw_ids: frozenset[str],
) -> list[Bet]:
    """First to ``line``: the named team, or neither (tie) by elimination."""
    if market.line is None:
        return []
    team = _one_team(market, bind)
    if team is not None:
        return [(mt.value, None, market.line, team)]
    if market.market_id in draw_ids:
        return [(mt.value, None, market.line, TIE_SIDE)]
    return []


def market_bets(
    market: UsMarket,
    bind: EventBind,
    draw_ids: frozenset[str] = frozenset(),
) -> list[Bet]:
    """Every (market_type, entity, line, side) this market's symbol prices."""
    spec = smt_spec(market.sports_market_type)
    if spec is None:
        return []
    mt, kind = spec
    if kind == "winner":
        return _winner_bets(mt, market, bind, draw_ids)
    if kind == "spread":
        return _spread_bets(mt, market, bind)
    if kind == "total":
        return _over_under(mt, market, None, market.line)
    if kind == "team_total":
        team = _one_team(market, bind)
        return _over_under(mt, market, team, market.line) if team else []
    if kind == "team_outcome":
        team = _one_team(market, bind)
        if team is not None:
            return [(mt.value, None, None, team)]
        # "No team scores first" is the group's team-less member: the tie.
        if market.market_id in draw_ids and mt.shape is Shape.THREE_WAY:
            return [(mt.value, None, None, TIE_SIDE)]
        return []
    if kind == "game_yn":
        return _game_yn_bets(mt, market)
    if kind == "any_yn":
        # "At least one" is the 0.5 rung only; 1.5+ is a different bet.
        return _game_yn_bets(mt, market) if market.line == 0.5 else []
    if kind in ("player_ou", "player_yn"):
        return _player_bets(mt, market, kind)
    if kind == "race":
        return _race_bets(mt, market, bind, draw_ids)
    if kind in TITLE_KINDS:
        fx = bind.fixture
        names = {fx.home: fx.home_name, fx.away: fx.away_name}
        return title_bets(mt.value, market, bind.team_sides, kind, names)
    if kind == "at_least":
        line = market.line
        if line is None or line % 1:
            return []
        return _over_under(mt, market, None, normalize_line(line - 0.5))
    return []


def draw_market_ids(markets: Iterable[UsMarket]) -> frozenset[str]:
    """Team-less outcome of each per-outcome group (the draw / "neither").

    A 3-way group (``soccer_team_full_time_winner``, race-to-N at one line …)
    lists one market per outcome. Two name a team on their sides; the draw
    names none. The draw is identified by elimination — only when its group
    has exactly one team-less market beside exactly two distinct team markets.
    """
    groups: dict[tuple[str, str, float | None], list[UsMarket]] = {}
    for m in markets:
        groups.setdefault((m.event_id, m.sports_market_type, m.line), []).append(m)
    out: set[str] = set()
    for members in groups.values():
        teamless = [m for m in members if not any(s.team_id for s in m.sides)]
        team_ids = {
            s.team_id for m in members for s in m.sides if s.team_id
        }
        if len(teamless) == 1 and len(team_ids) == 2 and len(members) == 3:
            out.add(teamless[0].market_id)
    return frozenset(out)


def build_row(
    market: UsMarket, bind: EventBind, bet: Bet, league: str, side_yn: str | None = None,
) -> CanonicalRow:
    """Canonical row stamped with the market's symbol and the venue side it prices."""
    market_type, entity, line, side = bet[0], bet[1], bet[2], bet[3]
    grouping_key = bet[4] if len(bet) == 5 else None
    fx = bind.fixture
    return CanonicalRow(
        league=league,
        start_date=fx.start_date,
        home=fx.home,
        away=fx.away,
        market_type=market_type,
        entity=entity,
        line=line,
        side=side,
        grouping_key=grouping_key,
        polymarket_usa_market_id=market.slug,
        polymarket_usa_side=side_yn,
    )
