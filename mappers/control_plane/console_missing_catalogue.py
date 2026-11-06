"""Tip-league → crypto catalogue token filters for Missing inventory."""

from __future__ import annotations

from typing import Any

from BigQuery.crypto_gap_config import all_gap_leagues
from mappers.crypto_meta import crypto_meta_code


def tip_league_catalogue_keys(store: Any | None, league_slug: str) -> tuple[str, str]:
    """NX token (MLB) and catalogue meta_league for a tip slug, when wired."""
    slug = league_slug.strip().lower()
    if not slug or store is None:
        return "", ""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return "", ""
    meta = ""
    for row in store.leagues_for(rid):
        if str(row.league or "").strip().lower() != slug:
            continue
        meta = crypto_meta_code(row)
        break
    for gap in all_gap_leagues():
        if gap.league_key.lower() != slug:
            continue
        token = gap.league_prefix.removeprefix("NX.F.OPT.")
        return token, meta
    return "", meta


def sport_crypto_prefixes(store: Any | None, sport: str) -> frozenset[str]:
    """NX tokens for crypto-enabled tip leagues in this sport."""
    want = sport.strip().lower()
    if not want or store is None:
        return frozenset()
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return frozenset()
    slugs = {
        str(row.league or "").strip().lower()
        for row in store.leagues_for(rid)
        if str(row.sport or "").strip().lower() == want
    }
    out: set[str] = set()
    for gap in all_gap_leagues():
        if gap.league_key.lower() in slugs:
            out.add(gap.league_prefix.removeprefix("NX.F.OPT."))
    return frozenset(out)
