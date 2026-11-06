"""Per-league contract vocabulary for crypto mapping gap checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.pipeline import LeagueConfig
from mappers.seed.tip_leagues import resolved_run_leagues


def _gap_league_configs() -> dict[str, LeagueConfig]:
    """Crypto-enabled league configs from the activated tip."""
    return resolved_run_leagues({})

_NONE = "__none__"


@dataclass(frozen=True, slots=True)
class GapLeagueConfig:
    """One crypto-enabled league for BigQuery gap SQL."""

    league_key: str
    league_prefix: str
    game_lines: frozenset[str]
    player_props: frozenset[str]
    team_props: frozenset[str]
    game_props: frozenset[str]
    crypto: CryptoConfig
    optic_horizon_hours: int = 48
    # Optic /fixtures league.id values fetched by crypto-enabled mappers
    # (e.g. atp, atp_challenger, itf_men, itf_women, wta).
    optic_league_ids: frozenset[str] = frozenset()


def _from_crypto(league_key: str, cfg: LeagueConfig) -> GapLeagueConfig | None:
    crypto: CryptoConfig | None = cfg.CRYPTO
    if crypto is None:
        return None
    horizon = int(cfg.OPTIC.horizon_hours) if cfg.OPTIC.horizon_hours else 48
    optic_ids = frozenset({cfg.OPTIC.league_id}) if cfg.OPTIC.league_id else frozenset()
    return GapLeagueConfig(
        league_key=league_key,
        # crypto.com's symbol namespace token — usually the league, but tennis
        # files ATP and WTA under a shared sport-grouping prefix (NX.F.OPT.TENNIS).
        league_prefix=f"NX.F.OPT.{crypto.symbol_prefix or crypto.league}",
        game_lines=frozenset(crypto.contract_types),
        player_props=frozenset(crypto.prop_contract_types),
        team_props=frozenset(getattr(crypto, "team_prop_contract_types", None) or {}),
        game_props=frozenset(crypto.game_prop_contract_types),
        crypto=crypto,
        optic_horizon_hours=horizon,
        optic_league_ids=optic_ids,
    )


def all_gap_leagues() -> list[GapLeagueConfig]:
    """Return gap-check configs for every league with CRYPTO set."""
    out: list[GapLeagueConfig] = []
    for key, league_cfg in _gap_league_configs().items():
        gap = _from_crypto(key, league_cfg)
        if gap is not None:
            out.append(gap)
    return out


def distinct_gap_leagues() -> list[GapLeagueConfig]:
    """Gap configs collapsed to one per symbol prefix.

    ATP and WTA share the NX.F.OPT.TENNIS namespace (split only by
    meta_league), so both repo leagues resolve to the same prefix.  For the
    rollup — where each symbol must be counted once — merge configs that share
    a prefix, unioning their contract vocabularies so a symbol is treated as
    mapped if either league covers its contract type.
    """
    merged: dict[str, GapLeagueConfig] = {}
    for gap in all_gap_leagues():
        existing = merged.get(gap.league_prefix)
        if existing is None:
            merged[gap.league_prefix] = gap
            continue
        merged[gap.league_prefix] = replace(
            existing,
            game_lines=existing.game_lines | gap.game_lines,
            player_props=existing.player_props | gap.player_props,
            team_props=existing.team_props | gap.team_props,
            game_props=existing.game_props | gap.game_props,
            optic_horizon_hours=max(
                existing.optic_horizon_hours, gap.optic_horizon_hours
            ),
            optic_league_ids=existing.optic_league_ids | gap.optic_league_ids,
        )
    return list(merged.values())


def league_key_for_prefix(league_prefix: str) -> str | None:
    """Map NX.F.OPT.<META> prefix to repo league key (e.g. NX.F.OPT.MLB → mlb)."""
    for gap in all_gap_leagues():
        if gap.league_prefix == league_prefix:
            return gap.league_key
    return None


def league_keys_for_prefix(league_prefix: str) -> list[str]:
    """All repo league keys sharing a prefix (both tours for NX.F.OPT.TENNIS)."""
    return [g.league_key for g in all_gap_leagues() if g.league_prefix == league_prefix]


def sql_string_list(values: frozenset[str]) -> str:
    """Format a frozenset of contract types for a BigQuery unnest literal."""
    if not values:
        return f"'{_NONE}'"
    escaped = [v.replace("'", "\\'") for v in sorted(values)]
    return ", ".join(f"'{v}'" for v in escaped)


def fixture_prefix_re(league_prefix: str) -> str:
    """Regex fragment for extracting a fixture key from a crypto symbol."""
    escaped = league_prefix.replace(".", r"\.")
    return rf"{escaped}-\d+-\d{{6}}"


# League-agnostic form of fixture_prefix_re, for the consolidated gap SQL.
# `[^-]+` cannot cross a '-', so on a real symbol it matches exactly the
# league token the per-league literal would have matched.
ANY_FIXTURE_PREFIX_RE = r"NX\.F\.OPT\.[^-]+-\d+-\d{6}"

# Every configured prefix starts with this, so it is a safe pre-filter for
# the single-scan queries: no symbol excluded by it could match any league.
SYMBOL_NAMESPACE_PREFIX = "NX.F.OPT."


def sql_string_array(values: frozenset[str]) -> str:
    """Format a frozenset as a BigQuery array literal (never empty).

    An empty ARRAY<STRING> literal has no inferable element type inside a
    struct, so the ``__none__`` sentinel from :func:`sql_string_list` is
    kept — it matches nothing, exactly as the per-league SQL intends.
    """
    return f"[{sql_string_list(values)}]"


def leagues_struct_sql(leagues: list[GapLeagueConfig]) -> str:
    """Format the per-league gap vocabulary as an array-of-struct literal body.

    This is the whole point of the consolidated gap SQL: what used to be 27
    hand-substituted queries (one per league, each re-scanning the same
    sources) becomes one query joined against this literal dimension.
    Field order is fixed — BigQuery requires every struct in an array to
    share a type.
    """
    rows: list[str] = []
    for league in leagues:
        prefix = league.league_prefix.replace("'", "\\'")
        rows.append(
            "    struct(\n"
            f"      '{prefix}' as league_prefix,\n"
            f"      {int(league.optic_horizon_hours)} as optic_horizon_hours,\n"
            f"      {sql_string_array(league.game_lines)} as mapped_game_lines,\n"
            f"      {sql_string_array(league.player_props)} as mapped_player_props,\n"
            f"      {sql_string_array(league.team_props)} as mapped_team_props,\n"
            f"      {sql_string_array(league.game_props)} as mapped_game_props,\n"
            f"      {sql_string_array(league.optic_league_ids)} as optic_league_ids\n"
            "    )"
        )
    return ",\n".join(rows)


def gap_league_for_prefix(league_prefix: str) -> GapLeagueConfig | None:
    """Return gap config for NX.F.OPT.<META> prefix (e.g. NX.F.OPT.UCL)."""
    for gap in all_gap_leagues():
        if gap.league_prefix == league_prefix:
            return gap
    return None


def gap_league_for_cli_arg(arg: str) -> GapLeagueConfig | None:
    """Resolve repo league key (ucl) or NX.F.OPT prefix (NX.F.OPT.UCL)."""
    if arg.startswith("NX.F.OPT."):
        return gap_league_for_prefix(arg)
    return next((g for g in all_gap_leagues() if g.league_key == arg), None)


def gap_league_for_symbol(symbol: str) -> GapLeagueConfig | None:
    """Return gap config inferred from a crypto.com symbol string."""
    if not symbol.startswith("NX.F.OPT."):
        return None
    # legacy: ticker parse — replace with the typed venue field, do not extend
    league_prefix = symbol.split("-", 1)[0]
    return gap_league_for_prefix(league_prefix)


def fixture_prefix_from_symbol(symbol: str) -> str | None:
    """Extract NX.F.OPT.<LEAGUE>-<event>-<yymmdd> from a symbol, if present."""
    gap = gap_league_for_symbol(symbol)
    if gap is None:
        return None
    match = re.search(fixture_prefix_re(gap.league_prefix), symbol)
    return match.group(0) if match else None
