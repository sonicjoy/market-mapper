"""Stamp an Underdog catalogue onto Optic rows for one league.

Typed fields only: the Optic market id picks the canonical type, the Optic
fixture id says which league a contract belongs to, and the venue sentence
gives the teams, kickoff, YES side, line and player. The ticker is carried
through as the opaque RFQ key and is never parsed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path

from mappers.canonical_codes import names_fit, person_league
from mappers.exchanges import underdog_player_props
from mappers.exchanges.underdog import (
    UnderdogConfig,
    UnderdogContract,
    build_rows,
    needs_team,
    parse_contract,
    sentence_player,
)
from mappers.exchanges.underdog_udx_optic_witness import check_udx_optic_witness
from mappers.market_types import MarketType
from mappers.shared import CanonicalRow, normalize_player_name, parse_iso_datetime
from mappers.sport import Sport, sport_for_league
from mappers.team_side import team_side
from mappers.vocab.underdog_markets import UNDERDOG_BLOCKED_CLAUSES, UNDERDOG_BLOCKED_SERIES

Attach = Callable[..., str]

# Polymarket's kickoff window: a same-matchup series sits ~24h apart and a
# doubleheader ~6h, so 2h separates siblings. UDX "originally scheduled"
# for tennis and UFC is an order-of-play estimate that drifts for hours,
# and the same two people do not meet twice in a day. Tennis starts can
# also be placeholders a day or more off (adding-underdog.md item 11), so
# a person pair falls back to the only fixture within 3 days.
_TEAM_TOLERANCE = timedelta(hours=2)
_PERSON_TOLERANCE = timedelta(hours=6)
_PERSON_FALLBACK = timedelta(days=3)
# A same-pair fixture this close is a doubleheader or series game, where
# UDX's own Optic id has been swapped; kickoff must then agree with the id.
_SIBLING_WINDOW = timedelta(hours=36)

_SERIES_SPLIT_RE = re.compile(r"[_-]")

_TALLY_KEYS = (
    "stamped",
    "other_league",
    "closed",
    "blocked",
    "unparsed",
    "unmapped",
    "no_fixture",
    "no_side",
    "basis_unstated",
    "dropped",
    "optic_fixture",
    "optic_team",
    "optic_player",
    "unconfirmed",
)


# legacy: ticker parse — replace with the typed venue field, do not extend
def series_of(ticker: str) -> str:
    """UDX's series: the ticker text before the first underscore or hyphen."""
    return _SERIES_SPLIT_RE.split(ticker, maxsplit=1)[0]


def is_blocked(row: Mapping) -> bool:
    """True for a blocked series or a sentence with a blocked clause."""
    if series_of(str(row.get("ticker") or "")) in UNDERDOG_BLOCKED_SERIES:
        return True
    description = str(row.get("description") or "").casefold()
    return any(clause in description for clause in UNDERDOG_BLOCKED_CLAUSES)


def read_catalogue(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sides_align(sides: tuple[str, str], fx, *, player: bool) -> bool | None:
    """True when the sentence order is Optic away/home, False when crossed, None when no fit."""
    away, home = sides
    if names_fit(away, fx.away_name, player=player) and names_fit(home, fx.home_name, player=player):
        return True
    if names_fit(away, fx.home_name, player=player) and names_fit(home, fx.away_name, player=player):
        return False
    return None


def _match_fixture(sides: tuple[str, str], start: datetime, entries: list, *, player: bool):
    """Nearest name-matched fixture inside the kickoff window; a tie is ambiguous.

    A person pair with nothing in the window takes the only fixture within
    ``_PERSON_FALLBACK``; two or more there is ambiguous too.
    """
    window = (_PERSON_TOLERANCE if player else _TEAM_TOLERANCE).total_seconds()
    scored = sorted(
        (abs((parse_iso_datetime(str(entry.fixture.start_date)) - start).total_seconds()), i)
        for i, entry in enumerate(entries)
        if _sides_align(sides, entry.fixture, player=player) is not None
    )
    inside = [(delta, i) for delta, i in scored if delta <= window]
    if inside:
        if len(inside) > 1 and inside[0][0] == inside[1][0]:
            return None
        return entries[inside[0][1]]
    if not player:
        return None
    wide = [i for delta, i in scored if delta <= _PERSON_FALLBACK.total_seconds()]
    return entries[wide[0]] if len(wide) == 1 else None


def _yes_side(contract: UnderdogContract, fx) -> str:
    """Fixture code of the team the sentence puts YES on, or "" unless exactly one fits."""
    if not contract.yes_team:
        return ""
    return (
        team_side(
            contract.yes_team,
            home=fx.home,
            away=fx.away,
            home_name=str(getattr(fx, "home_name", "") or ""),
            away_name=str(getattr(fx, "away_name", "") or ""),
        )
        or ""
    )


def _player_entity(contract: UnderdogContract) -> str | None:
    """Sentence player normalized like Optic's entity, so row_key matches.

    Optic and Kalshi key player props on ``normalize_player_name``
    (``brock_purdy``); the raw sentence name (``Brock Purdy``) never merges.
    """
    name = sentence_player(contract.description)
    return normalize_player_name(name) if name else None


def _resolve_fixture(
    contract: UnderdogContract,
    entries: list,
    by_id: dict,
    league: str,
    matches: dict,
):
    """Entry for the contract: the fixture UDX's own Optic id names, both names permitting.

    The id is the join; kickoff only arbitrates a same-pair sibling within
    ``_SIBLING_WINDOW`` (an MLB doubleheader, where UDX once swapped the ids,
    adding-underdog.md item 13): the sentence kickoff, else the ``expires_at``
    kickoff, picks the game, and the witness rejects and alerts when that is
    not the id-named one. A row
    whose id names no fixture of this league falls back to name + kickoff.
    """
    player = person_league(league)
    entry = by_id.get(contract.fixture_id)
    if entry is not None:
        if _sides_align(contract.sides, entry.fixture, player=player) is None:
            return None
        # Every contract of an event asks the same question: answer it once per run.
        key = ("siblings", contract.sides, contract.fixture_id)
        if key not in matches:
            matches[key] = _siblings(contract.sides, entry, entries, player=player)
        if not matches[key]:
            return entry
        return _kickoff_pick(contract, entries, matches, player=player)
    if contract.start is None:
        return None
    return _match_by_kickoff(contract.sides, contract.start, entries, matches, player=player)


def _siblings(sides: tuple[str, str], entry, entries: list, *, player: bool) -> bool:
    """True when another fixture of the same pair starts within ``_SIBLING_WINDOW``."""
    start = parse_iso_datetime(str(entry.fixture.start_date))
    return any(
        other is not entry
        and abs((parse_iso_datetime(str(other.fixture.start_date)) - start).total_seconds())
        <= _SIBLING_WINDOW.total_seconds()
        and _sides_align(sides, other.fixture, player=player) is not None  # names last: the costly test
        for other in entries
    )


def _kickoff_pick(contract: UnderdogContract, entries: list, matches: dict, *, player: bool):
    """Fixture the sentence kickoff, else the expiry kickoff, picks; None when neither does."""
    for start in (contract.start, contract.expiry_kickoff):
        if start is None:
            continue
        picked = _match_by_kickoff(contract.sides, start, entries, matches, player=player)
        if picked is not None:
            return picked
    return None


def _match_by_kickoff(sides: tuple[str, str], start: datetime, entries: list, matches: dict, *, player: bool):
    key = (sides, start)
    if key not in matches:
        matches[key] = _match_fixture(sides, start, entries, player=player)
    return matches[key]


# Soccer lines whose Optic id is shared across competitions settle on the first
# half or the 90 minutes, as Optic's. The sentence must state that basis, so a
# listing that counts extra time under the same id maps nothing.
_REGULATION_RE = re.compile(r"during (?:regulation time|the entire game excluding extra time)")
_SOCCER_STATED_BASIS: dict[MarketType, re.Pattern[str]] = {
    MarketType.FIRST_HALF_BTTS: re.compile(r"during the first half"),
    MarketType.TEAM_TOTAL: _REGULATION_RE,
    MarketType.TOTAL_CORNERS: _REGULATION_RE,
    MarketType.TEAM_TOTAL_CORNERS: _REGULATION_RE,
    # Ligue 1 reads "the score of the entire game excluding extra time".
    MarketType.CORRECT_SCORE: re.compile(r"(?:during|score of) the entire game excluding extra time"),
}


# UDXBRASILASCORE's sentence names no basis; its rules do ("during the entire game
# excluding extra time ... Goals outside ... do not count"). Exact score may take the
# basis from the rules, but only when the sentence says nothing about extra time.
_BASIS_IN_RULES = frozenset({MarketType.CORRECT_SCORE})
_BASIS_WORDS_RE = re.compile(r"extra time|regulation|overtime", re.IGNORECASE)


def soccer_basis_stated(mt: MarketType, description: str, league: str, rules: str = "") -> bool:
    """False for a soccer contract whose sentence (or, for exact score, rules) states no basis."""
    pattern = _SOCCER_STATED_BASIS.get(mt)
    if pattern is None or sport_for_league(league) is not Sport.SOCCER:
        return True
    if pattern.search(description) is not None:
        return True
    if mt not in _BASIS_IN_RULES or _BASIS_WORDS_RE.search(description):
        return False
    return pattern.search(rules) is not None


# Basketball half lines take their period from UDX's Optic id alone. NBA and WNBA
# sentences say "during the first half"; NCAA's GAMEWIN1H says "in the ... game"
# (2026-10-30), so a half line maps only when its sentence names the half.
_BASKETBALL_FIRST_HALF = frozenset({
    MarketType.FIRST_HALF_POINT_SPREAD,
    MarketType.FIRST_HALF_TOTAL,
    MarketType.FIRST_HALF_TEAM_TOTAL,
})


def basketball_basis_stated(mt: MarketType, description: str, league: str) -> bool:
    """False for a basketball half line whose sentence does not say "during the first half"."""
    if mt not in _BASKETBALL_FIRST_HALF or sport_for_league(league) is not Sport.BASKETBALL:
        return True
    return "during the first half" in description


def _built_rows(
    contract: UnderdogContract,
    mt,
    row: dict,
    entries: list,
    by_id: dict,
    league: str,
    matches: dict,
    *,
    player_id_market: bool = False,
) -> tuple[list[CanonicalRow], str, str]:
    """Rows for one contract, or (``[]``, tally reason, alert line).

    A ``player_id_market`` contract takes its player from ``underdog_player_props``
    (whole sentence + the venue's player id) and maps nothing when they disagree.
    """
    if not basketball_basis_stated(mt, contract.description, league):
        return [], "basis_unstated", ""
    entry = _resolve_fixture(contract, entries, by_id, league, matches)
    if entry is None:
        return [], "no_fixture", ""
    fx = entry.fixture
    if not soccer_basis_stated(mt, contract.description, league, contract.rules):
        return [], "basis_unstated", ""
    team = _yes_side(contract, fx)
    if needs_team(mt) and not team and not contract.is_draw:
        return [], "no_side", ""
    player = _player_entity(contract)
    if player_id_market:
        check = underdog_player_props.confirm_player(contract, row, fx)
        if check.entity is None:
            return [], check.reason, check.alert
        player = check.entity
    built = build_rows(
        contract,
        mt,
        home=fx.home,
        away=fx.away,
        start_date=fx.start_date,
        league=league,
        team=team or None,
        player_name=player,
    )
    if not built:
        return [], "dropped", ""
    witness = check_udx_optic_witness(row, fx, built)
    if witness.reject:
        return [], witness.reject, witness.reject_line
    return built, "", ""


def _pass_catalogue_row(
    row: dict,
    *,
    cfg: UnderdogConfig,
    by_id: dict,
    entries: list,
    league: str,
    matches: dict,
    tally: dict[str, int],
    attach: Attach,
    row_index: dict,
    alt: dict,
    all_rows: list[CanonicalRow],
    witness_reject_alerts: list[str] | None,
) -> None:
    if str(row.get("status") or "open") != "open":
        tally["closed"] += 1
        return
    if is_blocked(row):
        tally["blocked"] += 1
        return
    contract = parse_contract(row)
    if contract is None:
        tally["unparsed"] += 1
        return
    if contract.fixture_id not in by_id:
        tally["other_league"] += 1
        return
    mt = cfg.market_type(contract)
    if mt is None:
        tally["unmapped"] += 1
        return
    built, reason, reject_line = _built_rows(
        contract,
        mt,
        row,
        entries,
        by_id,
        league,
        matches,
        player_id_market=contract.market_id in cfg.player_id_markets,
    )
    if reason:
        tally[reason] += 1
        if reject_line and witness_reject_alerts is not None:
            witness_reject_alerts.append(reject_line)
        return
    for item in built:
        if attach(row_index, alt, all_rows, item) == "stamped":
            tally["stamped"] += 1


def run_pass(
    catalogue: list[dict],
    cfg: UnderdogConfig,
    entries: list,
    *,
    league: str,
    attach: Attach,
    row_index: dict,
    all_rows: list[CanonicalRow],
    witness_reject_alerts: list[str] | None = None,
) -> dict[str, int]:
    by_id = {str(entry.fixture.fixture_id): entry for entry in entries}
    alt: dict[tuple[tuple, str], CanonicalRow] = {}
    matches: dict = {}
    tally: dict[str, int] = dict.fromkeys(_TALLY_KEYS, 0)
    for row in catalogue:
        _pass_catalogue_row(
            row,
            cfg=cfg,
            by_id=by_id,
            entries=entries,
            league=league,
            matches=matches,
            tally=tally,
            attach=attach,
            row_index=row_index,
            alt=alt,
            all_rows=all_rows,
            witness_reject_alerts=witness_reject_alerts,
        )
    return tally
