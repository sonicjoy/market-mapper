"""Overrides payload, league registry overlay, and PnL PDF rendering."""

import json
import re
from datetime import date
from unittest.mock import MagicMock

from google.api_core.exceptions import NotFound

from goalscorer.config import DEFAULT_LEAGUES, LEAGUES_TABLE, MAPPING_SOURCE, League
from goalscorer.leagues import LeagueRegistry
from goalscorer.overrides import OverridePublisher, override_message
from goalscorer.pnl_pdf import PnlReport, describe_leg, fmt_dollar, render, series_name, split_leg
from goalscorer.pnl_queries import LegRow, LossCombo, SeriesRow, goal_leg_regex, soccer_goal_prefixes


def test_override_message_matches_proto_shape():
    msg = override_message("g1", "Bukayo Saka", "KXEPLGOAL-P-ARSBSAKA7-1")
    assert msg["market_id"] == "anytime_goal_scorer" and msg["sportsbook"] == "Kalshi"
    assert msg["mapping_source"] == MAPPING_SOURCE and msg["grouping_key"] == "default"
    assert json.loads(msg["source_ids"]) == {"market_id": "KXEPLGOAL-P-ARSBSAKA7-1", "selection_id": "yes"}
    assert OverridePublisher("p", dry_run=True).publish([msg]) == 0
    assert override_message("g1", "Bukayo Saka", "T", active=False)["active"] is False


def _registry(rows=None, exc=None):
    client = MagicMock()
    if exc:
        client.query.side_effect = exc
    else:
        client.query.return_value.result.return_value = rows or []
    return LeagueRegistry(client, "proj")


def _row(league_id, prefix, active=True):
    return MagicMock(league_id=league_id, goal_prefix=prefix, display_name=league_id, sport="soccer", active=active)


def test_registry_overlays_table_on_defaults():
    rows = [_row("international_-_friendlies", "KXINTLFRIENDLYGOAL"), _row("uefa_-_champions_league", "X", False)]
    leagues = _registry(rows).active()
    assert "international_-_friendlies" in leagues and "uefa_-_champions_league" not in leagues
    assert leagues["england_-_premier_league"].goal_prefix == "KXEPLGOAL"


def test_registry_falls_back_to_defaults_when_table_missing():
    leagues = _registry(exc=NotFound(f"Not found: Table proj:{LEAGUES_TABLE}")).active()
    assert set(leagues) == {"spain_-_la_liga", "england_-_premier_league", "uefa_-_champions_league"}


def test_insert_knowledge_skips_taken_selection_or_ticker(monkeypatch):
    from goalscorer import store as store_mod
    from goalscorer.models import KnowledgeRow
    from tests.goalscorer.fakes import KICKOFF, goal

    store = store_mod.GoalscorerStore(MagicMock(), "proj")
    taken = [goal("g1", "Bukayo Saka", "ARSBSAKA7-1", part="P"), goal("g1", "Someone", "ARSXTAKEN1-1", part="P")]
    monkeypatch.setattr(store, "goal_mappings", lambda *a: taken)
    sent = {}

    def fake_sandbox(client, sql, job_config):
        sent["rows"] = job_config.query_parameters[0].values
        return MagicMock(num_dml_affected_rows=len(sent["rows"]))

    monkeypatch.setattr(store_mod, "sandbox_query", fake_sandbox)
    rows = [
        KnowledgeRow("g1", KICKOFF, "soccer", "EPL", "Bukayo Saka", "KXEPLGOAL-P-ARSBSAKA99-1"),  # selection taken
        KnowledgeRow("g1", KICKOFF, "soccer", "EPL", "New Name", "KXEPLGOAL-P-ARSXTAKEN1-1"),  # ticker taken
        KnowledgeRow("g1", KICKOFF, "soccer", "EPL", "Mikel Merino", "KXEPLGOAL-P-ARSMMERIN1-1"),
    ]
    assert store.insert_knowledge(rows) == 1
    assert len(sent["rows"]) == 1


def test_pnl_leg_regex_covers_soccer_series_only():
    leagues = [*DEFAULT_LEAGUES, League("nhl", "KXNHLGOAL", "NHL", "hockey")]
    prefixes = soccer_goal_prefixes(leagues)
    assert prefixes == [
        "KXEPLFIRSTGOAL",
        "KXEPLGOAL",
        "KXLALIGAFIRSTGOAL",
        "KXLALIGAGOAL",
        "KXUCLFIRSTGOAL",
        "KXUCLGOAL",
    ]
    pattern = re.compile(goal_leg_regex(prefixes))
    assert pattern.match("KXEPLGOAL-26AUG25ARSCHE-ARSBSAKA7-1")
    assert pattern.match("KXUCLFIRSTGOAL-26OCT13GALBAR-BARLYAMAL10")
    assert not pattern.match("KXNHLFIRSTGOAL-26OCT13BOSSJ-BOSCMCAVOY73")
    assert not pattern.match("KXNHLGOAL-26SEP25TORBOS-TORAMATT34-1")
    assert not pattern.match("KXEPLGAME-26AUG25ARSCHE-ARS")


def test_pdf_helpers():
    assert fmt_dollar(1234.4) == "+$1,234" and fmt_dollar(-0.5) == "-$0.50"
    assert series_name("KXEPLGOAL, KXSERIEAGOAL") == "EPL + SERIEA"
    assert series_name("KXUCLFIRSTGOAL, KXUCLGOAL") == "UCL First Goal + UCL"
    assert series_name("KXSERIEAFIRSTGOAL") == "SERIEA First Goal"
    assert split_leg("KXUCLFIRSTGOAL-26OCT13GALBAR-BARLYAMAL10") == ("BARLYAMAL10 FG", "GALBAR")
    assert describe_leg("KXUCLFIRSTGOAL-26OCT13GALBAR-BARLYAMAL10") == "UCL First Goal BARLYAMAL10"
    assert describe_leg("KXEPLTOTAL-26SEP26ARSCHE-3") == "EPL Total ARS/CHE o3"
    assert describe_leg("KXEPLGAME-26SEP26ARSCHE-ARS") == "EPL ML ARS"


def test_render_writes_a_pdf(tmp_path):
    total = SeriesRow("", 3, 3, 2, 1, -40.0, 120.0, 300.0, 1.5)
    epl = SeriesRow("KXEPLGOAL", 3, 3, 2, 1, -40.0, 120.0, 300.0, 1.5)
    legs = [
        LegRow("KXEPLGOAL-26SEP26ARSCHE-ARSBSAKA7-1", 2, 80.0, 200.0, -60.0),
        LegRow("KXEPLGOAL-X-Y1-1", 1, 40, 100, 20),
    ]
    losses = [LossCombo("KXMVECROSSCATEGORY-ABC", -60.0, 80.0, 200.0, ["KXEPLGAME-26SEP26ARSCHE-ARS"])]
    report = PnlReport(date(2026, 9, 26), ([epl], total), [("7-Day", [epl], total)], legs, losses)
    path = render(report, tmp_path / "r.pdf")
    assert path.read_bytes().startswith(b"%PDF")
