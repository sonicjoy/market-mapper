"""Shared parser-profile build helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.crypto_esports import esports_crypto_config
from mappers.exchanges.crypto_soccer import soccer_crypto_config
from mappers.exchanges.crypto_tennis import (
    TENNIS_ALSO_LEAGUES,
    TENNIS_META_LEAGUE_BY_SLUG,
    tennis_crypto_config,
)
from mappers.exchanges.novig import NovigConfig
from mappers.exchanges.optic import OpticConfig
from mappers.exchanges.polymarket import PolymarketConfig
from mappers.exchanges.px import PxConfig
from mappers.exchanges.runshop import RunshopConfig
from mappers.exchanges.runshop_vendor import DEFAULT_MARKETS_PATH
from mappers.exchanges.underdog import UnderdogConfig
from mappers.market_types import MarketType
from mappers.profiles.types import LeagueBuildContext
from mappers.sport import Sport
from mappers.vocab.baseball_markets import baseball_crypto_config
from mappers.vocab.basketball_markets import basketball_crypto_config
from mappers.vocab.football_markets import football_crypto_config
from mappers.vocab.hockey_markets import hockey_crypto_config
from mappers.vocab.underdog_markets import market_types_for_sport, player_id_markets_for_sport


def apply_crypto_tip_settings(
    base: CryptoConfig,
    settings: Mapping[str, Any],
) -> CryptoConfig:
    """Overlay tip exchange settings onto a built crypto.com config."""
    kwargs: dict[str, Any] = {}
    if settings.get("sport_grouping"):
        kwargs["sport_grouping"] = str(settings["sport_grouping"])
    if settings.get("league"):
        kwargs["league"] = str(settings["league"])
    if settings.get("period_type"):
        kwargs["period_type"] = str(settings["period_type"])
    extra_contracts = settings.get("extra_contract_types")
    if extra_contracts:
        merged = dict(base.contract_types)
        for name, mt in extra_contracts.items():
            merged[str(name)] = MarketType(str(mt))
        kwargs["contract_types"] = merged
    period_overrides = settings.get("contract_period_types")
    if period_overrides:
        kwargs["contract_period_types"] = {
            **base.contract_period_types,
            **{str(k): str(v) for k, v in period_overrides.items()},
        }
    return replace(base, **kwargs) if kwargs else base


@dataclass(frozen=True)
class OpticStandardProfile:
    """optic_standard_v1: Optic table types for one sport."""

    profile_id: str
    sportsbook: str
    sport: Sport
    table_types: Mapping[str, MarketType]

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> OpticConfig:
        """Build Optic config from league context."""
        _ = settings
        return OpticConfig(
            league_id=ctx.optic_league_id,
            table_types=dict(self.table_types),
            horizon_hours=ctx.fixture_horizon_hours,
            extra_league_ids=ctx.extra_optic_league_ids,
        )


@dataclass(frozen=True)
class PolyGenericProfile:
    """poly_generic_v1: sport-specific Polymarket recognizers."""

    profile_id: str
    sportsbook: str
    sport: Sport
    market_types: Mapping[str, MarketType]
    market_rules: Any
    team_name_aliases: Mapping[str, str] = field(default_factory=dict)
    aliases_leagues: frozenset[str] | None = None

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> PolymarketConfig | None:
        """Build Polymarket config when slug_prefix is set."""
        slug = str(settings.get("slug_prefix") or "").strip()
        if not slug:
            return None
        optic = str(settings.get("optic_league_id") or ctx.optic_league_id or "").strip()
        style = settings.get("question_style")
        aliases: dict[str, str] = {}
        if self.team_name_aliases and (
            self.aliases_leagues is None or ctx.league in self.aliases_leagues
        ):
            aliases = dict(self.team_name_aliases)
        return PolymarketConfig(
            slug_prefix=slug,
            optic_league_id=optic,
            market_types=dict(self.market_types),
            question_style=style or "mlb_suffix",
            market_rules=self.market_rules,
            team_name_aliases=aliases,
        )


@dataclass(frozen=True)
class PxGenericProfile:
    """px_generic_v1: PX tournament id from tip settings."""

    profile_id: str
    sportsbook: str
    sport: Sport

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> PxConfig | None:
        """Build PX config when tournament_id is present."""
        _ = ctx
        tid = settings.get("tournament_id")
        if tid is None:
            return None
        return PxConfig(tournament_id=int(tid), exact={}, suffix=[])


@dataclass(frozen=True)
class CryptoGenericProfile:
    """crypto_generic_v1: crypto.com meta league from tip settings."""

    profile_id: str
    sportsbook: str
    sport: Sport

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> CryptoConfig | None:
        """Build crypto.com config from tip sport_grouping settings."""
        _ = ctx
        league = str(settings.get("league") or "").strip()
        grouping = str(settings.get("sport_grouping") or "").strip()
        if not league or not grouping:
            return None
        if grouping == "ESPORT":
            return esports_crypto_config(league)
        if grouping == "TENNIS":
            return tennis_crypto_config(
                TENNIS_META_LEAGUE_BY_SLUG.get(ctx.league, league), settings,
                TENNIS_ALSO_LEAGUES.get(ctx.league, ()))
        if self.sport is Sport.BASKETBALL:
            return basketball_crypto_config(league, settings)
        if self.sport is Sport.BASEBALL:
            return baseball_crypto_config(league, settings)
        if self.sport is Sport.FOOTBALL:
            return football_crypto_config(league, settings)
        if self.sport is Sport.HOCKEY:
            return hockey_crypto_config(league, settings)
        if self.sport is Sport.SOCCER:
            return apply_crypto_tip_settings(soccer_crypto_config(league), settings)
        period = str(settings.get("period_type") or "Full-Game")
        return CryptoConfig(
            sport_grouping=grouping,
            league=league,
            period_type=period,
            contract_types={"Moneyline": MarketType.MONEYLINE},
        )


@dataclass(frozen=True)
class NovigGenericProfile:
    """novig_generic_v1: shared Novig market vocabulary for one sport."""

    profile_id: str
    sportsbook: str
    sport: Sport
    market_types: Mapping[str, MarketType]
    ignored_types: frozenset[str] = frozenset()

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> NovigConfig | None:
        """Build Novig config when league name is present."""
        _ = ctx
        league = str(settings.get("league") or "").strip()
        if not league:
            return None
        return NovigConfig(
            league=league,
            market_types=dict(self.market_types),
            ignored_types=self.ignored_types,
        )


@dataclass(frozen=True)
class RunshopGenericProfile:
    """runshop_generic_v1: Runshop vendor paths from tip exchange settings."""

    profile_id: str
    sportsbook: str
    sport: Sport

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> RunshopConfig | None:
        """Build Runshop config when enabled in tip settings."""
        _ = ctx
        if not settings.get("enabled", True):
            return None
        markets_raw = str(settings.get("markets_path") or DEFAULT_MARKETS_PATH)
        crosswalk_raw = settings.get("crosswalk_path")
        return RunshopConfig(
            markets_path=Path(markets_raw),
            crosswalk_path=Path(str(crosswalk_raw)) if crosswalk_raw else None,
        )


@dataclass(frozen=True)
class CryptoMmaProfile:
    """crypto_mma_v1: crypto.com MMA fight-line vocabulary."""

    profile_id: str
    sportsbook: str
    sport: Sport

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> CryptoConfig | None:
        """Build crypto.com config for MMA grouping only."""
        _ = ctx
        league = str(settings.get("league") or "").strip()
        if not league or str(settings.get("sport_grouping") or "") != "MMA":
            return None
        return CryptoConfig(
            sport_grouping="MMA",
            league=league,
            period_type=str(settings.get("period_type") or "Full Fight"),
            contract_types={"Moneyline": MarketType.MONEYLINE},
            # Method of Victory / Finish stay omitted: crypto buckets are not
            # verified like-for-like with Kalshi (KO/TKO vs KO/TKO/DQ).
            game_prop_contract_types={
                "Round of Victory": MarketType.ROUND_BETTING,
                "Round of Finish": MarketType.ROUND_BETTING,
                "Fight To Go The Distance": MarketType.FIGHT_GOES_DISTANCE,
            },
            game_prop_period_type="Full Fight",
            game_prop_accept_round_periods=bool(
                settings.get("game_prop_accept_round_periods", True)
            ),
        )


@dataclass(frozen=True)
class PolyUfcProfile:
    """poly_ufc_v1: UFC Polymarket recognizers + fighter name aliases."""

    profile_id: str
    sportsbook: str
    sport: Sport
    market_types: Mapping[str, MarketType]
    market_rules: Any
    team_name_aliases: Mapping[str, str]

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> PolymarketConfig | None:
        """Build Polymarket config when slug_prefix is set."""
        slug = str(settings.get("slug_prefix") or "").strip()
        if not slug:
            return None
        optic = str(settings.get("optic_league_id") or ctx.optic_league_id or "").strip()
        style = settings.get("question_style")
        return PolymarketConfig(
            slug_prefix=slug,
            optic_league_id=optic,
            market_types=dict(self.market_types),
            question_style=style or "tennis_prefix",
            market_rules=self.market_rules,
            team_name_aliases=dict(self.team_name_aliases),
        )


@dataclass(frozen=True)
class UnderdogGenericProfile:
    """underdog_generic_v1: the sport's UDX crosswalk, keyed on Optic market ids."""

    profile_id: str
    sportsbook: str
    sport: Sport

    def build(
        self,
        settings: Mapping[str, Any],
        ctx: LeagueBuildContext,
    ) -> UnderdogConfig | None:
        """Build when a league label is given; the table comes from the sport."""
        _ = ctx
        league = str(settings.get("league") or "").strip().upper()
        if not league:
            return None
        return UnderdogConfig(
            league=league,
            market_types=market_types_for_sport(self.sport),
            player_id_markets=player_id_markets_for_sport(self.sport),
        )


def exchange_settings(ex: Mapping[str, Any], sportsbook: str) -> dict[str, Any]:
    """Normalize tip exchange settings, including source_league_id fallbacks."""
    settings = dict(ex.get("settings") or {})
    if sportsbook == "polymarket_usa" and not settings.get("slug_prefix"):
        src = ex.get("source_league_id")
        if src:
            settings["slug_prefix"] = src
    if sportsbook == "novig" and not settings.get("league"):
        src = ex.get("source_league_id")
        if src:
            settings["league"] = src
    if sportsbook == "crypto.com" and not settings.get("league"):
        src = ex.get("source_league_id")
        if src:
            settings["league"] = src
    if sportsbook == "crypto.com" and not settings.get("sport_grouping"):
        raw = ex.get("settings") or {}
        if isinstance(raw, dict) and raw.get("sport_grouping"):
            settings["sport_grouping"] = raw["sport_grouping"]
    if sportsbook == "underdog" and not settings.get("league"):
        src = ex.get("source_league_id")
        if src:
            settings["league"] = src
    if sportsbook == "dkex" and not settings.get("league"):
        src = ex.get("source_league_id")
        if src:
            settings["league"] = src
    if sportsbook == "huddle" and not settings.get("competition_id"):
        src = ex.get("source_league_id")
        if src:
            settings["competition_id"] = src
    return settings
