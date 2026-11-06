"""Parser profile registry and intentional Optic ignores for seed extract."""

from __future__ import annotations

# league -> sportsbook -> parser_profile id.
# Seed aborts if an enabled exchange has no entry here.
PARSER_PROFILE_REGISTRY: dict[str, dict[str, str]] = {
    "ufc": {
        "optic": "optic_standard_v1",
        "crypto.com": "crypto_mma_v1",
        "polymarket": "poly_ufc_v1",
        "novig": "novig_generic_v1",
    },
    "boxing_matches": {
        "optic": "optic_standard_v1",
    },
    # Synthetic Kalshi fixture leagues (out of mapper LEAGUES; onboarded in
    # synthetic/series.toml). Every league_id there needs an entry, including the
    # ones whose [[series]] block is currently commented out -- so that enabling
    # one stays a single-line change and cannot abort the seed.
    "itf_men_doubles": {"kalshi": "kalshi_generic_v1"},
    "itf_women_doubles": {"kalshi": "kalshi_generic_v1"},
    # Motorsports outrights. "Nascar" is capitalised to match the manual fixtures
    # in opticodds_us.opticodds_fixtures; formulaone is staged but disabled.
    "Nascar": {"kalshi": "kalshi_generic_v1"},
    "formulaone": {"kalshi": "kalshi_generic_v1"},
    "ncaaf": {
        "optic": "optic_standard_v1",
        "crypto.com": "crypto_generic_v1",
    },
    # Big-5 soccer (Kalshi+Optic+Poly+crypto.com; PX still unwired).
    "italy_serie_a": {
        "optic": "optic_standard_v1",
        "crypto.com": "crypto_generic_v1",
        "polymarket": "poly_generic_v1",
    },
    "france_ligue_1": {
        "optic": "optic_standard_v1",
        "crypto.com": "crypto_generic_v1",
        "polymarket": "poly_generic_v1",
    },
    "germany_bundesliga": {
        "optic": "optic_standard_v1",
        "crypto.com": "crypto_generic_v1",
        "polymarket": "poly_generic_v1",
    },
}

# league -> optic market_id -> notes (explicit action=ignore).
# Do not list a key that is also in that league's OPTIC.table_types — COW
# identity ignores action, so the ignore wins and classify drops the map.
# UFC method_of_victory was removed 2026-08-19 (live map since 2026-08-07).
INTENTIONAL_OPTIC_IGNORES: dict[str, dict[str, str]] = {}

# Default profile guessers when league not fully registered yet (seed warns
# then fails unless --allow-incomplete-profiles).
DEFAULT_PROFILES: dict[str, str] = {
    "optic": "optic_standard_v1",
    "px": "px_generic_v1",
    "crypto.com": "crypto_generic_v1",
    "polymarket": "poly_generic_v1",
    "polymarket_usa": "poly_usa_generic_v1",
    "novig": "novig_generic_v1",
    "dkex": "dkex_generic_v1",
    "underdog": "underdog_generic_v1",
    "runshop": "runshop_generic_v1",
    "huddle": "huddle_nfl_v1",
}


def profile_for(league: str, sportsbook: str) -> str | None:
    return PARSER_PROFILE_REGISTRY.get(league, {}).get(sportsbook)
