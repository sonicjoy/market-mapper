"""The VM pipeline must fetch EVERY wired league.

`infra/run_pipeline.sh` used to hand-list the leagues passed to `fetch.optic`.
"atp_challenger" was added to every other registry — mappers.run.LEAGUES,
fetch.SUPPORTED_LEAGUES, fetch.LEAGUE_SECRET, the pipeline's tennis gate and
tennis_bootstrap — while that one line still omitted it, so the league was fully
wired and silently produced ZERO rows in production. Nothing failed; it just
mapped nothing.

The list is now derived from mappers.run.api_fetch_league_keys (tip when
SoT=bq, else every LEAGUES key). These tests guard the derivation
itself, since a future edit back to a literal list would reintroduce
exactly the same silent gap.
"""

import os
import re
from pathlib import Path

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")


_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "run_pipeline.sh"
_FETCH_CALL = re.compile(r"-m fetch --league (?P<args>[^\n]*?) --out-dir")


def _fetch_args() -> str:
    m = _FETCH_CALL.search(_SCRIPT.read_text(encoding="utf-8"))
    assert m is not None, f"no `-m fetch --league ... --out-dir` call in {_SCRIPT}"
    return m.group("args").strip()


def test_pipeline_passes_a_derived_league_list_not_a_literal():
    """The fetch call must interpolate a variable, never enumerate leagues."""
    args = _fetch_args()
    assert args.startswith("$"), (
        f"run_pipeline.sh passes a literal league list to fetch ({args!r}). "
        "Derive it from mappers.run.api_fetch_league_keys instead — a hand-maintained list "
        "silently drops newly wired leagues."
    )


def test_pipeline_derives_the_list_from_the_registry():
    src = _SCRIPT.read_text(encoding="utf-8")
    var = _fetch_args().lstrip("$").strip("{}")
    # DOTALL + non-greedy: the assignment is a multi-line command substitution
    # once the BQ-sourced exclusion is applied, so this must not be line-anchored.
    assign = re.search(
        rf"^{re.escape(var)}=\$\((?P<cmd>.*?)\)$", src, re.M | re.S
    )
    assert assign is not None, f"{var} is not assigned from a command substitution"
    cmd = assign.group("cmd")
    assert "mappers.run" in cmd and "api_fetch_league_keys" in cmd, (
        f"{var} must be derived from mappers.run.api_fetch_league_keys, got: {cmd!r}"
    )


def test_pipeline_does_not_exclude_a_bq_optic_list():
    """BQ_OPTIC_LEAGUES is gone — every wired league is on the API fetch."""
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "BQ_OPTIC_LEAGUES" not in src


def test_former_bq_optic_leagues_are_on_the_api_fetch():
    from mappers.run import api_fetch_league_keys

    produced = set(api_fetch_league_keys())
    for slug in (
        "atp_challenger",
        "itf_men",
        "itf_women",
        "korea_k1",
        "korea_k2",
        "china_super_league",
        "norway_eliteserien",
        "peru_primera_division",
        "conmebol_sudamericana",
        "mlb",
        "nba",
        "nfl",
    ):
        assert slug in produced


def test_pipeline_map_uses_same_league_list_as_fetch():
    """Main map must use the same $FETCH_LEAGUES as fetch.optic."""
    src = _SCRIPT.read_text(encoding="utf-8")
    assert re.search(
        r"-m mappers\.run .*--league \$FETCH_LEAGUES",
        src,
    ), (
        "run_pipeline.sh must pass --league $FETCH_LEAGUES to mappers.run "
        "(align map with fetch)"
    )


def test_derivation_command_yields_tip_leagues():
    """api_fetch_league_keys returns enabled tip leagues plus code leagues."""
    from mappers.run import api_fetch_league_keys
    from mappers.seed.code_leagues import CODE_LEAGUES
    from mappers.seed.sot import load_snapshot

    produced = api_fetch_league_keys()
    enabled_tip = {
        str(row.league) for row in load_snapshot().leagues if row.enabled
    }
    assert "atp_challenger" in produced
    assert "itf_men" in produced
    assert "itf_women" in produced
    assert "china_super_league" in produced
    assert "korea_k1" in produced
    assert "mlb" in produced
    assert "nba" in produced
    assert set(CODE_LEAGUES) <= set(produced)
    for slug in produced:
        assert slug in enabled_tip or slug in CODE_LEAGUES, (
            f"{slug} is neither an enabled tip league nor a code league"
        )
