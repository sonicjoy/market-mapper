"""Compare UDX ``external_ids.optic_odds`` to our name+kickoff stamp.

Fixture ids reject when present and disagree. Team and player ids reject only
when they resolve to a **different** side or player than our YES row — unknown
ids are ignored (Optic competitor records often differ from fixture ids; see
``optic._odds_team_aliases``). The market id needs no check here: it is what
picks the canonical type, so market and period cannot disagree with it.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from BigQuery.alerts import AlertPublisher, build_publisher
from mappers.canonical_codes import names_fit
from mappers.exchanges.optic import Odd
from mappers.exchanges.underdog import optic_block
from mappers.market_types import MarketType
from mappers.shared import CanonicalRow, normalize_player_name


@dataclass
class UdxOpticWitness:
    """Outcome of comparing one catalogue row to the matched Optic fixture."""

    reject: str = ""
    reject_line: str = ""


def _yes_row(built: list[CanonicalRow]) -> CanonicalRow | None:
    for item in built:
        if item.underdog_side == "yes":
            return item
    return None


def _team_side_for_id(fx, team_id: str) -> str | None:
    """Fixture side abbrev for a UDX team_id, or None when unknown."""
    mapped = fx.team_map.get(team_id)
    return mapped if mapped else None


def _expected_team_abbrev(yes: CanonicalRow, fx) -> str | None:
    """Team abbrev our YES row names, when the contract is team-scoped."""
    if yes.side in {fx.home, fx.away}:
        return yes.side
    if yes.side in {"over", "under"} and yes.entity in {fx.home, fx.away}:
        return yes.entity
    if yes.market_type == MarketType.WINNING_MARGIN.value and yes.entity in {fx.home, fx.away}:
        return yes.entity
    return None


def _player_name_for_id(fx, player_id: str) -> str | None:
    """Display name Optic attaches to a player_id on this fixture, if any."""
    for odd in fx.odds:
        if not isinstance(odd, Odd):
            continue
        if str(odd.player_id or "") != player_id:
            continue
        return (odd.selection or odd.name or "").strip() or None
    if player_id in fx.team_map:
        return fx.team_map[player_id]
    return None


def _player_disagrees(fx, player_id: str, yes: CanonicalRow) -> bool:
    """True when player_id resolves to someone other than our YES entity/side."""
    if yes.side in {fx.home, fx.away}:
        if player_id not in fx.team_map:
            return False
        return fx.team_map[player_id] != yes.side
    if yes.entity and yes.entity in {fx.home, fx.away}:
        return _fighter_disagrees(fx, player_id, yes.entity)
    entity = (yes.entity or "").strip()
    if not entity:
        return False
    name = _player_name_for_id(fx, player_id)
    if name is None:
        return False
    if normalize_player_name(name) == entity:
        return False
    return not names_fit(name, entity, player=True)


def _fighter_disagrees(fx, player_id: str, side: str) -> bool:
    """A fighter-scoped yes row (method of victory) keys its fighter by the
    fixture side code, like Optic's own rows: compare Optic's name for the
    player_id with the fixture's full name for that side."""
    name = _player_name_for_id(fx, player_id)
    if name is None:
        return False
    if name in {fx.home, fx.away}:  # team_map fallback gives the side code
        return name != side
    name = name.split(" - ", 1)[0]  # "Fighter - Method" outcome names
    full = fx.home_name if side == fx.home else fx.away_name
    return not names_fit(name, full, player=True)


def _witness_fixture(
    oo: Mapping[str, Any], fx, ticker_raw: str,
) -> UdxOpticWitness | None:
    their_fixture = str(oo.get("fixture_id") or "").strip()
    if their_fixture and their_fixture != str(fx.fixture_id):
        return UdxOpticWitness(
            reject="optic_fixture",
            reject_line=(
                f"{ticker_raw}: UDX fixture_id={their_fixture!r} "
                f"ours={fx.fixture_id!r}"
            ),
        )
    return None


def _witness_team_player(
    oo: Mapping[str, Any], fx, yes: CanonicalRow, ticker_raw: str,
) -> UdxOpticWitness | None:
    their_team = str(oo.get("team_id") or "").strip()
    expected_team = _expected_team_abbrev(yes, fx)
    if their_team and expected_team:
        mapped = _team_side_for_id(fx, their_team)
        if mapped is not None and mapped != expected_team:
            return UdxOpticWitness(
                reject="optic_team",
                reject_line=(
                    f"{ticker_raw}: UDX team_id maps to {mapped!r} "
                    f"expected {expected_team!r}"
                ),
            )
    their_player = str(oo.get("player_id") or "").strip()
    if their_player and _player_disagrees(fx, their_player, yes):
        return UdxOpticWitness(
            reject="optic_player",
            reject_line=f"{ticker_raw}: UDX player_id disagrees with our YES row",
        )
    return None


def check_udx_optic_witness(
    row: dict[str, Any],
    fx,
    built: list[CanonicalRow],
) -> UdxOpticWitness:
    """Reject on fixture, team or player disagreement."""
    oo = optic_block(row)
    ticker_raw = str(row.get("ticker") or "")
    if not oo:
        return UdxOpticWitness()

    hit = _witness_fixture(oo, fx, ticker_raw)
    if hit is not None:
        return hit

    yes = _yes_row(built)
    if yes is None:
        return UdxOpticWitness()

    hit = _witness_team_player(oo, fx, yes, ticker_raw)
    return hit if hit is not None else UdxOpticWitness()


def format_witness_alert(league: str, *, reject_lines: list[str], limit: int = 8) -> str:
    """One Slack body for a league tick."""
    lines = [
        f"Underdog UDX optic witness [{league}]",
        f"{len(reject_lines)} reject(s) (stamp withheld)",
        *reject_lines[:limit],
    ]
    if len(reject_lines) > limit:
        lines.append(f"(+{len(reject_lines) - limit} more rejects)")
    return "\n".join(lines)


def publish_udx_witness_alerts(
    league: str,
    reject_alerts: list[str],
    *,
    alert_publisher: AlertPublisher | None = None,
) -> None:
    """Publish one warning when rejects were collected."""
    if not reject_alerts:
        return
    own_publisher = alert_publisher is None
    publisher = alert_publisher or build_publisher()
    try:
        if not publisher.routable:
            print(
                f"  underdog [{league}]: optic witness alerts not routable "
                f"({len(reject_alerts)} reject)",
                file=sys.stderr,
            )
            return
        publisher.publish(
            "warning", format_witness_alert(league, reject_lines=reject_alerts),
        )
    except Exception:
        print(
            f"  underdog [{league}]: optic witness alert publish failed",
            file=sys.stderr,
        )
    finally:
        if own_publisher:
            publisher.close()
