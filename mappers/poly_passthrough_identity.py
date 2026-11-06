"""Drop Optic Polymarket passthrough ids whose own question names someone else.

OpticOdds stamps ``source_ids["Polymarket"]`` onto its own odds, and
``load_mappings`` emits that id verbatim.  Optic has attached one player's
ladder to another player on the same fixture (Pumas-Atletico de San Luis
2026-09-27: "Nathan Silva: 1+ goals + assists" on Jordan Silva) and one
game's corners token to another game (Canadian Premier League "Inter Toronto
FC vs. Pacific FC" on York United-Inter Toronto).  The Polymarket bridge
carries the token's own question, so identity is checked against it here
before the passthrough can be emitted.

Missing > wrong, but only on positive evidence: a token absent from the
bridge, or a question with no parseable player or matchup, keeps its
passthrough.  Fixture mismatches additionally require the question's two
teams to resolve to exactly one *other* fixture in the run, because Optic's
team names drift from Polymarket's far more often than Optic is wrong.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mappers.canonical_codes import names_fit
from mappers.exchanges import polymarket
from mappers.exchanges.optic import Fixture, Odd
from mappers.shared import CanonicalRow, normalize_player_name
from mappers.snapshot_index import SnapshotIndex

POLY_BOOK = "Polymarket"
_VS = re.compile(r"\s*(.+?)\s+vs\.?\s+(.+?)\??\s*", re.I)

Mismatch = Literal["player", "fixture"]


@dataclass
class IdentityStats:
    """Per-league counts for the stderr summary line."""

    verified: int = 0
    unverified: int = 0
    dropped_player: int = 0
    dropped_fixture: int = 0


_BRIDGE_KEY: tuple[str, ...] | None = None
_BRIDGE: dict[str, polymarket.PolyMarket] = {}


def bridge_by_clob(
    data_dir: Path, snapshot: SnapshotIndex | None,
) -> dict[str, polymarket.PolyMarket]:
    """Every bridge market keyed by each of its outcome clob tokens.

    Built once per snapshot (or per file mtime) and reused across leagues:
    the bridge carries every slug prefix, not just the pinned ones, so a
    league with no official Polymarket pin is still checked.
    """
    global _BRIDGE_KEY, _BRIDGE
    path = data_dir / "polymarket_markets.jsonl"
    if snapshot is not None:
        key: tuple[str, ...] = ("snapshot", snapshot.snapshot_id)
        lines: Iterable[str] = snapshot.polymarket_lines
    elif path.is_file():
        key = ("file", str(path), str(path.stat().st_mtime_ns))
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        return {}
    if key == _BRIDGE_KEY:
        return _BRIDGE
    index: dict[str, polymarket.PolyMarket] = {}
    for line in lines:
        market = polymarket.parse_market(line) if line.strip() else None
        if market is None:
            continue
        for outcome in market.outcomes:
            index[outcome.clob_token_id] = market
    _BRIDGE_KEY, _BRIDGE = key, index
    return index


def question_player(question: str) -> str | None:
    """The player a "<Player>: <stat>" question is about, else None."""
    head, sep, _ = (question or "").partition(":")
    head = head.strip()
    if not sep or not head or _VS.fullmatch(head):
        return None
    return head


def question_teams(question: str) -> tuple[str, str] | None:
    """The first "<A> vs. <B>" segment of a colon-separated question."""
    for part in (question or "").split(":"):
        m = _VS.fullmatch(part)
        if m:
            return m.group(1), m.group(2)
    return None


def _spaced(name: str) -> str:
    return normalize_player_name(name).replace("_", " ")


def player_fits(
    poly_name: str,
    optic_selection: str,
    entity: str | None,
    aliases: Mapping[str, str],
) -> bool:
    """Same person under the parser's own identity, names_fit, or a tip alias."""
    key = normalize_player_name(poly_name)
    if key and (key == entity or key == normalize_player_name(optic_selection)):
        return True
    if entity is not None and aliases.get(key) == entity:
        return True
    return names_fit(_spaced(poly_name), _spaced(optic_selection), player=True)


class FixtureNames:
    """Each fixture's competitor names, normalized once per league."""

    def __init__(self, fixtures: Sequence[Fixture], style: str) -> None:
        self.style = style
        self._names = {
            fx.game_id: (
                polymarket._norm_name(fx.home_name, style),
                polymarket._norm_name(fx.away_name, style),
            )
            for fx in fixtures
        }
        self._memo: dict[tuple[str, str, str], bool] = {}

    def _has(self, game_id: str, a: str, b: str) -> bool:
        home, away = self._names[game_id]

        def hit(x: str, y: str) -> bool:
            return polymarket._name_match(x, y, self.style)

        return (hit(a, home) and hit(b, away)) or (hit(a, away) and hit(b, home))

    def names_other_fixture(self, teams: tuple[str, str], own_game: str) -> bool:
        """True when both teams match exactly one fixture, and it is not ours."""
        a = polymarket._norm_name(teams[0], self.style)
        b = polymarket._norm_name(teams[1], self.style)
        key = (a, b, own_game)
        if key not in self._memo:
            if own_game in self._names and self._has(own_game, a, b):
                self._memo[key] = False
            else:
                hits = [g for g in self._names if g != own_game and self._has(g, a, b)]
                self._memo[key] = len(hits) == 1
        return self._memo[key]


def identity_mismatch(
    row: CanonicalRow,
    odd: Odd,
    question: str,
    fixture_names: FixtureNames,
    *,
    player_types: frozenset[str],
    player_aliases: Mapping[str, str],
) -> Mismatch | None:
    """Why this Optic odd cannot carry this Polymarket question, if it cannot."""
    if row.market_type in player_types:
        name = question_player(question)
        if name is None:
            return None
        if player_fits(name, odd.selection, row.entity, player_aliases):
            return None
        return "player"
    teams = question_teams(question)
    if teams is None:
        return None
    own_game = odd.id.split(":", 1)[0]
    return "fixture" if fixture_names.names_other_fixture(teams, own_game) else None


def _passthrough_clob(odd: Odd | None) -> str | None:
    src = (odd.source_ids or {}).get(POLY_BOOK) if odd is not None else None
    clob = src.get("selection_id") if isinstance(src, dict) else None
    return str(clob) if clob else None


def _drop(odd: Odd, clob: str, question: str, reason: Mismatch,
          stats: IdentityStats, league: str) -> None:
    odd.source_ids = {k: v for k, v in odd.source_ids.items() if k != POLY_BOOK}
    if reason == "player":
        stats.dropped_player += 1
        shown = odd.selection
    else:
        stats.dropped_fixture += 1
        shown = odd.id.split(":", 1)[0]
    print(
        f"  polymarket [{league}] passthrough identity: dropping clob {clob} "
        f"({reason}): Optic {shown!r} vs question {question!r}",
        file=sys.stderr,
    )


def drop_mismatched_passthroughs(
    rows: Iterable[CanonicalRow],
    odd_lookup: Mapping[str, Odd],
    bridge: Mapping[str, polymarket.PolyMarket],
    fixtures: Sequence[Fixture],
    *,
    league: str,
    player_types: frozenset[str],
    player_aliases: Mapping[str, str],
    style: str,
) -> IdentityStats:
    """Remove ``source_ids["Polymarket"]`` from odds whose question disagrees.

    Mutates the Optic odd so neither guard #4's index nor ``load_mappings``
    ever sees the wrong token; the matcher may then stamp that token onto the
    row it really belongs to.
    """
    stats = IdentityStats()
    fixture_names = FixtureNames(fixtures, style)
    seen: set[str] = set()
    for row in rows:
        if row.optic_id is None or row.optic_id in seen:
            continue
        seen.add(row.optic_id)
        odd = odd_lookup.get(row.optic_id)
        clob = _passthrough_clob(odd)
        if odd is None or clob is None:
            continue
        market = bridge.get(clob)
        if market is None:
            stats.unverified += 1
            continue
        reason = identity_mismatch(
            row, odd, market.question, fixture_names,
            player_types=player_types, player_aliases=player_aliases,
        )
        if reason is None:
            stats.verified += 1
        else:
            _drop(odd, clob, market.question, reason, stats, league)
    return stats
