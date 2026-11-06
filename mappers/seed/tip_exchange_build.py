"""Build exchange configs from tip exchange rows via the profile registry."""

from __future__ import annotations

from typing import Any

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.dkex import DkexConfig
from mappers.exchanges.huddle import HuddleConfig
from mappers.exchanges.kalshi import KalshiConfig
from mappers.exchanges.novig import NovigConfig
from mappers.exchanges.optic import OpticConfig
from mappers.exchanges.polymarket import PolymarketConfig
from mappers.exchanges.polymarket_usa_config import PolyUsaConfig
from mappers.exchanges.px import PxConfig
from mappers.exchanges.runshop import RunshopConfig
from mappers.exchanges.underdog import UnderdogConfig
from mappers.profiles._builders import exchange_settings
from mappers.profiles.registry import lookup_profile
from mappers.profiles.types import LeagueBuildContext
from mappers.seed.league_meta import league_settings_from_row
from mappers.seed.profiles import DEFAULT_PROFILES
from mappers.seed.tip_helpers import exchange_map, narrow


def _profile_id(ex: dict[str, Any], book: str) -> str:
    return str(ex.get("parser_profile") or "").strip() or DEFAULT_PROFILES.get(book, "")


def _runshop_from_meta(row: Any, ctx: LeagueBuildContext) -> RunshopConfig | None:
    """Fallback Runshop build when only ``runshop_enabled`` meta is set."""
    settings = league_settings_from_row(row)
    if not settings.get("runshop_enabled"):
        return None
    profile = lookup_profile("runshop_generic_v1", ctx.sport)
    if profile is None:
        return None
    runshop_settings: dict[str, Any] = {"enabled": True}
    markets_path = settings.get("runshop_markets_path")
    if markets_path:
        runshop_settings["markets_path"] = markets_path
    crosswalk_path = settings.get("runshop_crosswalk_path")
    if crosswalk_path:
        runshop_settings["crosswalk_path"] = crosswalk_path
    else:
        runshop_settings["crosswalk_path"] = f"vendor/{ctx.league}/runshop_crosswalk.toml"
    return narrow(RunshopConfig, profile.build(runshop_settings, ctx))


def _configs_from_exchanges(
    by_book: dict[str, dict[str, Any]],
    ctx: LeagueBuildContext,
) -> tuple[
    PxConfig | None,
    KalshiConfig | None,
    CryptoConfig | None,
    PolymarketConfig | None,
    PolyUsaConfig | None,
    NovigConfig | None,
    DkexConfig | None,
    UnderdogConfig | None,
    RunshopConfig | None,
    HuddleConfig | None,
]:
    px_cfg: PxConfig | None = None
    crypto_cfg: CryptoConfig | None = None
    poly_cfg: PolymarketConfig | None = None
    poly_usa_cfg: PolyUsaConfig | None = None
    novig_cfg: NovigConfig | None = None
    dkex_cfg: DkexConfig | None = None
    underdog_cfg: UnderdogConfig | None = None
    runshop_cfg: RunshopConfig | None = None
    huddle_cfg: HuddleConfig | None = None

    # Every league maps Kalshi: which markets are its own is decided by
    # the Optic fixture each Kalshi milestone joins, not by tip settings.
    kalshi_cfg = KalshiConfig(sport=ctx.sport)

    for _book, ex in by_book.items():
        if _book == "kalshi":
            continue
        profile_id = _profile_id(ex, _book)
        profile = lookup_profile(profile_id, ctx.sport)
        if profile is None:
            continue
        built = profile.build(exchange_settings(ex, profile.sportsbook), ctx)
        if profile.sportsbook == "px":
            px_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "crypto.com":
            crypto_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "polymarket":
            poly_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "polymarket_usa":
            poly_usa_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "novig":
            novig_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "dkex":
            dkex_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "underdog":
            underdog_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "runshop":
            runshop_cfg = built  # type: ignore[assignment]
        elif profile.sportsbook == "huddle":
            huddle_cfg = built  # type: ignore[assignment]

    return (px_cfg, kalshi_cfg, crypto_cfg, poly_cfg, poly_usa_cfg,
            novig_cfg, dkex_cfg, underdog_cfg, runshop_cfg, huddle_cfg)


def _optic_config(ctx: LeagueBuildContext, optic_profile_id: str) -> OpticConfig:
    optic_profile = lookup_profile(optic_profile_id, ctx.sport)
    if optic_profile is None:
        raise KeyError(f"{optic_profile_id} missing for {ctx.sport}")
    optic_cfg = narrow(OpticConfig, optic_profile.build({}, ctx))
    if optic_cfg is None:
        raise KeyError(f"{optic_profile_id} built no config for {ctx.sport}")
    return optic_cfg


def build_tip_exchange_configs(
    row: Any,
    ctx: LeagueBuildContext,
    *,
    optic_profile_id: str = "optic_standard_v1",
) -> tuple[
    PxConfig | None,
    OpticConfig,
    KalshiConfig | None,
    CryptoConfig | None,
    PolymarketConfig | None,
    PolyUsaConfig | None,
    NovigConfig | None,
    DkexConfig | None,
    UnderdogConfig | None,
    RunshopConfig | None,
    HuddleConfig | None,
]:
    """Resolve every enabled exchange on a tip row through ``ParserProfile``."""
    (
        px_cfg,
        kalshi_cfg,
        crypto_cfg,
        poly_cfg,
        poly_usa_cfg,
        novig_cfg,
        dkex_cfg,
        underdog_cfg,
        runshop_cfg,
        huddle_cfg,
    ) = _configs_from_exchanges(exchange_map(row), ctx)
    if runshop_cfg is None:
        runshop_cfg = _runshop_from_meta(row, ctx)
    optic_cfg = _optic_config(ctx, optic_profile_id)
    return (
        px_cfg,
        optic_cfg,
        kalshi_cfg,
        crypto_cfg,
        poly_cfg,
        poly_usa_cfg,
        novig_cfg,
        dkex_cfg,
        underdog_cfg,
        runshop_cfg,
        huddle_cfg,
    )
