"""Substitute crypto.com mapping-gap SQL for manual drill-down.

``scripts/print_crypto_gap_sql.py`` and the investigation probe print
these queries. The mapper tick does not run them; gap-propose drafts
the repairs.
"""

from __future__ import annotations

from pathlib import Path

from BigQuery.crypto_gap_config import (
    GapLeagueConfig,
    distinct_gap_leagues,
    fixture_prefix_re,
    leagues_struct_sql,
    sql_string_list,
)

_SQL_DIR = Path(__file__).resolve().parent / "sql"

SQL_PATH = _SQL_DIR / "crypto_mapping_gaps_summary.sql"
DETAIL_SQL_PATH = _SQL_DIR / "crypto_mapping_gaps.sql"
ALL_CORE_SQL_PATH = _SQL_DIR / "crypto_mapping_gaps_all_core.sql"
ALL_SQL_PATH = _SQL_DIR / "crypto_mapping_gaps_all_summary.sql"
ALL_DETAIL_SQL_PATH = _SQL_DIR / "crypto_mapping_gaps_all.sql"


def _strip_sql_header_comments(template: str) -> str:
    lines: list[str] = []
    for line in template.splitlines():
        if not lines and (not line.strip() or line.strip().startswith("--")):
            continue
        lines.append(line)
    return "\n".join(lines)


def _substitute_gap_sql(template: str, project: str, league: GapLeagueConfig) -> str:
    sql = template.replace("{project}", project)
    sql = sql.replace("{league_prefix}", league.league_prefix)
    sql = sql.replace("{optic_horizon_hours}", str(league.optic_horizon_hours))
    sql = sql.replace("{mapped_player_props}", sql_string_list(league.player_props))
    sql = sql.replace("{mapped_game_lines}", sql_string_list(league.game_lines))
    sql = sql.replace("{mapped_team_props}", sql_string_list(league.team_props))
    sql = sql.replace("{mapped_game_props}", sql_string_list(league.game_props))
    sql = sql.replace("{optic_league_ids}", sql_string_list(league.optic_league_ids))
    return sql.replace("{fixture_prefix_re}", fixture_prefix_re(league.league_prefix))


def load_summary_sql(project: str, league: GapLeagueConfig) -> str:
    """Load the gap summary SQL template with league substitutions."""
    template = SQL_PATH.read_text(encoding="utf-8")
    return _strip_sql_header_comments(_substitute_gap_sql(template, project, league))


def load_detail_sql(project: str, league: GapLeagueConfig) -> str:
    """Load the per-symbol gap drill-down SQL with league substitutions."""
    template = DETAIL_SQL_PATH.read_text(encoding="utf-8")
    return _strip_sql_header_comments(_substitute_gap_sql(template, project, league))


def _sorted_gap_leagues() -> list[GapLeagueConfig]:
    """Leagues in a stable order for the SQL dimension literal."""
    return sorted(distinct_gap_leagues(), key=lambda g: g.league_prefix)


def _substitute_all_gap_sql(
    template: str,
    project: str,
    leagues: list[GapLeagueConfig],
) -> str:
    """Compose a consolidated gap query: shared core + this template's tail."""
    core = ALL_CORE_SQL_PATH.read_text(encoding="utf-8")
    sql = template.replace("{core}", core)
    sql = sql.replace("{project}", project)
    return sql.replace("{leagues_struct}", leagues_struct_sql(leagues))


def load_all_summary_sql(project: str, leagues: list[GapLeagueConfig] | None = None) -> str:
    """Load the one summary gap query covering every crypto-enabled league."""
    template = ALL_SQL_PATH.read_text(encoding="utf-8")
    return _strip_sql_header_comments(
        _substitute_all_gap_sql(template, project, leagues or _sorted_gap_leagues())
    )


def load_all_detail_sql(project: str, leagues: list[GapLeagueConfig] | None = None) -> str:
    """Load the one per-symbol gap query covering every crypto-enabled league."""
    template = ALL_DETAIL_SQL_PATH.read_text(encoding="utf-8")
    return _strip_sql_header_comments(
        _substitute_all_gap_sql(template, project, leagues or _sorted_gap_leagues())
    )
