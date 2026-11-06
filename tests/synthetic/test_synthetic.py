"""Pure tests for the synthetic-fixture job (no network / no BQ)."""

import dataclasses
import json as _json
import os
import pathlib
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

from synthetic import adapters, coverage, inplay_pause, writers

_BASE_SERIES = adapters.SyntheticSeries(
    series_ticker="KXITFDOUBLES", sport_id="tennis", sport_name="Tennis",
    league_id="itf_men_doubles", league_name="ITF Men Doubles")


def _series(**overrides) -> adapters.SyntheticSeries:
    """A test SyntheticSeries with optional field overrides.

    Uses dataclasses.replace rather than splatting a dict into the constructor:
    a dict literal of only-str values infers as dict[str, str], and pyright then
    checks str against EVERY parameter, erroring on each non-str field
    (allow_backfill, ttko_hours, start_bias_minutes). replace()
    is typed **changes: Any, so it stays clean as fields are added.
    """
    return dataclasses.replace(_BASE_SERIES, **overrides)


# --- config loading -------------------------------------------------------

def test_load_series_from_shipped_toml():
    series = adapters.load_series()          # the series.toml shipped in synthetic/
    by_series = {s.series_ticker: s for s in series}
    assert {"KXITFMATCH", "KXITFWMATCH", "KXNASCARRACE"} <= set(by_series)
    # allow_backfill is permitted ONLY where the matcher can be league-scoped, and
    # run.py must pass series.league_id (it does). The original blanket ban existed
    # because load_optic_fixtures is scoped by SPORT: for tennis the candidate pool
    # is every atp/wta/challenger/utr/itf/doubles fixture in the window, so a
    # doubles event could false-match a player's same-day singles fixture. The
    # league filter in find_existing_fixture closes that; DOUBLES stays off anyway
    # because Optic has no itf_*_doubles league to attach to.
    # STILL OFF EVERYWHERE. Both prerequisites have landed (161005a):
    #   1. sport-scoped matcher -- find_existing_fixture takes league_id, run.py
    #      passes it;
    #   2. provenance-blind set-diff -- load_published_overrides also matches
    #      attributes.source='mm-synthetic', and publish_overrides no longer
    #      filters mapping_rows to wsdsyn- only, so a backfilled override
    #      (published under Optic's real game_id) both reaches `desired` AND is
    #      visible to the retraction diff. See
    #      test_publish_overrides_retracts_stale_backfill_key.
    #
    # It is nonetheless HELD OFF, as a risk decision rather than a missing-machinery
    # one -- see the allow_backfill note in series.toml. Briefly: the prize is zero
    # on ITF (all four Kalshi ITF series are moneyline, so there is no sibling
    # market to split against), and it would swap a CAUGHT failure (duplicate
    # fixture -> Alert E -> retracted in ~15 min) for a SILENT one (mis-attach ->
    # one fixture -> invisible to A/B/B2/E/D while the leg prices off another
    # match). The prod --dry-run gate is also unmet (IAM deny on the Kalshi secret).
    assert all(s.allow_backfill is False for s in series)
    # Every series must declare a TTKO gate; an unbounded one would admit season
    # futures. Values are per-series and deliberately differ.
    assert all(s.ttko_hours is not None for s in series)


def test_tennis_doubles_series_are_off():
    """Doubles intentionally off (2026-10-20): no block may re-enable them by accident."""
    tickers = {s.series_ticker for s in adapters.load_series()}
    for p in ("KXITFDOUBLES", "KXITFWDOUBLES", "KXATPCHALLENGERDOUBLES"):
        assert p not in tickers


# --- in-play pause (console pause plane) -----------------------------------

# mm-trading-dash backend/app/routers/market_pause.py `_pause_message`, in order.
_CONSOLE_PAUSE_FIELDS = ("scope", "tenant", "fixture_id", "market_id", "selection",
                         "paused", "ts_ms", "source", "operator")


def test_inplay_pause_message_is_the_console_wire_shape():
    """Field for field the console's `_pause_message`, so the maker MarketPauseRegistry
    canonicalizes it exactly like a console Fixture Pause."""
    msg = inplay_pause.pause_message(
        scope="fixture", tenant="kalshi-inplay", fixture_id="wsdsyn-KXITFMATCH-26SEP02VUJTAL",
        market_id=None, selection=None, paused=True, ts_ms=1700000000000, operator="ben")
    assert tuple(msg) == _CONSOLE_PAUSE_FIELDS
    assert msg["source"] == "mmmapper"
    assert msg["paused"] is True and msg["ts_ms"] == 1700000000000
    assert _json.loads(_json.dumps(msg)) == msg


def test_inplay_pause_fans_out_one_fixture_scope_message_per_inplay_tenant():
    msgs = inplay_pause.build_messages(
        ["wsdsyn-A", "wsdsyn-B"], inplay_pause.INPLAY_TENANTS, paused=True, operator="ben", ts_ms=1)
    assert len(msgs) == 2 * len(inplay_pause.INPLAY_TENANTS)
    assert {(m["fixture_id"], m["tenant"]) for m in msgs} == {
        (f, t) for f in ("wsdsyn-A", "wsdsyn-B") for t in inplay_pause.INPLAY_TENANTS}
    assert all(m["scope"] == "fixture" and m["market_id"] is None and m["selection"] is None
               for m in msgs)


def test_inplay_pause_default_tenants_are_the_inplay_books():
    assert set(inplay_pause.INPLAY_TENANTS) == {
        "kalshi-inplay", "novig-inplay", "polymarket-inplay", "polymarketus-inplay", "underdog-inplay"}
    assert all(t.endswith("-inplay") for t in inplay_pause.INPLAY_TENANTS)


def test_inplay_pause_refuses_out_of_scope_targets_before_publishing():
    """Only wsdsyn- ids and *-inplay tenants, checked before any network call: real fixtures
    are paused from the console."""
    with patch.object(inplay_pause, "publish") as pub:
        assert inplay_pause.main(["--fixture", "KXITFMATCH-26SEP02VUJTAL", "--apply"]) == 2
        assert inplay_pause.main(["--fixture", "wsdsyn-A", "--fixture", "wsdsyn-bad id", "--apply"]) == 2
        assert inplay_pause.main(["--fixture", "wsdsyn-A", "--tenant", "kalshi", "--apply"]) == 2
    pub.assert_not_called()


def test_inplay_pause_dry_run_publishes_nothing(capsys):
    with patch.object(inplay_pause, "publish") as pub:
        assert inplay_pause.main(["--fixture", "wsdsyn-A", "--operator", "ben"]) == 0
    pub.assert_not_called()
    msgs = [_json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    assert [m["tenant"] for m in msgs] == list(inplay_pause.INPLAY_TENANTS)
    assert all(m["paused"] is True and m["operator"] == "ben" for m in msgs)


def test_inplay_pause_apply_publishes_with_tenant_override_and_unpause():
    with patch.object(inplay_pause, "publish", return_value=["id-1"]) as pub:
        rc = inplay_pause.main(["--fixture", "wsdsyn-A", "--tenant", "kalshi-inplay", "--unpause",
                                "--operator", "ben", "--project", "marketmaking-test", "--apply"])
    assert rc == 0
    (project, messages), _ = pub.call_args
    assert project == "marketmaking-test"
    assert [(m["tenant"], m["paused"], m["source"], m["operator"]) for m in messages] == [
        ("kalshi-inplay", False, "mmmapper", "ben")]


def test_inplay_pause_reports_publish_failures():
    with patch.object(inplay_pause, "publish", return_value=["id-1", RuntimeError("boom")]):
        rc = inplay_pause.main(["--fixture", "wsdsyn-A", "--tenant", "kalshi-inplay",
                                "--tenant", "novig-inplay", "--apply"])
    assert rc == 1


def test_synthetic_scripts_no_longer_touch_the_odds_screen():
    """R_080: registration is gone (no book requires it) and pausing goes through the
    console pause plane. `rg -n "mm-odds-screen|/api/registrations" synthetic/` stays empty."""
    root = pathlib.Path(__file__).resolve().parents[2]
    assert not (root / "synthetic" / "register_inplay.py").exists()
    for path in (root / "synthetic").iterdir():
        if path.suffix in {".py", ".toml", ".md"}:
            body = path.read_text(encoding="utf-8")
            assert "mm-odds-screen" not in body and "/api/registrations" not in body, path


def test_no_wrapper_script_turns_inplay_betting_on():
    """Nothing in the repo may switch synthetic in-play betting on or off unattended.

    `infra/activate_synthetic_inplay.sh` was deleted deliberately: a blanket
    "register everything and set betting ON" entry point is the opposite of a kill
    switch, and it must not reappear as a script or a cron entry. `inplay_pause.py`
    is a manual CLI for the same reason.
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    assert not (root / "infra" / "activate_synthetic_inplay.sh").exists()
    crontab = root / "infra" / "crontab"
    if crontab.exists():
        body = crontab.read_text(encoding="utf-8")
        live = [ln for ln in body.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        for ln in live:
            assert not any(s in ln for s in ("register_inplay", "inplay_pause", "activate_synthetic")), (
                f"synthetic in-play controls must never be on cron: {ln!r}")


def test_load_series_atp_challenger_config():
    """ATP Challenger singles: shaped like ITF singles, but a DIFFERENT start bias.

    The bias is the whole point of this test. 346 (ITF's value) would put the
    estimated start ~3h before the true one, and since the gate admits at
    `est_start - ttko_hours`, that turns "map 1h before the off" into "map ~4h
    before" -- widening exactly the window ttko_hours=1 exists to close.

    Measured 2026-09-08, n=130 Challenger tickers Optic had already mapped:
    median 160, p75/p90/p95 = 180, max 180. 180 is the observed MAX, chosen so
    est_start is always at or before the true start.
    """
    by_series = {s.series_ticker: s for s in adapters.load_series()}
    s = by_series["KXATPCHALLENGERMATCH"]
    assert s.sport_id == "tennis" and s.sport_name == "Tennis"
    assert s.league_id == "atp_challenger"      # must match Optic's league_id exactly
    assert s.market_type == "match_winner"
    assert s.ttko_hours == 1                    # same late-mapping rule as ITF singles
    assert s.start_bias_minutes == 180          # NOT 346 -- see docstring
    assert s.write_greg_rows is False
    assert s.allow_backfill is False


def test_every_series_bias_is_plausible_for_its_shape():
    """A bias far larger than the match actually lasts silently widens the gate.

    Guards against the copy-paste failure this file exists to prevent: cloning an
    ITF entry for a new series and leaving 346 behind. Bounds are deliberately
    loose -- this catches an order-of-magnitude slip, not a fine calibration.
    """
    for s in adapters.load_series():
        assert 0 < s.start_bias_minutes <= 400, (
            f"{s.series_ticker}: start_bias_minutes={s.start_bias_minutes} is outside the "
            f"plausible range for any currently-onboarded market shape")


def test_load_series_nascar_outright_config():
    """NASCAR race winner: same outright shape as F1, but league "Nascar".

    Capitalised deliberately — the manual fixtures already in
    opticodds_us.opticodds_fixtures (windowworld450, tsport200, faithfest250)
    all carry "Nascar", and those are the rows that priced and traded.
    """
    by_series = {s.series_ticker: s for s in adapters.load_series()}
    s = by_series["KXNASCARRACE"]
    assert s.sport_id == "motorsports" and s.sport_name == "motorsports"
    assert s.league_id == "Nascar" and s.league_name == "Nascar"
    assert s.optic_market_id == "race_winner"
    assert s.market_type == "outright"
    assert s.start_bias_minutes == 360
    assert s.write_greg_rows is False


def test_shipped_toml_enabled_outrights():
    """NASCAR is the only outright currently live.

    F1 is staged but commented out — its book is too thin to quote (7 of 22
    contracts two-sided) and the one listed race is ~262h out. Uncommenting it
    should not need any other change, so this test names the live set explicitly:
    if F1 comes back, update it deliberately rather than discovering the drift.
    """
    outrights = [s for s in adapters.load_series() if s.market_type == "outright"]
    assert {s.series_ticker for s in outrights} == {"KXNASCARRACE"}
    # 360 min is verified against published start times for BOTH motorsports
    # leagues (Monza plus four NASCAR races), so it must hold for whichever are on.
    assert all(s.start_bias_minutes == 360 for s in outrights)
    assert all(s.sport_id == "motorsports" for s in outrights)
    # Outrights are a pre-off product: no GREG rows, so no in-play registration
    # and no split-fixture exposure.
    assert all(s.write_greg_rows is False for s in outrights)


# --- match day from the milestone -----------------------------------------

def test_match_day_is_0001_utc_on_the_milestone_day():
    assert adapters.match_day("2026-08-12T14:30:00Z") == \
        datetime(2026, 8, 12, 0, 1, tzinfo=UTC)
    # A late-evening start west of UTC is already the next UTC day.
    assert adapters.match_day("2026-08-12T22:30:00-04:00") == \
        datetime(2026, 8, 13, 0, 1, tzinfo=UTC)


def test_match_day_missing_or_bad_is_none():
    assert adapters.match_day(None) is None
    assert adapters.match_day("") is None
    assert adapters.match_day("not a date") is None


# --- estimated_start (TTKO gate) ------------------------------------------

def test_estimated_start_subtracts_bias():
    market = {"expected_expiration_time": "2026-08-19T14:00:00Z"}
    est = adapters.estimated_start(market, bias_minutes=346)
    expected = datetime(2026, 8, 19, 14, 0, tzinfo=UTC) - timedelta(minutes=346)
    assert est == expected


def test_estimated_start_no_bias():
    market = {"expected_expiration_time": "2026-08-19T14:00:00Z"}
    est = adapters.estimated_start(market, bias_minutes=0)
    assert est == datetime(2026, 8, 19, 14, 0, tzinfo=UTC)


def test_estimated_start_missing_field_returns_none():
    assert adapters.estimated_start({}, bias_minutes=346) is None
    assert adapters.estimated_start({"expected_expiration_time": ""}, bias_minutes=346) is None


def test_estimated_start_bad_format_returns_none():
    assert adapters.estimated_start(
        {"expected_expiration_time": "not-a-date"}, bias_minutes=0) is None


# --- estimated_start_for_event (modal expiration across a field) ----------

def _mk(exp):
    return {"expected_expiration_time": exp}


def test_estimated_start_for_event_uses_modal_not_first():
    """A single out-of-line runner must not move the fixture's start_date.

    Reproduces KXNASCARRACE-TSP2PBW26: 38 contracts at 05:00Z, one at 06:00Z.
    Putting the outlier first is exactly the ms[0] coin flip this replaces.
    """
    markets = [_mk("2026-07-25T06:00:00Z")] + [_mk("2026-07-25T05:00:00Z")] * 38
    est = adapters.estimated_start_for_event(markets, bias_minutes=360)
    assert est == datetime(2026, 7, 24, 23, 0, tzinfo=UTC)     # 05:00Z - 6h


def test_estimated_start_for_event_tie_breaks_to_earliest():
    """On a dead tie, take the earliest: an early start_date is the safe error."""
    markets = [_mk("2026-07-25T06:00:00Z"), _mk("2026-07-25T05:00:00Z")]
    est = adapters.estimated_start_for_event(markets, bias_minutes=0)
    assert est == datetime(2026, 7, 25, 5, 0, tzinfo=UTC)


def test_estimated_start_for_event_ignores_missing_values():
    markets = [_mk(None), _mk(""), _mk("2026-09-06T19:00:00Z")]
    est = adapters.estimated_start_for_event(markets, bias_minutes=360)
    assert est == datetime(2026, 9, 6, 13, 0, tzinfo=UTC)      # Italian GP, 15:00 CEST


def test_estimated_start_for_event_all_missing_is_none():
    """The season-future signal — every contract lacks the field."""
    assert adapters.estimated_start_for_event([_mk(None), _mk("")], 360) is None
    assert adapters.estimated_start_for_event([], 360) is None


# --- id determinism -------------------------------------------------------

def test_synthetic_game_id_deterministic_and_prefixed():
    gid = writers.synthetic_game_id("KXITFDOUBLES-26AUG12ALOMARPALYIL")
    assert gid == "wsdsyn-KXITFDOUBLES-26AUG12ALOMARPALYIL"
    assert gid.startswith(coverage.SYNTHETIC_PREFIX)
    assert writers.synthetic_game_id("KXITFDOUBLES-26AUG12ALOMARPALYIL") == gid


# --- fixture row shape ----------------------------------------------------

def test_build_fixture_row_sets_flat_and_nested():
    s = _series()  # KXITFDOUBLES → tennis / itf_men_doubles
    row = writers.build_fixture_row(
        "wsdsyn-x", s, "A / B", "C / D",
        "2026-08-12T00:01:00+00:00", "live", "2026-08-12T09:00:00+00:00")
    assert row["sport_id"] == "tennis"                 # flat — the sport gate
    assert row["sport"] == {"id": "tennis", "name": "Tennis"}   # nested — odds-screen
    assert row["league_id"] == "itf_men_doubles"
    assert row["league"]["name"] == "ITF Men Doubles"
    assert row["id"] == row["game_id"] == "wsdsyn-x"
    assert row["status"] == "live" and row["is_live"] is True


# --- mapping rows ---------------------------------------------------------

def test_build_mapping_rows_yes_no_per_ticker():
    s = _series()
    rows = writers.build_mapping_rows(
        s, "wsdsyn-x", "wsdsyn-x",
        "KXITFDOUBLES-26AUG12ALOMARPALYIL-ALOMAR", "Alopaeus / Martikainen",
        "KXITFDOUBLES-26AUG12ALOMARPALYIL-PALYIL", "Paldanius / Yilmaz",
        "2026-08-12T00:01:00+00:00", "2026-08-12T09:00:00+00:00")
    assert len(rows) == 4  # 2 sides x {yes,no}
    keys = {(r["source_ids"]["market_id"], r["source_ids"]["selection_id"]) for r in rows}
    assert keys == {
        ("KXITFDOUBLES-26AUG12ALOMARPALYIL-ALOMAR", "yes"),
        ("KXITFDOUBLES-26AUG12ALOMARPALYIL-ALOMAR", "no"),
        ("KXITFDOUBLES-26AUG12ALOMARPALYIL-PALYIL", "yes"),
        ("KXITFDOUBLES-26AUG12ALOMARPALYIL-PALYIL", "no"),
    }
    assert all(r["sportsbook"] == "Kalshi" for r in rows)
    assert all(r["fixture_id"] == "wsdsyn-x" for r in rows)


# --- mapping_override message (the pricing fix) --------------------------

def test_build_override_message_shape():
    import json as _json
    s = _series()
    rows = writers.build_mapping_rows(
        s, "wsdsyn-x", "wsdsyn-x",
        "KXITFDOUBLES-26AUG12ALOMARPALYIL-ALOMAR", "Alopaeus / Martikainen",
        "KXITFDOUBLES-26AUG12ALOMARPALYIL-PALYIL", "Paldanius / Yilmaz",
        "2026-08-12T00:01:00+00:00", "2026-08-12T09:00:00+00:00")
    msg = writers.build_override_message(rows[0])
    # proto-required fields present, correct types (line-less market -> 0 / "")
    assert msg["game_id"] == "wsdsyn-x"
    assert msg["sportsbook"] == "Kalshi"
    assert msg["market_id"] == s.optic_market_id
    assert msg["selection"] == "Alopaeus / Martikainen"
    assert msg["selection_line"] == ""
    assert isinstance(msg["points"], float) and msg["points"] == 0.0
    assert isinstance(msg["selection_points"], float) and msg["selection_points"] == 0.0
    assert msg["grouping_key"] == "default"
    assert msg["active"] is True
    # source_ids is a JSON STRING carrying ticker + side
    assert _json.loads(msg["source_ids"]) == {
        "market_id": "KXITFDOUBLES-26AUG12ALOMARPALYIL-ALOMAR",
        "selection_id": "yes",
    }


def test_build_override_message_active_false():
    s = _series()
    rows = writers.build_mapping_rows(
        s, "wsdsyn-x", "wsdsyn-x",
        "T-A", "A", "T-B", "B",
        "2026-08-12T00:01:00+00:00", "2026-08-12T09:00:00+00:00")
    msg = writers.build_override_message(rows[0], active=False)
    assert msg["active"] is False
    assert msg["game_id"] == "wsdsyn-x"


# --- override key ---------------------------------------------------------

def test_override_key_consistent_between_build_and_readback():
    s = _series()
    rows = writers.build_mapping_rows(
        s, "wsdsyn-x", "wsdsyn-x",
        "T-A", "PlayerA", "T-B", "PlayerB",
        "2026-08-12T00:01:00+00:00", "2026-08-12T09:00:00+00:00")
    msg = writers.build_override_message(rows[0])
    key1 = writers._override_key(msg)
    # Simulate a BQ read-back (sportsbook casing, IFNULL normalization)
    readback = {
        "game_id": "wsdsyn-x",
        "market_id": "moneyline",
        "sportsbook": "Kalshi",
        "selection": "PlayerA",
        "selection_line": "",
        "points": 0.0,
        "selection_points": 0.0,
        "grouping_key": "default",
    }
    key2 = writers._override_key(readback)
    assert key1 == key2


def test_override_key_lowercases_sportsbook():
    msg = {
        "game_id": "g", "market_id": "m", "sportsbook": "Kalshi",
        "selection": "s", "selection_line": "", "points": 0,
        "selection_points": 0, "grouping_key": "default",
    }
    assert writers._override_key(msg)[2] == "kalshi"


# --- publish_overrides ----------------------------------------------------

class _FakeClient:
    project = "marketmaking-test"


def _make_published(*entries):
    """Build a published dict. Each entry is (game_id, selection) or
    (game_id, selection, source_ids_json)."""
    published = {}
    for entry in entries:
        gid, sel = entry[0], entry[1]
        src = entry[2] if len(entry) > 2 else '{}'
        msg = {
            "game_id": gid, "market_id": "moneyline", "sportsbook": "Kalshi",
            "selection": sel, "selection_line": "", "points": 0.0,
            "selection_points": 0.0, "grouping_key": "default",
            "source_ids": src, "active": True,
        }
        published[writers._override_key(msg)] = msg
    return published


def _bq_published_from_rows(rows):
    """Published dict as BigQuery actually returns it.

    `_desired_from_rows` builds the published side with the SAME serializer as
    the desired side, so both carry json.dumps spacing and always compare equal.
    That blind spot is why the republish-every-run bug survived: in production
    the published side comes from TO_JSON_STRING, which is compact. This helper
    reproduces that, so tests using it see what the job really sees.
    """
    published = {}
    for r in rows:
        # Yes-side only, mirroring publish_overrides (see _desired_from_rows).
        if (r.get("source_ids") or {}).get("selection_id") != "yes":
            continue
        msg = writers.build_override_message(r)
        src = _json.loads(msg["source_ids"])
        msg = {**msg, "source_ids": _json.dumps(src, separators=(",", ":"))}
        published[writers._override_key(msg)] = msg
    return published


def _desired_from_rows(rows):
    """Build a desired dict from mapping rows (same logic as publish_overrides).

    The yes-side filter MIRRORS publish_overrides and must stay in step with it:
    the override key collapses on `selection`, so taking both sides would put
    ticker_b on both keys and drop ticker_a (see
    test_two_way_event_maps_both_kalshi_tickers).
    """
    desired = {}
    for r in rows:
        if (r.get("source_ids") or {}).get("selection_id") != "yes":
            continue
        msg = writers.build_override_message(r)
        desired[writers._override_key(msg)] = msg
    return desired


def _synth_rows():
    return writers.build_mapping_rows(
        _series(), "wsdsyn-x", "wsdsyn-x", "T-A", "A", "T-B", "B",
        "2026-08-12T00:01:00+00:00", "2026-08-12T09:00:00+00:00")


def test_publish_overrides_dryrun_previews_diff(monkeypatch):
    rows = _synth_rows()
    published = _desired_from_rows(rows)
    published.update(_make_published(("wsdsyn-stale", "Z")))
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: published)

    result = writers.publish_overrides(_FakeClient(), rows, dry_run=True)
    assert result["enabled"] == 0
    assert result["retracted"] == 0
    assert result["desired"] == 2
    assert result["would_enable"] == 0
    assert result["would_retract"] == 1
    assert result["unchanged"] == 2


def _backfill_rows():
    """Mapping rows for a BACKFILLED event: Optic's real game_id, not wsdsyn-."""
    return writers.build_mapping_rows(
        _series(), "1-2-2026-33", "20260813ABCD", "T-C", "C", "T-D", "D",
        "2026-08-12T00:01:00+00:00", "2026-08-12T09:00:00+00:00")


def test_publish_overrides_includes_backfill(monkeypatch):
    """Backfilled rows MUST get overrides — that is what puts the Kalshi ticker
    on Optic's real fixture. Previously they were filtered out by a wsdsyn-
    prefix test, so backfill silently published nothing at all."""
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: {})
    synth = _synth_rows()
    backfill = _backfill_rows()
    assert not any(r["game_id"].startswith("wsdsyn-") for r in backfill)
    result = writers.publish_overrides(_FakeClient(), synth + backfill, dry_run=True)
    assert result["desired"] == 4
    assert result["would_enable"] == 4


def test_publish_overrides_retracts_stale_backfill_key(monkeypatch):
    """The retraction path must work for backfilled keys too.

    This is the failure the provenance widening exists to prevent: a backfilled
    override that leaves the desired set and is never retracted, leaving
    active=true against a real Optic fixture with no teardown.
    """
    published = _desired_from_rows(_synth_rows() + _backfill_rows())
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: published)

    publishes = []

    class _FakePublisher:
        def topic_path(self, *a):
            return "t"

        def publish(self, _topic, data, **attrs):
            publishes.append((_json.loads(data.decode()), attrs))

            class _F:
                def result(self):
                    return None
            return _F()

    import google.cloud.pubsub_v1 as _ps
    monkeypatch.setattr(_ps, "PublisherClient", lambda: _FakePublisher())

    # desired now holds ONLY the synthetic rows — the backfilled event is gone
    result = writers.publish_overrides(_FakeClient(), _synth_rows())

    assert result["retracted"] == 2, "backfilled keys must be retracted"
    retracted = [m for m, _ in publishes if m["active"] is False]
    assert len(retracted) == 2
    assert all(not m["game_id"].startswith("wsdsyn-") for m in retracted)
    assert all(a.get("source") == "mm-synthetic" for _, a in publishes)


def test_load_published_overrides_query_is_provenance_aware():
    """The read-back must match backfilled rows (real game_id + provenance
    attribute) as well as legacy wsdsyn- rows, or the set-diff above cannot see
    them. Both clauses are load-bearing — see the writers docstring."""
    seen = {}

    class _CapturingClient:
        project = "marketmaking-test"

        def query(self, sql):
            seen["sql"] = sql

            class _R:
                def result(self):
                    return []
            return _R()

    writers.load_published_overrides(_CapturingClient())
    sql = seen["sql"]
    assert "STARTS_WITH(game_id, 'wsdsyn-')" in sql
    assert "JSON_VALUE(attributes, '$.source') = 'mm-synthetic'" in sql


def test_publish_overrides_retracts_stale_keys(monkeypatch):
    """Keys in published but not desired get active=false messages."""
    rows = _synth_rows()
    published = _desired_from_rows(rows)
    published.update(_make_published(("wsdsyn-stale", "Z")))
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: published)

    publishes = []
    mock_publisher = MagicMock()
    mock_publisher.topic_path.return_value = "test/topic"
    mock_publisher.publish.side_effect = lambda topic, data, **kw: (
        publishes.append(_json.loads(data)) or MagicMock()
    )
    with patch("google.cloud.pubsub_v1.PublisherClient", return_value=mock_publisher):
        result = writers.publish_overrides(_FakeClient(), rows)

    assert result["retracted"] == 1
    assert result["enabled"] == 0
    assert result["unchanged"] == 2
    retracted = [m for m in publishes if m["active"] is False]
    assert len(retracted) == 1
    assert retracted[0]["game_id"] == "wsdsyn-stale"


def test_publish_overrides_enables_new_keys(monkeypatch):
    """Keys in desired but not published get active=true messages."""
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: {})

    publishes = []
    mock_publisher = MagicMock()
    mock_publisher.topic_path.return_value = "test/topic"
    mock_publisher.publish.side_effect = lambda topic, data, **kw: (
        publishes.append(_json.loads(data)) or MagicMock()
    )
    with patch("google.cloud.pubsub_v1.PublisherClient", return_value=mock_publisher):
        result = writers.publish_overrides(_FakeClient(), _synth_rows())

    assert result["enabled"] == 2
    assert result["retracted"] == 0
    enabled = [m for m in publishes if m["active"] is True]
    assert len(enabled) == 2


def test_publish_overrides_empty_desired_skips_retraction(monkeypatch):
    """When desired is empty (API failure), retraction is blocked."""
    published = _make_published(("wsdsyn-x", "A"), ("wsdsyn-x", "B"))
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: published)

    with patch("google.cloud.pubsub_v1.PublisherClient") as mock_cls:
        result = writers.publish_overrides(_FakeClient(), [])
    assert result["retracted"] == 0
    assert result["enabled"] == 0
    mock_cls.assert_not_called()


def test_source_ids_equal_ignores_serialization_differences():
    """json.dumps spacing and BQ key ordering must not read as a change."""
    built = '{"market_id": "KXNASCARRACE-COKZS26-BOWM", "selection_id": "yes"}'
    readback = '{"market_id":"KXNASCARRACE-COKZS26-BOWM","selection_id":"yes"}'
    assert built != readback                      # the text really does differ
    assert writers._source_ids_equal(built, readback)
    # key order is normalised by a JSON-typed BQ column
    assert writers._source_ids_equal(
        '{"selection_id":"yes","market_id":"T-A"}',
        '{"market_id": "T-A", "selection_id": "yes"}')
    # genuine differences still register
    assert not writers._source_ids_equal(
        '{"market_id":"NEW"}', '{"market_id":"OLD"}')
    # empty / missing
    assert writers._source_ids_equal(None, "{}")
    assert writers._source_ids_equal(None, None)
    # unparseable is treated as changed, not silently equal
    assert not writers._source_ids_equal("not-json", '{"market_id":"T-A"}')


def test_publish_overrides_treats_bq_compact_source_ids_as_unchanged(monkeypatch):
    """REGRESSION: nothing to publish when only the JSON formatting differs.

    Before the _source_ids_equal fix this republished the whole desired set on
    every run, because the desired side is json.dumps (spaced) and the published
    side is BigQuery TO_JSON_STRING (compact). Observed in test as 79 NASCAR
    overrides re-sent on three consecutive 15-minute ticks with nothing changing
    underneath.
    """
    rows = _synth_rows()
    monkeypatch.setattr(writers, "load_published_overrides",
                        lambda _: _bq_published_from_rows(rows))

    with patch("google.cloud.pubsub_v1.PublisherClient") as mock_cls:
        result = writers.publish_overrides(_FakeClient(), rows)

    assert result["enabled"] == 0
    assert result["retracted"] == 0
    assert result["unchanged"] == 2
    mock_cls.assert_not_called()      # no publisher is even constructed


def test_publish_overrides_bq_compact_still_retracts_and_enables(monkeypatch):
    """The fix must not blunt the diff: a real add/remove still fires when the
    surviving keys arrive in BigQuery's compact form."""
    rows = _synth_rows()
    published = _bq_published_from_rows(rows)
    published.update(_make_published(("wsdsyn-stale", "Z")))
    # drop one desired key from published so it must be enabled
    published.pop(next(iter(_desired_from_rows(rows))))
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: published)

    publishes = []
    mock_publisher = MagicMock()
    mock_publisher.topic_path.return_value = "test/topic"
    mock_publisher.publish.side_effect = lambda topic, data, **kw: (
        publishes.append(_json.loads(data)) or MagicMock()
    )
    with patch("google.cloud.pubsub_v1.PublisherClient", return_value=mock_publisher):
        result = writers.publish_overrides(_FakeClient(), rows)

    assert result["enabled"] == 1
    assert result["retracted"] == 1
    assert result["unchanged"] == 1
    assert {m["active"] for m in publishes} == {True, False}


def test_publish_overrides_republishes_on_source_ids_change(monkeypatch):
    """Same key but different source_ids triggers a re-publish."""
    published = _make_published(("wsdsyn-x", "A"), ("wsdsyn-x", "B"))
    for msg in published.values():
        # compact, as BigQuery returns it — a real ticker change must still be
        # detected THROUGH the serialization difference, not because of it.
        msg["source_ids"] = '{"market_id":"OLD-TICKER","selection_id":"yes"}'
    monkeypatch.setattr(writers, "load_published_overrides", lambda _: published)

    publishes = []
    mock_publisher = MagicMock()
    mock_publisher.topic_path.return_value = "test/topic"
    mock_publisher.publish.side_effect = lambda topic, data, **kw: (
        publishes.append(_json.loads(data)) or MagicMock()
    )
    with patch("google.cloud.pubsub_v1.PublisherClient", return_value=mock_publisher):
        result = writers.publish_overrides(_FakeClient(), _synth_rows())

    assert result["enabled"] == 2
    assert result["retracted"] == 0
    assert result["unchanged"] == 0


# --- fixture existence match (backfill gate) ------------------------------

def _fx(home, away, d="2026-08-13"):
    return coverage.OpticFixture(
        id="20260813ABCD", game_id="1-2-2026-33",
        start_date=date.fromisoformat(d), home_u=home.upper(), away_u=away.upper())


def test_find_existing_fixture_matches_both_sides_either_orientation():
    fxs = [_fx("Samira De Stefano", "Alicia Herrero Linana")]
    # same orientation
    assert coverage.find_existing_fixture(
        "Samira De Stefano", "Alicia Herrero Linana", date(2026, 8, 13), fxs) \
        == ("1-2-2026-33", "20260813ABCD")
    # flipped orientation still matches
    assert coverage.find_existing_fixture(
        "Alicia Herrero Linana", "Samira De Stefano", date(2026, 8, 13), fxs) is not None


def test_find_existing_fixture_rejects_coincidental_single_token():
    # Davis Cup "Seydina Andre" must NOT match Optic "Andrea Paolini" etc.
    fxs = [_fx("Andrea Paolini", "Andrei Gadoiu")]
    assert coverage.find_existing_fixture(
        "Seydina Andre", "Connor Van Schalkwyk", date(2026, 8, 13), fxs) is None


def test_find_existing_fixture_rejects_out_of_window():
    fxs = [_fx("Samira De Stefano", "Alicia Herrero Linana", d="2026-08-20")]
    assert coverage.find_existing_fixture(
        "Samira De Stefano", "Alicia Herrero Linana", date(2026, 8, 13), fxs) is None


# --- outright builders (F1/NASCAR race winner) ----------------------------

# Mirrors the shipped KXNASCARRACE block — the only outright currently enabled.
_OUTRIGHT_SERIES = adapters.SyntheticSeries(
    series_ticker="KXNASCARRACE", sport_id="motorsports", sport_name="motorsports",
    league_id="Nascar", league_name="Nascar",
    optic_market_id="race_winner", market_type="outright",
    ttko_hours=336, start_bias_minutes=360, write_greg_rows=False)

# The staged-but-disabled F1 block, to prove the builders are config-driven and
# not NASCAR-specific.
_F1_SERIES = dataclasses.replace(
    _OUTRIGHT_SERIES, series_ticker="KXF1RACE",
    league_id="formulaone", league_name="formulaone")


def _outright_markets(n: int = 3) -> list[dict]:
    """Contracts off the real KXNASCARRACE-COKZS26 book (Coke Zero Sugar 400)."""
    names = ["Alex Bowman", "AJ Allmendinger", "Austin Cindric", "Bubba Wallace"]
    return [{"event_ticker": "KXNASCARRACE-COKZS26",
             "ticker": f"KXNASCARRACE-COKZS26-{name.split()[-1][:4].upper()}",
             "yes_sub_title": name,
             # 7:30pm ET start -> 23:30Z; Kalshi reports start + 360 min.
             "expected_expiration_time": "2026-08-30T05:30:00Z"}
            for name in names[:n]]


def test_build_outright_fixture_row_matches_manual_template():
    """Key set must equal the 2-way row's; the manual F1 rows carry ''/False."""
    row = writers.build_outright_fixture_row(
        "wsdsyn-KXNASCARRACE-COKZS26", _OUTRIGHT_SERIES,
        "2026-08-29T23:30:00+00:00", "", "2026-08-26T09:00:00+00:00")
    two_way = writers.build_fixture_row(
        "wsdsyn-x", _BASE_SERIES, "A / B", "C / D",
        "2026-08-12T00:01:00+00:00", "live", "2026-08-12T09:00:00+00:00")
    assert set(row) == set(two_way)          # same columns, no missing field
    assert row["id"] == row["game_id"] == "wsdsyn-KXNASCARRACE-COKZS26"
    # A 22-car field has no two sides.
    assert row["home_team_display"] == "" and row["away_team_display"] == ""
    # name == id, lower case — what the manual fixtures carry.
    assert row["sport"] == {"id": "motorsports", "name": "motorsports"}
    assert row["league"] == {"id": "Nascar", "name": "Nascar"}
    assert row["status"] == "" and row["is_live"] is False


def test_build_outright_fixture_row_is_live_tracks_status():
    row = writers.build_outright_fixture_row(
        "wsdsyn-x", _OUTRIGHT_SERIES, "2026-08-29T23:30:00+00:00", "live", "now")
    assert row["is_live"] is True


def test_build_outright_mapping_rows_yes_side_only():
    """One row per contract, yes side only — an outright has no other side."""
    rows = writers.build_outright_mapping_rows(
        _OUTRIGHT_SERIES, "wsdsyn-COKZS26", "wsdsyn-COKZS26",
        _outright_markets(3), "2026-09-06T13:00:00+00:00", "2026-08-26T09:00:00+00:00")
    assert len(rows) == 3                                  # NOT 6 — no "no" rows
    assert {r["source_ids"]["selection_id"] for r in rows} == {"yes"}
    assert all(r["market_id"] == "race_winner" for r in rows)
    assert all(r["sportsbook"] == "Kalshi" for r in rows)
    assert all(r["home"] == "" and r["away"] == "" for r in rows)
    assert {r["selection"] for r in rows} == {
        "Alex Bowman", "AJ Allmendinger", "Austin Cindric"}


def test_build_outright_mapping_rows_distinct_override_keys():
    """N runners must give N DISTINCT override keys.

    The single highest-risk invariant in the outright path. `_override_key`
    deliberately excludes `source_ids`, so the Kalshi ticker does NOT distinguish
    rows — and for an outright, game_id / market_id / sportsbook / grouping_key
    are all constant across runners and the numeric fields are all 0. `selection`
    is the ONLY discriminator. If two runners ever shared a selection they would
    collapse onto one key and all but one runner would silently stop pricing.
    """
    rows = writers.build_outright_mapping_rows(
        _OUTRIGHT_SERIES, "wsdsyn-COKZS26", "wsdsyn-COKZS26",
        _outright_markets(4), "2026-09-06T13:00:00+00:00", "2026-08-26T09:00:00+00:00")
    keys = {writers._override_key(writers.build_override_message(r)) for r in rows}
    assert len(keys) == len(rows) == 4
    # ...and selection is what makes them differ: blank it and they collapse.
    collapsed = {writers._override_key(
        {**writers.build_override_message(r), "selection": ""}) for r in rows}
    assert len(collapsed) == 1


def test_build_outright_mapping_rows_selection_falls_back_to_the_whole_ticker():
    markets = [{"event_ticker": "KXNASCARRACE-COKZS26",
                "ticker": "KXNASCARRACE-COKZS26-BOWM", "yes_sub_title": "",
                "expected_expiration_time": "2026-08-30T05:30:00Z"}]
    rows = writers.build_outright_mapping_rows(
        _OUTRIGHT_SERIES, "wsdsyn-x", "wsdsyn-x", markets,
        "2026-08-29T23:30:00+00:00", "now")
    assert rows[0]["selection"] == "KXNASCARRACE-COKZS26-BOWM"


def test_build_override_message_consumes_outright_row():
    """An outright row has no selection_points key at all — must not KeyError."""
    rows = writers.build_outright_mapping_rows(
        _OUTRIGHT_SERIES, "wsdsyn-x", "wsdsyn-x", _outright_markets(1),
        "2026-09-06T13:00:00+00:00", "now")
    msg = writers.build_override_message(rows[0])
    assert msg["game_id"] == "wsdsyn-x"
    assert msg["market_id"] == "race_winner"
    assert msg["selection"] == "Alex Bowman"
    assert msg["active"] is True


# --- run.py: --only safety + GREG scoping ---------------------------------

def _run_module():
    """Import synthetic.run lazily.

    fetch.kalshi reads GCP_PROJECT at IMPORT time (kalshi.py:31), so a module-level
    `from synthetic import run` would make the whole test file un-collectable
    outside a configured shell. Nothing here hits GCP — every client and reconcile
    step is patched out — so any project value will do.
    """
    os.environ.setdefault("GCP_PROJECT", "marketmaking-test")
    from synthetic import run as _run
    return _run



_TWO_SERIES_TOML = """
[[series]]
series_ticker = "KXITFDOUBLES"
sport_id = "tennis"
sport_name = "Tennis"
league_id = "itf_men_doubles"
league_name = "ITF Men Doubles"
optic_market_id = "moneyline"
ttko_hours = 100000
start_bias_minutes = 346
write_greg_rows = true

[[series]]
series_ticker = "KXNASCARRACE"
sport_id = "motorsports"
sport_name = "motorsports"
league_id = "Nascar"
league_name = "Nascar"
optic_market_id = "race_winner"
market_type = "outright"
ttko_hours = 336
start_bias_minutes = 360
write_greg_rows = false
"""


def _write_config(tmp_path) -> str:
    cfg = tmp_path / "series.toml"
    cfg.write_text(_TWO_SERIES_TOML, encoding="utf-8")
    return str(cfg)


def test_run_refuses_to_write_with_only(tmp_path):
    """--only + write would tear down every series it did NOT run.

    reconcile_mappings blanket-deletes all wsdsyn- rows, reconcile_fixtures flips
    everything not in live_ids to 'completed', and publish_overrides set-diffs
    against the FULL published set — all three are scoped by wsdsyn- game_id, not
    by series. So the guard must fire BEFORE any client is constructed.
    """
    run_mod = _run_module()
    with patch.object(run_mod, "ro_client") as mock_client:
        rc = run_mod.run(_write_config(tmp_path), only_series="KXNASCARRACE",
                         dry_run=False)
    assert rc == 2
    mock_client.assert_not_called()          # nothing touched, not even a client


_MILESTONES = {"KXITFDOUBLES-26AUG12ALOMARPALYIL": {"start_date": "2026-08-12T10:00:00Z"}}


def _run_with_stubs(config_path, only_series=None, dry_run=False):
    """Run the job with Kalshi + BQ + all three reconcile steps stubbed out."""
    run_mod = _run_module()
    exp = (datetime.now(UTC) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    itf_markets = [
        {"event_ticker": "KXITFDOUBLES-26AUG12ALOMARPALYIL",
         "ticker": f"KXITFDOUBLES-26AUG12ALOMARPALYIL-{side}",
         "yes_sub_title": name, "expected_expiration_time": exp}
        for side, name in (("ALOMAR", "Alopaeus / Martikainen"),
                           ("PALYIL", "Paldanius / Yilmaz"))
    ]
    race_markets = [{**m, "expected_expiration_time": exp} for m in _outright_markets(3)]

    def fake_fetch(series_ticker, key_id, private_key):
        return race_markets if series_ticker == "KXNASCARRACE" else itf_markets

    stubs = {
        "ro_client": MagicMock(return_value=MagicMock(project="marketmaking-test")),
        "load_credentials": MagicMock(return_value=("kid", "pem")),
        "fetch_milestones": MagicMock(return_value=_MILESTONES),
        "fetch_markets": MagicMock(side_effect=fake_fetch),
    }
    calls = {}
    with (patch.multiple(run_mod, **stubs),
          patch.object(run_mod.coverage, "load_covered_tickers", return_value=set()),
          patch.object(run_mod.writers, "reconcile_fixtures") as rf,
          patch.object(run_mod.writers, "reconcile_mappings") as rm,
          patch.object(run_mod.writers, "publish_overrides") as po):
        rc = run_mod.run(config_path, only_series, dry_run)
        calls["rc"] = rc
        calls["fixtures"] = rf.call_args[0][1] if rf.call_args else None
        calls["greg"] = rm.call_args[0][1] if rm.call_args else None
        calls["overrides"] = po.call_args[0][1] if po.call_args else None
    return calls


def test_run_writes_greg_rows_only_for_series_that_want_them(tmp_path):
    """write_greg_rows=false keeps F1 out of market_mapping but NOT out of the
    overrides — the overrides are what makes a fixture priceable."""
    c = _run_with_stubs(_write_config(tmp_path))
    assert c["rc"] == 0
    # 2 fixtures synthesized: one ITF match, one F1 race.
    assert len(c["fixtures"]) == 2
    # Overrides get the FULL set: 4 ITF rows (2 tickers x yes/no) + 3 F1 runners.
    assert len(c["overrides"]) == 7
    # GREG gets only the ITF rows.
    assert len(c["greg"]) == 4
    assert all(r["league"] == "itf_men_doubles" for r in c["greg"])
    assert not any(r["market_id"] == "race_winner" for r in c["greg"])


def test_run_outright_fixture_not_live_before_start(tmp_path):
    """est is 24h-360min out, so the F1 fixture must not be flagged in-play."""
    c = _run_with_stubs(_write_config(tmp_path))
    race = [r for r in c["fixtures"] if r["sport_id"] == "motorsports"]
    assert len(race) == 1
    assert race[0]["status"] == "" and race[0]["is_live"] is False
    assert race[0]["id"] == "wsdsyn-KXNASCARRACE-COKZS26"


def test_run_match_day_comes_from_the_milestone(tmp_path):
    calls = _run_with_stubs(_write_config(tmp_path))
    itf = [f for f in calls["fixtures"] if f["sport_id"] == "tennis"]
    assert [f["start_date"] for f in itf] == ["2026-08-12T00:01:00+00:00"]


def test_run_skips_a_match_with_no_milestone(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "_MILESTONES", {})
    calls = _run_with_stubs(_write_config(tmp_path))
    assert [f for f in calls["fixtures"] if f["sport_id"] == "tennis"] == []


def test_run_outright_rejects_market_with_no_expiration(tmp_path):
    """No expected_expiration_time is the season-future signal: reject, don't
    fall through to a fabricated start_date."""
    run_mod = _run_module()
    stubs = {
        "ro_client": MagicMock(return_value=MagicMock(project="marketmaking-test")),
        "load_credentials": MagicMock(return_value=("kid", "pem")),
        "fetch_milestones": MagicMock(return_value=_MILESTONES),
        "fetch_markets": MagicMock(return_value=[
            {"event_ticker": "KXNASCARRACE-NCS26",
             "ticker": "KXNASCARRACE-NCS26-BOWM",
             "yes_sub_title": "Alex Bowman"}]),
    }
    with (patch.multiple(run_mod, **stubs),
          patch.object(run_mod.coverage, "load_covered_tickers", return_value=set()),
          patch.object(run_mod.writers, "reconcile_fixtures") as rf,
          patch.object(run_mod.writers, "reconcile_mappings"),
          patch.object(run_mod.writers, "publish_overrides") as po):
        cfg = tmp_path / "raceonly.toml"
        cfg.write_text(_TWO_SERIES_TOML.split("[[series]]")[0]
                       + "[[series]]" + _TWO_SERIES_TOML.split("[[series]]")[2],
                       encoding="utf-8")
        assert run_mod.run(str(cfg), None, dry_run=False) == 0
    assert rf.call_args[0][1] == []          # no fixture minted
    assert po.call_args[0][1] == []          # no override published


def test_run_outright_respects_ttko(tmp_path):
    """A race beyond ttko_hours is gated out, not synthesized."""
    run_mod = _run_module()
    far = (datetime.now(UTC) + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stubs = {
        "ro_client": MagicMock(return_value=MagicMock(project="marketmaking-test")),
        "load_credentials": MagicMock(return_value=("kid", "pem")),
        "fetch_milestones": MagicMock(return_value=_MILESTONES),
        "fetch_markets": MagicMock(return_value=[
            {"event_ticker": "KXNASCARRACE-DAY27",
             "ticker": "KXNASCARRACE-DAY27-BOWM",
             "yes_sub_title": "Alex Bowman", "expected_expiration_time": far}]),
    }
    with (patch.multiple(run_mod, **stubs),
          patch.object(run_mod.coverage, "load_covered_tickers", return_value=set()),
          patch.object(run_mod.writers, "reconcile_fixtures") as rf,
          patch.object(run_mod.writers, "reconcile_mappings"),
          patch.object(run_mod.writers, "publish_overrides")):
        cfg = tmp_path / "raceonly.toml"
        cfg.write_text(_TWO_SERIES_TOML.split("[[series]]")[0]
                       + "[[series]]" + _TWO_SERIES_TOML.split("[[series]]")[2],
                       encoding="utf-8")
        assert run_mod.run(str(cfg), None, dry_run=False) == 0
    assert rf.call_args[0][1] == []


def test_run_skips_outright_when_any_runner_already_covered(tmp_path):
    """All-or-nothing: one hand-mapped runner suppresses the whole race rather
    than leaving a partly-mapped field."""
    run_mod = _run_module()
    exp = (datetime.now(UTC) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    covered = {"KXNASCARRACE-COKZS26-CIND"}
    stubs = {
        "ro_client": MagicMock(return_value=MagicMock(project="marketmaking-test")),
        "load_credentials": MagicMock(return_value=("kid", "pem")),
        "fetch_milestones": MagicMock(return_value=_MILESTONES),
        "fetch_markets": MagicMock(return_value=[
            {**m, "expected_expiration_time": exp} for m in _outright_markets(3)]),
    }
    with (patch.multiple(run_mod, **stubs),
          patch.object(run_mod.coverage, "load_covered_tickers", return_value=covered),
          patch.object(run_mod.writers, "reconcile_fixtures") as rf,
          patch.object(run_mod.writers, "reconcile_mappings"),
          patch.object(run_mod.writers, "publish_overrides") as po):
        cfg = tmp_path / "raceonly.toml"
        cfg.write_text(_TWO_SERIES_TOML.split("[[series]]")[0]
                       + "[[series]]" + _TWO_SERIES_TOML.split("[[series]]")[2],
                       encoding="utf-8")
        assert run_mod.run(str(cfg), None, dry_run=False) == 0
    assert rf.call_args[0][1] == []
    assert po.call_args[0][1] == []


# ---------------------------------------------------------------------------
# Backfill league scoping. load_optic_fixtures is scoped by SPORT, so for tennis
# the candidate pool includes atp / wta / atp_challenger / utr_* / itf_* /
# *_doubles (791 fixtures on 2026-09-01). Matching an ITF singles event onto a
# same-day UTR fixture with the same surnames would publish our Kalshi orderbook
# prices under a DIFFERENT match's fixture id — worse than the duplicate fixture
# backfill exists to avoid. These pin the filter that prevents it.
# ---------------------------------------------------------------------------

def _league_fx(fid, league, home, away, d="2026-09-02"):
    from datetime import date
    y, m, dd = (int(x) for x in d.split("-"))
    return coverage.OpticFixture(fid, fid, date(y, m, dd), home.upper(), away.upper(), league)


_POOL = [
    _league_fx("utr-1", "utr_men", "Stefan Vujic", "Marko Talic"),      # same names, WRONG league
    _league_fx("itf-1", "itf_men", "Stefan Vujic", "Marko Talic"),      # the right one
    _league_fx("chal-1", "atp_challenger", "Stefan Vujic", "Marko Talic"),
]


def test_backfill_matches_only_within_the_league():
    from datetime import date
    got = coverage.find_existing_fixture(
        "Stefan Vujic", "Marko Talic", date(2026, 9, 2), _POOL, league_id="itf_men")
    assert got == ("itf-1", "itf-1")


def test_backfill_refuses_a_cross_league_false_match():
    """The exact mis-route the blanket allow_backfill ban was guarding against."""
    from datetime import date
    pool = [f for f in _POOL if f.league_id != "itf_men"]   # only UTR + Challenger
    got = coverage.find_existing_fixture(
        "Stefan Vujic", "Marko Talic", date(2026, 9, 2), pool, league_id="itf_men")
    assert got is None


def test_backfill_unscoped_still_matches_anything():
    """league_id=None keeps the old permissive behaviour for existing callers."""
    from datetime import date
    got = coverage.find_existing_fixture(
        "Stefan Vujic", "Marko Talic", date(2026, 9, 2), _POOL)
    assert got is not None


def test_run_passes_league_id_into_the_matcher(monkeypatch):
    """run.py must actually pass series.league_id — the filter is useless otherwise."""
    seen = {}
    real = coverage.find_existing_fixture

    def spy(name_a, name_b, day, fixtures, league_id=None):
        seen["league_id"] = league_id
        return real(name_a, name_b, day, fixtures, league_id)

    import inspect
    src = inspect.getsource(_run_module().run)
    assert "league_id=series.league_id" in src, \
        "run.py no longer passes league_id to find_existing_fixture"


# ---------------------------------------------------------------------------
# THE INVARIANT THAT WAS MISSING: a 2-way synthetic event must map BOTH of its
# Kalshi tickers, not one.
#
# `_override_key` excludes source_ids (it has to match prices_state_merge's
# active_overrides GROUP BY), so it collapses on `selection`. The four rows
# build_mapping_rows emits therefore produced only two keys, BOTH carrying
# ticker_b -- ticker_a was silently dropped. Measured in prod 2026-09-04: all 80
# live synthetic events had 1.0 distinct tickers instead of 2, on doubles as well
# as singles, since the job went live. publish_overrides now takes the yes side
# of each ticker.
# ---------------------------------------------------------------------------

def _two_way_rows():
    """The four rows build_mapping_rows emits for one 2-way match."""
    return writers.build_mapping_rows(
        _BASE_SERIES, "wsdsyn-KXITFMATCH-26SEP04GARROD",
        "wsdsyn-KXITFMATCH-26SEP04GARROD",
        "KXITFMATCH-26SEP04GARROD-GAR", "Alejandro Garcia Carbajal",
        "KXITFMATCH-26SEP04GARROD-ROD", "Pedro Rodenas",
        "2026-09-04T00:01:00+00:00", "now")


def _desired_from(rows, monkeypatch):
    """Run publish_overrides in dry-run and capture the desired override set."""
    captured = {}
    real_key = writers._override_key

    def spy(msg):
        k = real_key(msg)
        captured[k] = msg
        return k

    monkeypatch.setattr(writers, "_override_key", spy)
    monkeypatch.setattr(writers, "load_published_overrides", lambda _c: {})
    writers.publish_overrides(MagicMock(project="p"), rows, dry_run=True)
    return captured


def test_two_way_event_maps_both_kalshi_tickers(monkeypatch):
    """The regression. Both tickers must survive into the desired override set."""
    desired = _desired_from(_two_way_rows(), monkeypatch)
    tickers = {_json.loads(m["source_ids"])["market_id"] for m in desired.values()}
    assert tickers == {
        "KXITFMATCH-26SEP04GARROD-GAR",
        "KXITFMATCH-26SEP04GARROD-ROD",
    }, f"only these tickers survived: {tickers}"


def test_override_set_is_yes_side_only(monkeypatch):
    """Each surviving row is the YES side of its own ticker."""
    desired = _desired_from(_two_way_rows(), monkeypatch)
    sides = {_json.loads(m["source_ids"])["selection_id"] for m in desired.values()}
    assert sides == {"yes"}, sides
    assert len(desired) == 2, f"expected 2 override keys, got {len(desired)}"


def test_selection_pairs_with_the_ticker_it_wins_on(monkeypatch):
    """Garcia must ride -GAR and Rodenas -ROD, not swapped."""
    desired = _desired_from(_two_way_rows(), monkeypatch)
    pairs = {m["selection"]: _json.loads(m["source_ids"])["market_id"]
             for m in desired.values()}
    assert pairs == {
        "Alejandro Garcia Carbajal": "KXITFMATCH-26SEP04GARROD-GAR",
        "Pedro Rodenas": "KXITFMATCH-26SEP04GARROD-ROD",
    }, pairs


def test_outright_unaffected_by_the_yes_filter(monkeypatch):
    """Outrights already emit yes-side only, so every runner must survive."""
    rows = writers.build_outright_mapping_rows(
        _OUTRIGHT_SERIES, "wsdsyn-x", "wsdsyn-x", _outright_markets(4),
        "2026-09-04T00:00:00+00:00", "now")
    desired = _desired_from(rows, monkeypatch)
    assert len(desired) == 4, f"expected 4 runners, got {len(desired)}"


def test_greg_rows_still_carry_all_four_sides():
    """The fix is scoped to the OVERRIDE path. GREG keeps both sides of both
    tickers, because mapping_loader's greg_raw partitions on
    (market_id, selection_id) and can represent them."""
    rows = _two_way_rows()
    combos = {(r["source_ids"]["market_id"], r["source_ids"]["selection_id"])
              for r in rows}
    assert len(combos) == 4, combos
    assert {s for _, s in combos} == {"yes", "no"}
