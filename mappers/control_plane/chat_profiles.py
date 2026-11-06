"""Default exchange pins for Mapper Chat league onboarding."""

from __future__ import annotations

from typing import Any

# Keep aligned with console/src/entryEnums.ts SPORTSBOOKS / defaultParserProfile
# and mappers/control_plane/console_platforms.py (explore ids + labels).
# Kalshi is absent on purpose: it maps from its own typed fields, so a league
# never carries a Kalshi exchange row.
CHAT_SPORTSBOOKS: tuple[str, ...] = (
    "crypto.com",
    "optic",
    "polymarket",
    "polymarket_usa",
    "px",
    "novig",
    "underdog",
    "dkex",
)

_PARSER: dict[str, str] = {
    "crypto.com": "crypto_generic_v1",
    "optic": "optic_standard_v1",
    "polymarket": "poly_generic_v1",
    "polymarket_usa": "poly_usa_generic_v1",
    "px": "px_generic_v1",
    "novig": "novig_generic_v1",
    "underdog": "underdog_generic_v1",
    "dkex": "dkex_generic_v1",
}


def parser_profile(sportsbook: str) -> str:
    """Default parser profile id for a sportsbook."""
    return _PARSER.get(sportsbook, f"{sportsbook}_generic_v1")


def all_platform_exchanges(
    *,
    optic_league_id: str,
    evidence_books: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Enable every book with evidence; others stay off with empty source id."""
    enabled = set(evidence_books or list(CHAT_SPORTSBOOKS))
    out: list[dict[str, Any]] = []
    for book in CHAT_SPORTSBOOKS:
        has = book in enabled
        # Only Optic reuses the Optic league id as source_league_id.
        # Polymarket official, Poly US, crypto.com, and Novig each carry their
        # own id shape — never copy the Optic slug onto those pins.
        source = optic_league_id if has and book == "optic" else None
        out.append(
            {
                "sportsbook": book,
                "enabled": has,
                "parser_profile": parser_profile(book),
                "source_league_id": source if has else None,
                "settings": {},
            }
        )
    return out


def enabled_sportsbooks(exchanges: list[dict[str, Any]]) -> list[str]:
    """Sportsbooks flagged enabled on a league payload."""
    return [str(e["sportsbook"]) for e in exchanges if e.get("enabled")]
