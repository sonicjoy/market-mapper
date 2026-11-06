"""Phase 2 fight-card pins go through the market-rule draft kernel."""

from __future__ import annotations

from mappers.control_plane.pin_flow_markets import draft_and_verify_market_rules
from mappers.control_plane.rof_before_rule import MarketRuleObservation
from mappers.control_plane.rows import LeagueRow, MarketRuleRow
from mappers.control_plane.store import InMemoryStore

_TDS_NOTES = (
    "No official Polymarket US contract text was found for tds-. "
    "yes_side is unset. The code comment that Yes stamps over is not a citation."
)


def _exchange(book: str, profile: str, settings: dict[str, object]) -> dict[str, object]:
    return {
        "sportsbook": book,
        "enabled": True,
        "parser_profile": profile,
        "source_league_id": "",
        "settings": settings,
    }


def _league(slug: str, sport: str, exchanges: list[dict[str, object]]) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=slug,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=["moneyline"],
        exchanges=exchanges,
    )


def _map(
    league: str,
    book: str,
    key_type: str,
    key: str,
    canonical: str,
    *,
    rule_id: str,
) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=rule_id,
        league=league,
        sportsbook=book,
        rule_kind="taxonomy",
        source_key_type=key_type,
        source_key=key,
        action="map",
        canonical_market_type=canonical,
        priority=100,
        enabled=True,
        confidence="id_verified",
        match_operator="exact",
    )


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_phase2",
        entities=[],
        leagues=[
            _league("ufc", "mma", [
                _exchange("crypto.com", "crypto_mma_v1", {
                    "league": "ufc", "sport_grouping": "MMA",
                }),
            ]),
            _league("nfl", "football", [
                _exchange("polymarket_usa", "poly_usa_generic_v1", {"slug_prefix": "nfl"}),
            ]),
            _league("ncaaf", "football", [
                _exchange("polymarket_usa", "poly_usa_generic_v1", {"slug_prefix": "cfb"}),
            ]),
        ],
        market_rules=[
            _map("ufc", "optic", "market_id", "total_rounds", "total_rounds", rule_id="mr_optic_rounds"),
            _map(
                "ufc", "crypto.com", "contract_type", "Round of Finish", "round_betting",
                rule_id="mr_finish",
            ),
            _map("nfl", "optic", "market_id", "total_touchdowns", "total_touchdowns", rule_id="mr_nfl_td"),
            _map(
                "ncaaf", "optic", "market_id", "total_touchdowns", "total_touchdowns",
                rule_id="mr_ncaaf_td",
            ),
        ],
        activate=True,
    )
    return store


def _kalshi_rounds_obs() -> MarketRuleObservation:
    return {
        "league": "ufc",
        "sportsbook": "kalshi",
        "source_key": "ROUNDS",
        "source_key_type": "ticker_type",
        "live_optic_market_ids": {"total_rounds"},
    }


def _tds_obs(league: str) -> MarketRuleObservation:
    return {
        "league": league,
        "sportsbook": "polymarket_usa",
        "source_key": "tds-",
        "source_key_type": "ticker_suffix",
        "match_operator": "prefix",
        "canonical_market_type": "total_touchdowns",
        "notes": _TDS_NOTES,
        "live_optic_market_ids": {"total_touchdowns"},
    }


def _finish_obs() -> MarketRuleObservation:
    return {
        "league": "ufc",
        "sportsbook": "crypto.com",
        "source_key": "Round of Finish",
        "source_key_type": "contract_type",
        "live_optic_market_ids": {"round_betting"},
    }


def test_phase2_card_drafts_nothing_for_kalshi_or_uncited_sides() -> None:
    """Kalshi maps from its own typed fields, so its ROUNDS type is never a tip rule."""
    pins, skipped = draft_and_verify_market_rules(
        _store(),
        [_kalshi_rounds_obs(), _finish_obs(), _tds_obs("nfl"), _tds_obs("ncaaf")],
    )
    assert [(row["source_key"], row["reason"]) for row in skipped] == [
        ("ROUNDS", "not_name_match_book"),
        ("Round of Finish", "already_mapped"),
        ("tds-", "needs_code"),
        ("tds-", "needs_code"),
    ]
    assert pins == []


def test_ncaaf_tds_skips_when_the_census_lacks_the_id() -> None:
    obs = _tds_obs("ncaaf")
    obs["live_optic_market_ids"] = set()
    pins, skipped = draft_and_verify_market_rules(_store(), [obs])
    assert pins == []
    assert skipped[0]["reason"] == "needs_code"
    assert skipped[0]["league"] == "ncaaf"
    assert skipped[0]["source_key"] == "tds-"
