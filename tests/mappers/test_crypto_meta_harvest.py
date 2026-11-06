"""crypto_security_def harvest SQL: recency, close event_date, unbounded."""

from mappers.control_plane.gap_inventory import CLOSE_MAX_DAYS
from mappers.crypto_meta import CLOSE_EVENT_DAYS, SECDEF_HARVEST_SQL, harvest_team_ids_from_fix


def test_close_event_days_match_inventory() -> None:
    assert CLOSE_EVENT_DAYS == CLOSE_MAX_DAYS == 3


def test_harvest_sql_keeps_close_events_without_fresh_publish() -> None:
    sql = SECDEF_HARVEST_SQL.format(
        table="processed_upstream_us.crypto_security_def",
        league="UFC",
        days=30,
        close_days=CLOSE_EVENT_DAYS,
    )
    assert "{days} <= 0" in SECDEF_HARVEST_SQL
    assert "meta_event_date" in sql
    assert "interval 30 day" in sql
    assert "interval 3 day" in sql
    assert "meta_league = 'UFC'" in sql


def test_unbounded_harvest_sql_skips_publish_cutoff() -> None:
    sql = SECDEF_HARVEST_SQL.format(
        table="processed_upstream_us.crypto_security_def",
        league="UFC",
        days=0,
        close_days=CLOSE_EVENT_DAYS,
    )
    assert "0 <= 0" in sql


def test_harvest_fn_is_importable() -> None:
    assert callable(harvest_team_ids_from_fix)
