"""Official Polymarket dated-slug extraction for Mapper Chat probes."""

from __future__ import annotations

from mappers.exchanges.poly_slug import find_poly_slug, parse_poly_slug, slug_gap_kind


def test_parse_bundesliga_exact_score_slug() -> None:
    slug = "bun-stu-koe-2026-09-04-exact-score-0-0"
    parsed = parse_poly_slug(slug)
    assert parsed is not None
    assert parsed.prefix == "bun"
    assert parsed.home == "stu"
    assert parsed.away == "koe"
    assert parsed.date == "2026-09-04"
    assert parsed.suffix == "exact-score-0-0"
    assert slug_gap_kind(parsed.suffix) == "exact_score"


def test_find_poly_slug_in_do_we_map_question() -> None:
    slug = "bun-stu-koe-2026-09-04-exact-score-0-0"
    msg = f"do we map this ticker: `{slug}`"
    assert parse_poly_slug(msg) is None
    assert find_poly_slug(msg) == slug


def test_filler_prefix_is_not_a_slug() -> None:
    assert parse_poly_slug("do-we-map-2026-09-04") is None
    assert find_poly_slug("do we map this") == ""
