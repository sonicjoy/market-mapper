"""Console Missing catalogue inventory (no BQ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mappers.control_plane.console_missing import _cache, list_missing_symbols


def _sample_rows() -> list[dict]:
    kick = datetime.now(UTC) + timedelta(hours=6)
    return [
        {
            "symbol": "NX.F.OPT.MLB-00001-260925-M.O.1.1.20261130",
            "symbol_base": "NX.F.OPT.MLB-00001-260925-M.O.1.1",
            "fixture_prefix": "NX.F.OPT.MLB-00001-260925",
            "crypto_prefix": "MLB",
            "market_group": "Game Line",
            "contract_type": "Moneyline",
            "period_type": "Full-Game",
            "meta_name": "Team A @ Team B",
            "meta_league": "MLB",
            "kickoff": kick,
            "scope": "untouched",
        },
        {
            "symbol": "NX.F.OPT.MLB-00002-260925-M.O.1.156.20261130",
            "symbol_base": "NX.F.OPT.MLB-00002-260925-M.O.1.156",
            "fixture_prefix": "NX.F.OPT.MLB-00002-260925",
            "crypto_prefix": "MLB",
            "market_group": "Player Prop",
            "contract_type": "Total RBIs",
            "period_type": "Full-Game",
            "meta_name": "Other @ Game",
            "meta_league": "MLB",
            "kickoff": kick,
            "scope": "extra",
        },
        {
            "symbol": "NX.F.OPT.EPL-00001-260928-M.O.1.1.20261230",
            "symbol_base": "NX.F.OPT.EPL-00001-260928-M.O.1.1",
            "fixture_prefix": "NX.F.OPT.EPL-00001-260928",
            "crypto_prefix": "EPL",
            "market_group": "Game Line",
            "contract_type": "Moneyline (3-Way)",
            "period_type": "90 Minutes and Stoppage Time",
            "meta_name": "Away @ Home",
            "meta_league": "EPL",
            "kickoff": kick,
            "scope": "untouched",
        },
    ]


def setup_function() -> None:
    _cache.clear()


def test_list_missing_filters_scope_and_search() -> None:
    def fetch() -> list[dict]:
        return _sample_rows()

    view = list_missing_symbols(scope="untouched", q="team a", fetch_fn=fetch)
    assert view["count"] == 1
    assert view["rows"][0]["symbol"].startswith("NX.F.OPT.MLB-00001")


def test_list_missing_unknown_platform_empty() -> None:
    view = list_missing_symbols(platform="kalshi", fetch_fn=lambda: _sample_rows())
    assert view["count"] == 0
    assert view["rows"] == []


def test_list_missing_pagination_and_sort_symbol() -> None:
    view = list_missing_symbols(
        sort="symbol",
        sort_dir="desc",
        limit=1,
        offset=1,
        fetch_fn=lambda: _sample_rows(),
    )
    assert view["count"] == 3
    assert len(view["rows"]) == 1


def _windowed_rows() -> list[dict]:
    now = datetime.now(UTC)
    rows = _sample_rows()
    rows[0]["kickoff"] = now + timedelta(hours=2)
    rows[1]["kickoff"] = now + timedelta(hours=30)
    rows[2]["kickoff"] = None
    return rows


def test_list_missing_kickoff_window_bounds() -> None:
    now = datetime.now(UTC)
    view = list_missing_symbols(
        kickoff_from=(now + timedelta(hours=1)).isoformat(),
        kickoff_to=(now + timedelta(hours=3)).isoformat(),
        fetch_fn=_windowed_rows,
    )
    assert [r["symbol"][:18] for r in view["rows"]] == ["NX.F.OPT.MLB-00001"]


def test_list_missing_kickoff_from_only_drops_undated_rows() -> None:
    now = datetime.now(UTC)
    view = list_missing_symbols(
        kickoff_from=(now + timedelta(hours=10)).isoformat(),
        fetch_fn=_windowed_rows,
    )
    assert view["count"] == 1
    assert view["rows"][0]["contract_type"] == "Total RBIs"


def test_list_missing_kickoff_naive_bound_is_utc() -> None:
    now = datetime.now(UTC)
    naive = (now + timedelta(hours=10)).replace(tzinfo=None).isoformat(timespec="minutes")
    view = list_missing_symbols(kickoff_to=naive, fetch_fn=_windowed_rows)
    assert view["count"] == 1
    assert view["rows"][0]["contract_type"] == "Moneyline"


def test_list_missing_bad_kickoff_bound_reports_error() -> None:
    view = list_missing_symbols(kickoff_from="tomorrow", fetch_fn=_windowed_rows)
    assert view["count"] == 0
    assert "kickoff_from" in (view["error"] or "")


def test_list_missing_market_names_select_any_of() -> None:
    view = list_missing_symbols(
        contract_type=["moneyline", "Total RBIs"],
        fetch_fn=lambda: _sample_rows(),
    )
    assert sorted(r["contract_type"] for r in view["rows"]) == ["Moneyline", "Total RBIs"]


def test_list_missing_single_contract_type_string_still_filters() -> None:
    view = list_missing_symbols(contract_type="Total RBIs", fetch_fn=lambda: _sample_rows())
    assert view["count"] == 1


def test_list_missing_market_options_ignore_own_selection() -> None:
    view = list_missing_symbols(
        contract_type=["Moneyline"],
        fetch_fn=lambda: _sample_rows(),
    )
    names = [o["name"] for o in view["market_options"]]
    assert set(names) == {"Moneyline", "Total RBIs", "Moneyline (3-Way)"}
    assert view["count"] == 1


def test_list_missing_market_options_follow_other_filters() -> None:
    view = list_missing_symbols(scope="untouched", fetch_fn=lambda: _sample_rows())
    assert {o["name"]: o["count"] for o in view["market_options"]} == {
        "Moneyline": 1,
        "Moneyline (3-Way)": 1,
    }
