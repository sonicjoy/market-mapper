"""TxODDS in the mapping console: Cart Verify evidence, the Missing catalogue, the paste-box guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mappers.control_plane import console_missing
from mappers.control_plane.console_missing import list_missing_symbols
from mappers.control_plane.console_missing_txodds import (
    TXODDS_NOTE,
    CatalogueUnavailableError,
    normalize_txodds_row,
    txodds_missing_sql,
)
from mappers.control_plane.console_platforms import default_missing_platform_id, explore_platform
from mappers.control_plane.entry import detect_sportsbook
from mappers.control_plane.league_review import BOOK_LABELS
from mappers.control_plane.live_evidence import collect_pins_evidence, probe_pin_evidence
from mappers.control_plane.live_evidence_types import EvidenceFetchers
from mappers.control_plane.models import AliasPin, EntityAliasPayload
from mappers.control_plane.rows import EntityRow

TEAMS = {"1622": "Boston Celtics", "2476": "LA Clippers", "1812": "Detroit Pistons"}


class _Store:
    current_rule_set_id = "P_test"

    def entities_for(self, rid):
        return [
            EntityRow(
                league="nba", entity_type="team", canonical_key="BOS", canonical_name="Boston Celtics", aliases=[]
            ),
            EntityRow(
                league="nba", entity_type="team", canonical_key="LAC", canonical_name="Los Angeles Clippers", aliases=[]
            ),
            EntityRow(league="nba", entity_type="team", canonical_key="CHI", canonical_name=None, aliases=[]),
        ]


def _probe(value: str, name: str, teams=None):
    fx = EvidenceFetchers(txodds_teams=(lambda: TEAMS) if teams is None else teams)
    return probe_pin_evidence(
        _Store(),
        league="nba",
        sportsbook="txodds",
        alias_kind="external_id",
        alias_value=value,
        canonical_name=name,
        fetchers=fx,
    )


def test_pin_on_the_right_team_passes_with_a_ref():
    hit = _probe("1622", "Boston Celtics")
    assert hit.blocker is None and hit.refs == ("txodds:team:1622:Boston Celtics",)


def test_canonical_key_resolves_to_the_tip_name_and_la_matches_los_angeles():
    assert _probe("2476", "LAC").blocker is None


def test_pin_on_the_wrong_team_is_blocked():
    hit = _probe("1622", "Detroit Pistons")
    assert hit.blocker == "TxODDS 1622 is 'Boston Celtics', not 'Detroit Pistons'."


def test_unknown_and_non_numeric_ids_are_blocked():
    assert "not in the TxODDS team list" in (_probe("99999", "Boston Celtics").blocker or "")
    assert "are numbers" in (_probe("BOS", "Boston Celtics").blocker or "")


def test_a_canonical_with_no_name_is_checked_for_existence_only():
    hit = _probe("1622", "CHI")
    assert hit.blocker is None and "txodds:name-unchecked" in hit.refs


def test_an_unreadable_team_list_fails_open_and_says_so():
    def boom():
        raise PermissionError("no grant on tx_scores_us")

    hit = _probe("1622", "Detroit Pistons", teams=boom)
    assert hit.blocker is None and hit.refs == ("txodds:unverified:PermissionError",)


def test_cart_verify_collects_txodds_evidence():
    pins = [
        EntityAliasPayload(
            league="nba",
            canonical_key="BOS",
            canonical_name="Boston Celtics",
            aliases=[AliasPin(sportsbook="txodds", alias_kind="external_id", alias_value="1812")],
        )
    ]
    refs, blockers = collect_pins_evidence(
        _Store(), pins, fetchers=EvidenceFetchers(txodds_teams=lambda: TEAMS), probe=probe_pin_evidence
    )
    assert refs == [] and blockers == ["TxODDS 1812 is 'Detroit Pistons', not 'Boston Celtics'."]


def test_short_numbers_are_not_guessed_as_optic_ids():
    assert detect_sportsbook("1622") is None
    assert detect_sportsbook("39288") is None
    assert detect_sportsbook("20000009") == "crypto.com"  # 6+ digits: crypto.com, unchanged
    assert detect_sportsbook("B29E0BFC1622") == "optic"  # Optic competitor id, unchanged


def test_txodds_platform_and_label():
    plat = explore_platform("txodds")
    assert plat is not None and plat.missing_catalogue and not plat.unmapped_inventory
    assert default_missing_platform_id() == "crypto"
    assert BOOK_LABELS["txodds"] == "TxODDS"


def _map_rows():
    soon = datetime.now(UTC) + timedelta(hours=10)
    return [
        {
            "txodds_fixture_id": "18398707",
            "txodds_start": soon,
            "home_canonical": "DAL",
            "away_canonical": "SAS",
            "home_txodds_team_id": "1788",
            "away_txodds_team_id": "2914",
            "coverage_status": "Approved",
            "match_status": "unmatched",
        },
        {
            "txodds_fixture_id": "18290770",
            "txodds_start": soon + timedelta(hours=1),
            "home_canonical": None,
            "away_canonical": "CLE",
            "home_txodds_team_id": "2709",
            "away_txodds_team_id": "1737",
            "coverage_status": "Approved",
            "match_status": "teams_unpinned",
        },
        {
            "txodds_fixture_id": "18300000",
            "txodds_start": (soon + timedelta(minutes=30)).isoformat(),
            "home_canonical": "BOS",
            "away_canonical": "NYK",
            "match_status": "ambiguous",
        },
    ]


def test_fixture_map_rows_become_missing_rows():
    row = normalize_txodds_row(_map_rows()[1])
    assert (row["platform"], row["symbol"], row["fixture_name"]) == ("txodds", "18290770", "2709 v CLE")
    assert (row["league"], row["sport"], row["contract_type"], row["scope"]) == (
        "nba",
        "basketball",
        "teams_unpinned",
        "untouched",
    )
    assert row["ttko_hours"] is not None and 10 < row["ttko_hours"] < 12
    assert normalize_txodds_row(_map_rows()[2])["scope"] == "extra"


@pytest.fixture(autouse=True)
def _clear_cache():
    console_missing._cache.clear()
    yield
    console_missing._cache.clear()


def test_missing_page_lists_txodds_rows_with_their_own_filters():
    view = list_missing_symbols(platform="txodds", fetch_fn=_map_rows)
    assert view["count"] == 3 and view["note"] == TXODDS_NOTE and view["error"] is None
    assert [r["symbol"] for r in view["rows"]] == ["18398707", "18300000", "18290770"]
    assert {o["name"] for o in view["market_options"]} == {"unmatched", "teams_unpinned", "ambiguous"}
    assert list_missing_symbols(platform="txodds", league="nfl", fetch_fn=_map_rows)["count"] == 0
    assert list_missing_symbols(platform="txodds", sport="basketball", scope="extra", fetch_fn=_map_rows)["count"] == 1
    picked = list_missing_symbols(platform="txodds", contract_type="teams_unpinned", q="cle", fetch_fn=_map_rows)
    assert [r["symbol"] for r in picked["rows"]] == ["18290770"] and picked["rows"][0]["league"] == "nba"


def test_an_unreadable_fixture_map_shows_the_unwired_state_not_an_error():
    def unreadable():
        raise CatalogueUnavailableError("Forbidden: no grant")

    view = list_missing_symbols(platform="txodds", fetch_fn=unreadable)
    assert view["rows"] == [] and view["error"] is None
    assert view["note"] == "TxODDS catalogue is not readable here: Forbidden: no grant"


def test_the_txodds_platform_uses_its_own_fetcher(monkeypatch):
    seen = []
    monkeypatch.setattr(console_missing, "fetch_txodds_missing", lambda project: seen.append(project) or _map_rows())
    monkeypatch.setenv("GCP_PROJECT", "rs-marketmaking")
    monkeypatch.delenv("MAPPING_MISSING_BQ_PROJECT", raising=False)
    assert list_missing_symbols(platform="txodds")["count"] == 3 and seen == ["rs-marketmaking"]


def test_fixture_map_sql_reads_the_view_for_unmatched_upcoming_fixtures():
    sql = txodds_missing_sql("rs-marketmaking")
    assert "`rs-marketmaking.tx_scores_us.txodds_optic_fixture_map`" in sql
    assert "match_status != 'matched'" in sql and "interval 24 hour" in sql


def test_fetch_maps_not_found_and_forbidden_to_unavailable(monkeypatch):
    from google.api_core.exceptions import Forbidden, NotFound

    import BigQuery.client as bq
    from mappers.control_plane import console_missing_txodds as mod

    for exc in (NotFound("view"), Forbidden("grant")):
        monkeypatch.setattr(bq, "ro_client", lambda: SimpleNamespace())
        monkeypatch.setattr(bq, "ro_query", lambda client, sql, exc=exc: (_ for _ in ()).throw(exc))
        with pytest.raises(CatalogueUnavailableError):
            mod.fetch_txodds_missing("rs-marketmaking")
    with pytest.raises(CatalogueUnavailableError, match="GCP_PROJECT"):
        mod.fetch_txodds_missing("")
