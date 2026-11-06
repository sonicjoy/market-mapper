"""Tests for regression/config_diff.py (step 5, the gate).

Fixture canonical files are written through config_project so the
compared forms are real; run() is exercised end to end (exit codes,
classification, printed accounting) with today pinned."""
import datetime

import pytest

from regression.config_project import canon_all
from regression.config_diff import (
    config_matches,
    diff_files,
    load_config_waivers,
    run,
)
from regression.waivers import WaiverError

TODAY = datetime.date(2026, 8, 14)


def entity(league, key, name, **over):
    rec = {"league": league, "entity_type": "team",
           "canonical_key": key, "canonical_name": name,
           "enabled": True}
    rec.update(over)
    return "entity", rec


def alias(league, key, sportsbook, value):
    return "alias", {"league": league, "entity_type": "team",
                     "canonical_key": key, "sportsbook": sportsbook,
                     "alias_kind": "code", "alias_value": value,
                     "enabled": True}


def rule(league, sportsbook, source_key):
    return "market_rule", {"league": league, "sportsbook": sportsbook,
                           "source_key_type": "ticker_type",
                           "source_key": source_key, "action": "map",
                           "priority": 100, "enabled": True}


def write(tmp_path, name, records):
    lines, _ = canon_all(records)
    p = tmp_path / f"{name}.v1.jsonl"
    p.write_text("".join(li + "\n" for li in lines))
    return p


def waivers_file(tmp_path, body):
    p = tmp_path / "waivers.toml"
    p.write_text(body)
    return p


QUOTED_WAIVER = '''
audit = "test-audit"

[[waiver]]
id = "quoted-names"
reason = "extractor drops quoted display names — ask 4"
match = { direction = "both", kind = "entity", league = "lol" }
max_rows = 2
expires = 2026-09-13
'''


# --- diffing ---------------------------------------------------------------

def test_identical_files_pass(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks")])
    b = write(tmp_path, "b", [entity("nba", "ATL", "Atlanta Hawks")])
    assert run(a, b, today=TODAY) == 0
    out = capsys.readouterr().out
    assert "MATCHED: 1" in out and "GATE PASS" in out


def test_annotations_do_not_affect_equality(tmp_path):
    a = write(tmp_path, "a", [("entity", dict(
        entity("nba", "ATL", "Atlanta Hawks")[1], source="x.toml"))])
    b = write(tmp_path, "b", [("entity", dict(
        entity("nba", "ATL", "Atlanta Hawks")[1], alias_id="deadbeef"))])
    assert run(a, b, today=TODAY) == 0


def test_surplus_on_either_side_is_unexplained(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks"),
                              entity("nba", "BOS", "Boston Celtics")])
    b = write(tmp_path, "b", [entity("nba", "ATL", "Atlanta Hawks"),
                              entity("nba", "BKN", "Brooklyn Nets")])
    assert run(a, b, today=TODAY) == 1
    out = capsys.readouterr().out
    assert "UNEXPLAINED: 2" in out
    assert "A_ONLY" in out and "B_ONLY" in out


def test_changed_value_prints_as_paired_change(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("lol", "DK.C",
                                     "Dplus KIA Challengers")])
    b = write(tmp_path, "b", [entity("lol", "DK.C", None)])
    assert run(a, b, today=TODAY) == 1
    out = capsys.readouterr().out
    assert "CHANGED" in out and "UNEXPLAINED: 2" in out


# --- structural scope --------------------------------------------------------

def test_only_kinds_restricts_both_sides(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks")])
    b = write(tmp_path, "b", [entity("nba", "ATL", "Atlanta Hawks"),
                              rule("nba", "kalshi", "SPREAD")])
    assert run(a, b, only_kinds={"entity", "alias"}, today=TODAY) == 0
    assert "1 lines out of scope" in capsys.readouterr().out


def test_exclude_poly_overlay_drops_both_sides_and_prints(tmp_path,
                                                          capsys):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks")])
    b = write(tmp_path, "b", [
        entity("nba", "ATL", "Atlanta Hawks"),
        entity("nba", "poly_name:hawks", "Hawks"),
        alias("nba", "poly_name:hawks", "polymarket", "Hawks")])
    assert run(a, b, exclude_poly=True, today=TODAY) == 0
    assert "EXCLUDED (decision-1 boundary): 2" in \
        capsys.readouterr().out


def test_version_mismatch_refused(tmp_path):
    a = write(tmp_path, "a", [])
    b = tmp_path / "b.v2.jsonl"
    b.write_text("")
    assert run(a, b, today=TODAY) == 2


# --- waivers ------------------------------------------------------------------

def test_waiver_covers_changed_pair_and_prints(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("lol", "DK.C",
                                     "Dplus KIA Challengers")])
    b = write(tmp_path, "b", [entity("lol", "DK.C", None)])
    w = waivers_file(tmp_path, QUOTED_WAIVER)
    assert run(a, b, waivers_path=w, audit="test-audit", today=TODAY) == 0
    out = capsys.readouterr().out
    assert "WAIVED(quoted-names): 2" in out and "GATE PASS" in out


def test_breached_waiver_waives_nothing(tmp_path, capsys):
    a = write(tmp_path, "a", [
        entity("lol", "DK.C", "Dplus KIA Challengers"),
        entity("lol", "DRX.C", "DRX Challengers")])
    b = write(tmp_path, "b", [entity("lol", "DK.C", None),
                              entity("lol", "DRX.C", None)])
    w = waivers_file(tmp_path, QUOTED_WAIVER)  # ceiling 2, matches 4
    assert run(a, b, waivers_path=w, audit="test-audit", today=TODAY) == 1
    out = capsys.readouterr().out
    assert "BREACHED" in out and "UNEXPLAINED: 4" in out


def test_stale_waiver_named_for_deletion(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks")])
    b = write(tmp_path, "b", [entity("nba", "ATL", "Atlanta Hawks")])
    w = waivers_file(tmp_path, QUOTED_WAIVER)
    assert run(a, b, waivers_path=w, audit="test-audit", today=TODAY) == 0
    assert "STALE waiver 'quoted-names'" in capsys.readouterr().out


def test_blanket_waiver_is_a_file_error(tmp_path):
    w = waivers_file(tmp_path, '''
audit = "test-audit"

[[waiver]]
id = "blanket"
reason = "everything"
match = { direction = "both" }
max_rows = 1000
expires = 2026-09-13
''')
    with pytest.raises(WaiverError, match="must include"):
        load_config_waivers(w, TODAY, audit="test-audit")


def test_waiver_never_crosses_kind_or_league():
    w = {"match": {"direction": "both", "kind": "entity",
                   "league": "lol"}}
    lol_alias = {"direction": "a_only",
                 "rec": {"t": "alias",
                         "k": ["lol", "team", "DK.C", "kalshi",
                               "code", "DKC"]}}
    nba_entity = {"direction": "a_only",
                  "rec": {"t": "entity", "k": ["nba", "team", "ATL"]}}
    assert not config_matches(w, lol_alias)
    assert not config_matches(w, nba_entity)


def test_canonical_market_deltas_are_unwaivable():
    w = {"match": {"direction": "both", "kind": "canonical_market",
                   "league": "any"}}
    d = {"direction": "b_only",
         "rec": {"t": "canonical_market", "k": ["point_spread"]}}
    assert not config_matches(w, d)


# --- comment loss ----------------------------------------------------------------

COMMENT_WAIVER = '''
audit = "test-audit"

[comment_loss]
reason = "comments only partially migrate — redesign ask 4"
expires = 2026-09-13
'''


def report_file(tmp_path):
    p = tmp_path / "report.json"
    p.write_text('{"nba": {"files": 1, "comments": 10, '
                 '"migrated": 7, "lost": 3, "unknown_keys": []}}')
    return p


def test_comment_loss_prints_as_expected_loss(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks")])
    b = write(tmp_path, "b", [entity("nba", "ATL", "Atlanta Hawks")])
    w = waivers_file(tmp_path, COMMENT_WAIVER)
    assert run(a, b, waivers_path=w, audit="test-audit",
               comment_report=report_file(tmp_path), today=TODAY) == 0
    out = capsys.readouterr().out
    assert "EXPECTED-LOSS (comment_loss): 3" in out


def test_comment_report_without_waiver_section_fails(tmp_path, capsys):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks")])
    b = write(tmp_path, "b", [entity("nba", "ATL", "Atlanta Hawks")])
    assert run(a, b, comment_report=report_file(tmp_path),
               today=TODAY) == 1
    assert "no [comment_loss] section" in capsys.readouterr().out


def test_expired_comment_loss_section_is_an_error(tmp_path):
    w = waivers_file(tmp_path, COMMENT_WAIVER)
    after = datetime.date(2026, 9, 14)
    with pytest.raises(WaiverError, match="not furniture"):
        load_config_waivers(w, after, audit="test-audit")


def test_the_checked_in_waivers_file_is_valid():
    waivers, cl = load_config_waivers(
        "regression/config_waivers.toml", TODAY,
        audit="reader-vs-extractor")
    assert len(waivers) == 4
    assert cl is not None


# --- diff_files unit ---------------------------------------------------------------

def test_diff_files_sorted_and_directional(tmp_path):
    a = write(tmp_path, "a", [entity("nba", "ATL", "Atlanta Hawks")])
    b = write(tmp_path, "b", [entity("nba", "BOS", "Boston Celtics")])
    deltas, stats = diff_files(a, b)
    assert [(d["direction"], d["rec"]["k"][2]) for d in deltas] == \
        [("a_only", "ATL"), ("b_only", "BOS")]
    assert stats["matched"] == 0


# --- audit binding ------------------------------------------------------------------

def test_waivers_file_refused_for_a_different_audit(tmp_path, capsys):
    """The Uwinks lesson, enforced mechanically: an entity-audit
    waiver file passed to a tip-audit run refuses to classify."""
    a = write(tmp_path, "a", [entity("lol", "UWI", "Uwinks")])
    b = write(tmp_path, "b", [])
    w = waivers_file(tmp_path, QUOTED_WAIVER)
    assert run(a, b, waivers_path=w, audit="tip-audit",
               today=TODAY) == 2
    assert "declared for audit 'test-audit'" in \
        capsys.readouterr().out


def test_waivers_without_audit_flag_refused(tmp_path):
    w = waivers_file(tmp_path, QUOTED_WAIVER)
    with pytest.raises(WaiverError, match="pass --audit"):
        load_config_waivers(w, TODAY)


def test_undeclared_waivers_file_is_invalid(tmp_path):
    w = waivers_file(tmp_path, QUOTED_WAIVER.replace(
        'audit = "test-audit"\n', ""))
    with pytest.raises(WaiverError, match="bound to one audit"):
        load_config_waivers(w, TODAY, audit="test-audit")
