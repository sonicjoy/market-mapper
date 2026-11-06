"""Tip-only LeagueConfig factories via the parser-profile registry."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, TypeVar

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.crypto_esports import esports_crypto_config
from mappers.exchanges.crypto_soccer import soccer_crypto_config
from mappers.exchanges.crypto_tennis import tennis_crypto_config
from mappers.exchanges.dkex import VENUE_TOKEN_BY_SLUG, DkexConfig
from mappers.exchanges.huddle import HuddleConfig
from mappers.exchanges.kalshi import KalshiConfig
from mappers.exchanges.novig import NovigConfig
from mappers.exchanges.polymarket import PolymarketConfig
from mappers.exchanges.polymarket_usa_config import PolyUsaConfig
from mappers.exchanges.polymarket_usa_leagues import us_league_ids
from mappers.exchanges.px import PxConfig
from mappers.exchanges.sxbet_leagues import config_for as _sxbet_config_for
from mappers.exchanges.underdog import UnderdogConfig
from mappers.market_types import MarketType
from mappers.pipeline import LeagueConfig
from mappers.profiles._builders import (
    apply_crypto_tip_settings,
    exchange_settings,
)
from mappers.profiles.registry import lookup_profile, profile_registered
from mappers.profiles.types import LeagueBuildContext
from mappers.seed.profiles import DEFAULT_PROFILES, PARSER_PROFILE_REGISTRY
from mappers.seed.tip_exchange_build import build_tip_exchange_configs
from mappers.seed.tip_helpers import exchange_map
from mappers.seed.tip_helpers import narrow as _narrow
from mappers.sport import Sport, sport_for_league
from mappers.vocab.baseball_markets import baseball_crypto_config
from mappers.vocab.basketball_markets import basketball_crypto_config
from mappers.vocab.football_markets import (
    FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS,
    NFL_NCAAF_LEAGUES,
    football_crypto_config,
)
from mappers.vocab.hockey_markets import hockey_crypto_config
from mappers.vocab.novig_markets import NOVIG_LEAGUE_NAMES
from mappers.vocab.underdog_markets import UNDERDOG_LEAGUE_SLUGS

_KALSHI_PROFILE = "kalshi_generic_v1"
_POLY_PROFILE = "poly_generic_v1"
_NOVIG_PROFILE = "novig_generic_v1"
_DKEX_PROFILE = "dkex_generic_v1"
_UNDERDOG_PROFILE = "underdog_generic_v1"

_C = TypeVar("_C")

_OPTIC_PROFILE = "optic_standard_v1"


def _extend_nfl_ncaaf_optic(league: str, optic_cfg: Any) -> Any:
    """Wire NFL/NCAAF-only Optic ids."""
    if league not in NFL_NCAAF_LEAGUES or optic_cfg is None:
        return optic_cfg
    table = dict(optic_cfg.table_types)
    table.update(FOOTBALL_NFL_NCAAF_OPTIC_EXTRAS)
    return replace(optic_cfg, table_types=table)


def sport_of(obj: Any) -> Sport:
    """Read ``sport`` from a tip row or LeagueConfig.

    Python modules often leave ``LeagueConfig.sport`` unset; fall back to
    the enum map so an overlay does not attach soccer recognizers to CS2.
    """
    raw = getattr(obj, "sport", None)
    if isinstance(raw, Sport):
        return raw
    if raw:
        try:
            return Sport(str(raw).lower())
        except ValueError:
            pass
    league = getattr(obj, "league", None)
    if league is not None:
        return sport_for_league(str(league))
    return Sport.SOCCER


def tip_only_ok(row: Any) -> bool:
    """True when every enabled exchange resolves in the profile registry."""
    sport = sport_of(row)
    for ex in getattr(row, "exchanges", None) or []:
        if not ex.get("enabled", True):
            continue
        book = str(ex.get("sportsbook") or "")
        if book == "kalshi":
            # Every league maps Kalshi by its sport; no profile is needed.
            continue
        profile_id = _profile_id(ex, book)
        registered = PARSER_PROFILE_REGISTRY.get(row.league, {}).get(book)
        if registered and registered != profile_id:
            return False
        if not profile_id or not profile_registered(profile_id, sport):
            return False
    return True


def league_context_from_row(row: Any) -> LeagueBuildContext:
    """Construct build context from a tip league row."""
    sport = sport_of(row)
    horizon = float(getattr(row, "fixture_horizon_hours", 96) or 96)
    extra = tuple(getattr(row, "extra_optic_league_ids", None) or ())
    optic_id = str(getattr(row, "optic_league_id", "") or "")
    return LeagueBuildContext(
        league=str(row.league),
        sport=sport,
        optic_league_id=optic_id,
        fixture_horizon_hours=horizon,
        extra_optic_league_ids=extra,
    )


def build_tip_league(row: Any) -> LeagueConfig:
    """Build a tip-only LeagueConfig from the parser-profile registry."""
    ctx = league_context_from_row(row)
    (
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
    ) = build_tip_exchange_configs(row, ctx, optic_profile_id=_OPTIC_PROFILE)
    optic_cfg = _extend_nfl_ncaaf_optic(ctx.league, optic_cfg)
    return LeagueConfig(
        league=ctx.league,
        sport=ctx.sport,
        PX=px_cfg,
        OPTIC=optic_cfg,
        OUTPUT_ORDER=tuple(dict.fromkeys(optic_cfg.table_types.values())),
        MarketType=MarketType,
        KALSHI=kalshi_cfg,
        CRYPTO=crypto_cfg,
        POLYMARKET=poly_cfg,
        POLYMARKET_USA=poly_usa_cfg,
        NOVIG=novig_cfg,
        DKEX=dkex_cfg,
        UNDERDOG=underdog_cfg,
        RUNSHOP=runshop_cfg,
        HUDDLE=huddle_cfg,
    )


def apply_tip_exchange_settings(cfg: LeagueConfig, row: Any) -> LeagueConfig:
    """Fill prefix / slug / optic id / horizon from the tip league row."""
    optic = cfg.OPTIC
    horizon = float(
        getattr(row, "fixture_horizon_hours", optic.horizon_hours)
        or optic.horizon_hours
    )
    extra = tuple(
        getattr(row, "extra_optic_league_ids", None) or optic.extra_league_ids
    )
    optic_id = str(getattr(row, "optic_league_id", "") or optic.league_id)
    optic = replace(
        optic,
        league_id=optic_id or optic.league_id,
        horizon_hours=horizon,
        extra_league_ids=extra,
    )
    by_book = exchange_map(row)
    sport = sport_of(cfg)
    return replace(
        cfg,
        OPTIC=optic,
        KALSHI=overlay_kalshi(cfg.KALSHI, by_book.get("kalshi"), sport),
        PX=overlay_px(cfg.PX, by_book.get("px")),
        CRYPTO=overlay_crypto(cfg.CRYPTO, by_book.get("crypto.com")),
        POLYMARKET=overlay_poly(
            cfg.POLYMARKET, by_book.get("polymarket"), optic_id, sport,
        ),
        NOVIG=overlay_novig(cfg.NOVIG, by_book.get("novig"), sport),
        UNDERDOG=overlay_underdog(cfg.UNDERDOG, by_book.get("underdog"), sport),
        HUDDLE=overlay_huddle(cfg.HUDDLE, by_book.get("huddle"), sport),
    )


def overlay_novig(
    base: Any | None,
    ex: dict[str, Any] | None,
    sport: Sport,
) -> Any | None:
    """Overlay Novig league string from the tip row."""
    if ex is None:
        return base
    settings = exchange_settings(ex, "novig")
    league = str(settings.get("league") or "").strip()
    if base is None:
        if not league:
            return None
        return _novig_from_profile(league, sport)
    if league:
        return replace(base, league=league)
    return base


def overlay_kalshi(
    base: KalshiConfig | None,
    ex: dict[str, Any] | None,
    sport: Sport,
) -> KalshiConfig:
    """Every league maps Kalshi by its sport; tip settings play no part."""
    _ = base, ex
    return KalshiConfig(sport=sport)


def overlay_px(base: PxConfig | None, ex: dict[str, Any] | None) -> PxConfig | None:
    """Overlay PX tournament_id when present."""
    if ex is None:
        return base
    tid = dict(ex.get("settings") or {}).get("tournament_id")
    if tid is None:
        return base
    if base is None:
        return PxConfig(tournament_id=int(tid), exact={}, suffix=[])
    return replace(base, tournament_id=int(tid))


def overlay_crypto(
    base: CryptoConfig | None, ex: dict[str, Any] | None,
) -> CryptoConfig | None:
    """Overlay crypto meta_league; tip-only ESPORT/MMA when settings name it."""
    if ex is None:
        return base
    settings = dict(ex.get("settings") or {})
    if base is None:
        league = str(settings.get("league") or "").strip()
        grouping = str(settings.get("sport_grouping") or "")
        if league and grouping == "ESPORT":
            return esports_crypto_config(league)
        if league and grouping == "TENNIS":
            return tennis_crypto_config(league, settings)
        if league and grouping == "MMA":
            return _crypto_mma_from_settings(settings)
        if league and grouping in ("NBA", "WNBA", "CBB"):
            return basketball_crypto_config(league, settings)
        if league and grouping == "MLB":
            return baseball_crypto_config(league, settings)
        if league and grouping in ("NFL", "CFB"):
            return football_crypto_config(league, settings)
        if league and grouping == "NHL":
            return hockey_crypto_config(league, settings)
        if league and grouping == "SOCCER":
            profile = lookup_profile("crypto_generic_v1", Sport.SOCCER)
            if profile is not None:
                ctx = LeagueBuildContext("", Sport.SOCCER, "", 96.0, ())
                built = _narrow(CryptoConfig, profile.build(settings, ctx))
                if built is not None:
                    return built
            return apply_crypto_tip_settings(soccer_crypto_config(league), settings)
        return None
    return _crypto_replace(base, settings)


def overlay_poly(
    base: PolymarketConfig | None,
    ex: dict[str, Any] | None,
    optic_id: str,
    sport: Sport,
) -> PolymarketConfig | None:
    """Overlay official Polymarket slug; tip-only gets the sport's recognizers."""
    if ex is None:
        return base
    settings = exchange_settings(ex, "polymarket")
    return _overlay_poly_pin(base, settings, optic_id, sport, _POLY_PROFILE)


def _overlay_poly_pin(
    base: PolymarketConfig | None,
    settings: dict[str, Any],
    optic_id: str,
    sport: Sport,
    profile_id: str,
) -> PolymarketConfig | None:
    slug = str(settings.get("slug_prefix") or "").strip()
    optic = str(settings.get("optic_league_id") or optic_id or "").strip()
    style = settings.get("question_style")
    if base is None:
        if not slug:
            return None
        return _poly_from_profile(slug, optic, style, sport, profile_id)
    return _poly_replace(base, slug, optic, style, sport, settings, profile_id)


def _profile_id(ex: dict[str, Any], book: str) -> str:
    return str(ex.get("parser_profile") or "").strip() or DEFAULT_PROFILES.get(book, "")


def _dkex_from_profile(league: str, sport: Sport) -> DkexConfig | None:
    """Build a DKEX config for a venue league token off the profile.

    Unlike Novig there is no empty-config fallback: a DkexConfig with no
    market_types classifies every symbol to None, which would report the
    whole venue book as unmapped rather than as unconfigured.
    """
    profile = lookup_profile(_DKEX_PROFILE, sport)
    if profile is None:
        return None
    ctx = LeagueBuildContext("", sport, "", 96.0, ())
    return _narrow(DkexConfig, profile.build({"league": league}, ctx))


def overlay_huddle(
    base: HuddleConfig | None,
    ex: dict[str, Any] | None,
    sport: Sport,
) -> HuddleConfig | None:
    """Overlay Huddle competition_id from the tip row."""
    if ex is None:
        return base
    settings = exchange_settings(ex, "huddle")
    cid = str(settings.get("competition_id") or "").strip()
    if base is None:
        if not cid:
            return None
        return _huddle_from_profile(cid, sport)
    if cid:
        return replace(base, competition_ids=(cid,))
    return base


def with_code_dkex(cfg: LeagueConfig, slug: str) -> LeagueConfig:
    """Set DKEX from code, whatever the tip says.

    ``VENUE_TOKEN_BY_SLUG`` alone decides which leagues map DKEX and
    under which venue token; market types come from the sport's code
    vocab.  A tip ``dkex`` exchange row (token, enable flag, profile)
    is ignored, so a league the table does not list maps no DKEX.
    """
    token = VENUE_TOKEN_BY_SLUG.get(slug.strip().casefold())
    dkex_cfg = _dkex_from_profile(token, sport_of(cfg)) if token else None
    if dkex_cfg == cfg.DKEX:
        return cfg
    return replace(cfg, DKEX=dkex_cfg)


def with_code_poly_usa(cfg: LeagueConfig) -> LeagueConfig:
    """Set Polymarket US from code, whatever the tip says.

    ``US_LEAGUE_IDS_BY_OPTIC`` alone decides which gateway leagues (by
    their typed numeric id) a league reads, keyed on its Optic league ids;
    market types come from the gateway enum table.  A tip
    ``polymarket_usa`` exchange row or ``sports_market_type`` rule is
    ignored, exactly as for DKEX.
    """
    optic = cfg.OPTIC
    ids = us_league_ids((optic.league_id, *optic.extra_league_ids))
    usa_cfg = PolyUsaConfig(league_ids=ids) if ids else None
    if usa_cfg == cfg.POLYMARKET_USA:
        return cfg
    return replace(cfg, POLYMARKET_USA=usa_cfg)


def with_code_sxbet(cfg: LeagueConfig, slug: str) -> LeagueConfig:
    """Set SX Bet from code, whatever the tip says.

    ``sxbet_leagues`` alone decides which leagues map SX (each entry is
    evidence-backed: Optic's own event links, or kickoff + names); market
    types come from the sport's crosswalk.  No tip ``sxbet`` exchange row
    exists or is read, exactly as for DKEX.
    """
    sx_cfg = _sxbet_config_for(slug, str(sport_of(cfg)))
    if sx_cfg == cfg.SXBET:
        return cfg
    return replace(cfg, SXBET=sx_cfg)


def with_code_underdog(cfg: LeagueConfig, slug: str) -> LeagueConfig:
    """Set Underdog from code for every slug the code vocab owns.

    ``UNDERDOG_LEAGUE_SLUGS`` decides which leagues map Underdog and the
    market types come from the sport's code vocab; a tip ``underdog``
    exchange row is ignored for these slugs.  A slug the set does not list
    keeps whatever the tip built (existing leagues only).
    """
    key = slug.strip().casefold()
    if key not in UNDERDOG_LEAGUE_SLUGS:
        return cfg
    underdog_cfg = _underdog_from_profile(key.upper(), sport_of(cfg))
    if underdog_cfg == cfg.UNDERDOG:
        return cfg
    return replace(cfg, UNDERDOG=underdog_cfg)


def with_code_novig(cfg: LeagueConfig, slug: str) -> LeagueConfig:
    """Wire Novig from code for slugs ``NOVIG_LEAGUE_NAMES`` owns.

    The Novig league string comes from the table and the market types from
    the sport's code vocab.  A league the tip already wires keeps the tip's
    config; only a missing one is filled in.
    """
    league = NOVIG_LEAGUE_NAMES.get(slug.strip().casefold())
    if league is None or cfg.NOVIG is not None:
        return cfg
    return replace(cfg, NOVIG=_novig_from_profile(league, sport_of(cfg)))


def _underdog_from_profile(league: str, sport: Sport) -> UnderdogConfig | None:
    profile = lookup_profile(_UNDERDOG_PROFILE, sport)
    if profile is None:
        return None
    ctx = LeagueBuildContext("", sport, "", 96.0, ())
    return _narrow(UnderdogConfig, profile.build({"league": league}, ctx))


def overlay_underdog(
    base: UnderdogConfig | None,
    ex: dict[str, Any] | None,
    sport: Sport,
) -> UnderdogConfig | None:
    """Overlay the Underdog venue league token from the tip row."""
    if ex is None:
        return base
    settings = exchange_settings(ex, "underdog")
    league = str(settings.get("league") or "").strip().upper()
    if base is None:
        if not league:
            return None
        return _underdog_from_profile(league, sport)
    if league:
        return replace(base, league=league)
    return base


def _huddle_from_profile(competition_id: str, sport: Sport) -> HuddleConfig | None:
    profile = lookup_profile("huddle_nfl_v1", sport)
    if profile is None:
        return None
    ctx = LeagueBuildContext("", sport, "", 96.0, ())
    return _narrow(HuddleConfig, profile.build({"competition_id": competition_id}, ctx))


def _novig_from_profile(league: str, sport: Sport) -> NovigConfig | None:
    profile = lookup_profile(_NOVIG_PROFILE, sport)
    if profile is None:
        return NovigConfig(league=league, market_types={})
    ctx = LeagueBuildContext("", sport, "", 96.0, ())
    return _narrow(NovigConfig, profile.build({"league": league}, ctx))


def _poly_from_profile(
    slug: str,
    optic: str,
    style: Any,
    sport: Sport,
    profile_id: str = _POLY_PROFILE,
) -> PolymarketConfig | None:
    profile = lookup_profile(profile_id, sport)
    if profile is None:
        return None
    ctx = LeagueBuildContext("", sport, optic, 96.0, ())
    built = profile.build(
        {
            "slug_prefix": slug,
            "optic_league_id": optic,
            "question_style": style,
        },
        ctx,
    )
    return _narrow(PolymarketConfig, built)


def _crypto_mma_from_settings(settings: dict[str, Any]) -> CryptoConfig | None:
    profile = lookup_profile("crypto_mma_v1", Sport.MMA)
    if profile is None:
        return None
    ctx = LeagueBuildContext("", Sport.MMA, "", 96.0, ())
    return _narrow(CryptoConfig, profile.build(settings, ctx))


def _crypto_replace(
    base: CryptoConfig, settings: dict[str, Any],
) -> CryptoConfig:
    return apply_crypto_tip_settings(base, settings)


def _poly_replace(
    base: PolymarketConfig,
    slug: str,
    optic: str,
    style: Any,
    sport: Sport,
    settings: dict[str, Any] | None = None,
    profile_id: str = _POLY_PROFILE,
) -> PolymarketConfig:
    kwargs: dict[str, Any] = {}
    if slug:
        kwargs["slug_prefix"] = slug
    if optic:
        kwargs["optic_league_id"] = optic
    if style:
        kwargs["question_style"] = style
    if not base.market_types or not base.market_rules:
        fresh = _poly_from_profile(
            slug or base.slug_prefix,
            optic,
            style,
            sport,
            profile_id,
        )
        if fresh is not None:
            if not base.market_types:
                kwargs["market_types"] = dict(fresh.market_types)
            if not base.market_rules:
                kwargs["market_rules"] = fresh.market_rules
    return replace(base, **kwargs) if kwargs else base
