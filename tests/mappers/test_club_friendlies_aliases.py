"""Club-friendlies Polymarket aliases now live on the activated tip."""

from __future__ import annotations

from mappers.run import LEAGUES
from mappers.seed.sot import entities_to_alias_data, load_snapshot


def test_alias_table_is_wired_into_the_config():
    cfg = LEAGUES["international_club_friendlies"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "clf"
    assert cfg.optic_league_id == LEAGUES["international_club_friendlies"].OPTIC.league_id
    snap = load_snapshot()
    alias_data, _ = entities_to_alias_data(
        snap.entities, league="international_club_friendlies", entity_type="team",
    )
    poly = alias_data.by_exchange.get("polymarket", {})
    assert poly, "club-friendly polymarket aliases must stay on the tip"
