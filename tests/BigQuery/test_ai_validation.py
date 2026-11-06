"""Tests for the AI mapping validator: fingerprint, prompts, verdict join, alerts.

Pure functions only — no BigQuery, no Gemini, no network (repo convention for
the BigQuery tests).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from BigQuery.ai_validation import (
    FIXTURE_PAD_DAYS,
    PROMPT_VERSION,
    SPORTSBOOKS,
    Verdict,
    _fingerprint_expr,
    build_prompt,
    build_sql,
    derive_mapping_ok,
    exchange_ref,
    exchange_side,
    exchange_text,
    format_summary,
    has_exchange_text,
    mask_exchange_dates,
    partition_chunks,
    row_line,
    strip_slug_date,
    summarize_flags,
    system_prompt_for,
    verdict_rows,
)
from BigQuery.load_mappings import KEY_COLUMNS

START = datetime(2026, 7, 30, 15, 0, tzinfo=UTC)


def _kalshi_row(**over) -> dict:
    row = {
        "row_fingerprint": "fp-kalshi",
        "sportsbook": "Kalshi",
        "sport": "tennis",
        "league": "atp",
        "start_date": START,
        "et_date": date(2026, 7, 30),
        "home": "NAK",
        "away": "MEN",
        "market_type": "moneyline",
        "entity": None,
        "line": None,
        "side": "NAK",
        "group_key": None,
        "game_id": "20408-30104-2026-30",
        "market_id": "moneyline",
        "selection": "Brandon Nakashima",
        "selection_line": "",
        "points": 0.0,
        "grouping_key": "default",
        "src_market_id": "KXATPMATCH-26JUL30NAKMEN-NAK",
        "src_selection_id": "yes",
        "src_symbol": None,
        "fixture_name": "Brandon Nakashima v Jakub Mensik",
        "kalshi_title": "Will Brandon Nakashima win the Nakashima vs Mensik: Round Of 16 match?",
        "kalshi_sub": None,
        "poly_question": None,
        "poly_outcome": None,
        "poly_slug": None,
        "cc_selection": None,
        "cc_event": None,
        "cc_participant": None,
        "cc_home": None,
        "cc_away": None,
        "cc_period": None,
        "cc_contract": None,
        "cc_family": None,
        "novig_market_desc": None,
        "novig_outcome_desc": None,
        "novig_player_name": None,
    }
    row.update(over)
    return row


def _poly_row(**over) -> dict:
    return _kalshi_row(
        **{
            "row_fingerprint": "fp-poly",
            "sportsbook": "Polymarket",
            "src_market_id": None,
            "src_selection_id": "10460541055086995053613266111616443689343363851749426216430316935458564405897",
            "kalshi_title": None,
            "poly_question": "Bonn: Tom Gentzsch vs Max Dahlin",
            "poly_outcome": "Tom Gentzsch",
            "poly_slug": "atp-gentzsc-dahlin-2026-07-30",
            **over,
        }
    )


def _crypto_row(**over) -> dict:
    return _kalshi_row(
        **{
            "row_fingerprint": "fp-crypto",
            "sportsbook": "crypto.com",
            "src_market_id": None,
            "src_selection_id": None,
            "src_symbol": "NX.F.OPT.TENNIS-0011-260730-M.O.1.2.20261231",
            "kalshi_title": None,
            "cc_selection": "Brandon Nakashima to win",
            "cc_event": "Nakashima vs Mensik",
            "cc_participant": "Brandon Nakashima",
            "cc_period": "Full-Game",
            "cc_contract": "Moneyline",
            "cc_family": "Game Line",
            **over,
        }
    )


def _novig_row(**over) -> dict:
    return _kalshi_row(
        **{
            "row_fingerprint": "fp-novig",
            "sportsbook": "Novig",
            "src_market_id": "novig-mkt-1",
            "src_selection_id": "novig-outcome-under",
            "kalshi_title": None,
            "novig_market_desc": "Total Rebounds",
            "novig_outcome_desc": "Under 2.5",
            "novig_player_name": "Jonquel Jones",
            **over,
        }
    )


# === Fingerprint ===


def test_fingerprint_covers_every_merge_key_column():
    """A key column added to market_mapping must land in the fingerprint too.

    This is the regression that silently breaks the never-revisit contract: a new
    identity column not in the hash makes two distinct mappings collide, and the
    second one is never judged.
    """
    expr = _fingerprint_expr()
    for column in KEY_COLUMNS:
        assert column in expr, f"{column} missing from the fingerprint"
    assert "source_ids" in expr, "source_ids must be hashed: a re-mapped ticker has to re-judge"


def test_fingerprint_uses_stable_timestamp_and_float_forms():
    """Timestamps hash as millis and lines at fixed precision — no format drift."""
    expr = _fingerprint_expr()
    assert "UNIX_MILLIS(start_date)" in expr
    assert "FORMAT('%.4f', line)" in expr


def test_fingerprint_expr_qualifies_with_alias():
    """The alias form is what a JOIN needs."""
    assert "m.start_date" in _fingerprint_expr("m")


# === Input SQL ===


def test_build_sql_anti_joins_already_judged_rows():
    """Default run skips rows that already have a verdict at this prompt version."""
    sql = build_sql("proj", revalidate=False, include_corroborated=False)
    assert f"v.prompt_version = {PROMPT_VERSION}" in sql
    assert "v.row_fingerprint IS NULL" in sql
    assert "(0 = 1 OR v.row_fingerprint IS NULL)" in sql


def test_build_sql_revalidate_disables_the_anti_join():
    """--revalidate re-judges the window."""
    sql = build_sql("proj", revalidate=True, include_corroborated=False)
    assert "(1 = 1 OR v.row_fingerprint IS NULL)" in sql


def test_build_sql_skips_optic_corroborated_rows_by_default():
    """Corroborated rows are excluded unless explicitly included."""
    default = build_sql("proj", revalidate=False, include_corroborated=False)
    included = build_sql("proj", revalidate=False, include_corroborated=True)
    assert "(0 = 1 OR o.game_id IS NULL)" in default
    assert "(1 = 1 OR o.game_id IS NULL)" in included


def test_build_sql_pads_the_fixture_lookup_window():
    """Fixture names must survive a fixture whose Optic start_date drifted.

    Filtering opticodds_fixtures by the mapping window itself lost the readable
    matchup for 55 tennis rows, and the model then fell back to the slug date.
    """
    sql = build_sql("proj", revalidate=False, include_corroborated=False)
    assert f"TIMESTAMP_SUB(@date_from, INTERVAL {FIXTURE_PAD_DAYS} DAY)" in sql
    assert f"TIMESTAMP_ADD(@date_to, INTERVAL {FIXTURE_PAD_DAYS} DAY)" in sql


def test_build_sql_never_lets_one_null_team_erase_the_fixture_name():
    """CONCAT() with a NULL argument returns NULL, not a partial string."""
    sql = build_sql("proj", revalidate=False, include_corroborated=False)
    assert "IFNULL(home_team_display, '')" in sql
    assert "IFNULL(away_team_display, '')" in sql


def test_build_sql_only_reads_the_windowed_partition():
    """Both sides of the window are bound parameters on the partition column."""
    sql = build_sql("proj", revalidate=False, include_corroborated=False)
    assert "start_date BETWEEN @date_from AND @date_to" in sql
    assert "proj.markets_us.market_mapping" in sql


# === Prompt assembly ===


def test_system_prompt_carries_only_the_batch_exchange_rules():
    """A Kalshi batch must not pay for the Polymarket or crypto rules."""
    kalshi = system_prompt_for("Kalshi")
    assert "THRESHOLD RULE" in kalshi
    assert "POLYMARKET encoding" not in kalshi
    assert "CRYPTO.COM encoding" not in kalshi
    assert "NOVIG encoding" not in kalshi

    poly = system_prompt_for("Polymarket")
    assert "POLYMARKET encoding" in poly
    assert "THRESHOLD RULE" not in poly

    novig = system_prompt_for("Novig")
    assert "NOVIG encoding" in novig
    assert "THRESHOLD RULE" not in novig
    assert "POLYMARKET encoding" not in novig


def test_system_prompt_always_defines_every_verdict():
    """Each verdict the model must return is described in the core prompt."""
    prompt = system_prompt_for("Kalshi")
    for field in ("fixture_ok", "market_ok", "side_ok", "line_ok", "entity_ok", "mapping_ok"):
        assert field in prompt


def test_row_line_kalshi_pairs_our_bet_with_ticker_and_title():
    line = row_line(0, _kalshi_row())
    assert line.startswith("0. OURS ")
    assert "KALSHI t=KXATPMATCH-*NAKMEN-NAK s=yes" in line
    assert "Will Brandon Nakashima win" in line
    assert "POLY" not in line and "CRYPTO" not in line


def test_row_line_poly_shows_outcome_label_and_dateless_slug():
    line = row_line(1, _poly_row())
    assert "POLY q='Bonn: Tom Gentzsch vs Max Dahlin'" in line
    assert "outcome='Tom Gentzsch'" in line
    assert "slug=atp-gentzsc-dahlin" in line
    assert "slug=atp-gentzsc-dahlin-2026-07-30" not in line


def test_row_line_crypto_shows_selection_text_event_and_scope():
    """The selection text carries side AND line, so it must always be rendered."""
    line = row_line(2, _crypto_row(cc_home="Jakub Mensik", cc_away="Brandon Nakashima"))
    assert "CRYPTO sym=NX.F.OPT.TENNIS-0011-*-M.O.1.2.20261231" in line
    assert "sel='Brandon Nakashima to win'" in line
    assert "event='Nakashima vs Mensik'" in line
    assert "home='Jakub Mensik' away='Brandon Nakashima'" in line
    assert "period='Full-Game'" in line
    assert "contract='Moneyline'" in line


def test_row_line_novig_shows_outcome_market_and_player():
    """`sel` alone never names a player prop's player -- `who` does."""
    line = row_line(3, _novig_row(entity="Jonquel Jones", market_type="player_rebounds"))
    assert "NOVIG sel='Under 2.5'" in line
    assert "mkt='Total Rebounds'" in line
    assert "who='Jonquel Jones'" in line


def test_row_line_novig_omits_who_when_not_a_player_prop():
    line = row_line(0, _novig_row(novig_player_name=None))
    assert "who=" not in line


def test_row_line_shows_no_date_on_either_side():
    """Dates are the matcher's join key, not evidence for the judge.

    Three prompt versions told the model to discount them and it flagged on them
    anyway (100% of rows in v1, 126 in v2, 10 in v4); removing them is the fix.
    """
    line = row_line(0, _kalshi_row(start_date=datetime(2026, 8, 2, 0, 0, tzinfo=UTC), et_date=date(2026, 8, 1)))
    assert "2026-08-02" not in line
    assert "2026-08-01" not in line
    assert "et=" not in line


def test_mask_exchange_dates_blanks_kalshi_ticker_dates():
    assert mask_exchange_dates("KXATPMATCH-26AUG01KOVBOR-KOV") == "KXATPMATCH-*KOVBOR-KOV"
    assert mask_exchange_dates("KXWC1H-26JUN27FRAGER-FRA") == "KXWC1H-*FRAGER-FRA"


def test_mask_exchange_dates_blanks_crypto_symbol_dates():
    masked = str(mask_exchange_dates("NX.F.OPT.TENNIS-0011-260730-M.O.1.2.20261231"))
    assert "260730" not in masked
    # the trailing 20261231 is a contract-expiry token, not the event date
    assert masked.endswith("M.O.1.2.20261231")


def test_mask_exchange_dates_leaves_team_codes_and_none_alone():
    assert mask_exchange_dates("KXNFLSPREAD-CARARI-ARI5") == "KXNFLSPREAD-CARARI-ARI5"
    assert mask_exchange_dates(None) is None


def test_system_prompt_states_there_are_no_dates_to_judge():
    prompt = system_prompt_for("Kalshi")
    assert "THERE ARE NO DATES IN THIS TASK" in prompt


def test_system_prompt_forbids_date_reasons_outright():
    """Listing dates drift with reschedules; fixture_ok is about who is playing."""
    assert "Never write a date-based `reason`" in system_prompt_for("Polymarket")


def test_system_prompt_states_the_crypto_spread_sign_rule():
    """crypto writes the sign and lists both sides; "N to win" is the PLUS side."""
    prompt = system_prompt_for("crypto.com")
    assert "SPREAD SIGNS" in prompt
    assert "MISSING minus" in prompt


def test_system_prompt_states_grp_is_not_a_line():
    """Every exchange's rules must say so: _ours_line renders grouping_key for
    all three, and the inverted-sign trap is not exchange-specific."""
    for book in SPORTSBOOKS:
        prompt = system_prompt_for(book)
        assert "`grp` IS NOT THE BET'S LINE" in prompt, book
        assert "MIRROR of the real line" in prompt, book


def test_row_line_renders_a_grp_whose_sign_contradicts_the_line():
    """The regression this rule exists for: a correct crypto.com run_line row
    carries line=+4.5 AND grp='default:-4.5', and the first prod run flagged
    three of these with reason "OURS is -4.5" — the grouping key was the only
    -4.5 present. The renderer keeps grp (it carries player names for
    entity_ok), so the prompt must tell the judge to ignore its number."""
    line = row_line(
        0,
        _crypto_row(
            market_type="point_spread",
            selection="Minnesota Twins",
            side="MIN",
            line=4.5,
            points=4.5,
            grouping_key="default:-4.5",
        ),
    )
    assert " line=4.5" in line
    assert "grp='default:-4.5'" in line


def test_system_prompt_states_the_winner_anchored_scoreline_rule():
    """OURS correct_score is <winner>:<loser> (shared.correct_score_line), while
    exchanges write home-away — comparing them positionally flags valid rows."""
    prompt = system_prompt_for("Polymarket")
    assert "WINNER-ANCHORED" in prompt
    assert "REORDER" in prompt
    assert "_TIE" in prompt


def test_row_line_renders_prop_entity_and_line():
    line = row_line(0, _kalshi_row(entity="Aaron Judge", line=1.5, market_type="player_home_runs"))
    assert "entity='Aaron Judge'" in line
    assert "line=1.5" in line


def test_build_prompt_numbers_rows_from_zero():
    prompt = build_prompt([_kalshi_row(), _kalshi_row()])
    assert prompt.splitlines()[0].startswith("0. ")
    assert prompt.splitlines()[1].startswith("1. ")


# === Batching ===


def test_partition_chunks_never_mixes_sportsbooks():
    """One rule block per call only works if a batch is single-sportsbook."""
    rows = [_kalshi_row(), _poly_row(), _crypto_row(), _novig_row(), _kalshi_row(), _poly_row()]
    for chunk in partition_chunks(rows, 25):
        assert len({r["sportsbook"] for r in chunk}) == 1


def test_partition_chunks_interleaves_so_no_exchange_is_judged_last():
    """The smallest book must not wait for the biggest to finish.

    Grouped by exchange, crypto.com was always last, so during a re-judge it held
    no rows at the current prompt_version and disappeared from every
    version-filtered dashboard panel for the whole run.
    """
    rows = (
        [_kalshi_row() for _ in range(4)]
        + [_poly_row() for _ in range(60)]
        + [_crypto_row() for _ in range(2)]
        + [_novig_row() for _ in range(2)]
    )
    chunks = partition_chunks(rows, 2)
    first_four = {c[0]["sportsbook"] for c in chunks[:4]}
    assert first_four == set(SPORTSBOOKS), f"a book starved until late: {first_four}"


def test_partition_chunks_respects_batch_size_and_keeps_every_row():
    rows = [_kalshi_row() for _ in range(5)] + [_poly_row() for _ in range(3)]
    chunks = partition_chunks(rows, 2)
    assert all(len(c) <= 2 for c in chunks)
    assert sum(len(c) for c in chunks) == len(rows)


def test_partition_chunks_drops_unknown_sportsbooks():
    """Only the exchanges we match ourselves are judged."""
    rows = [_kalshi_row(), _kalshi_row(sportsbook="Prophet X")]
    assert sum(len(c) for c in partition_chunks(rows, 25)) == 1


def test_sportsbooks_are_the_ones_we_match_ourselves():
    assert SPORTSBOOKS == ("Kalshi", "Polymarket", "crypto.com", "Novig")


# === Exchange text extraction ===


def test_has_exchange_text_requires_that_exchange_own_text():
    assert has_exchange_text(_kalshi_row())
    assert not has_exchange_text(_kalshi_row(kalshi_title=None, kalshi_sub=None))
    assert has_exchange_text(_poly_row())
    assert not has_exchange_text(_poly_row(poly_question=None, poly_outcome=None))
    assert has_exchange_text(_crypto_row())
    assert not has_exchange_text(_crypto_row(cc_selection=None, cc_event=None))
    assert has_exchange_text(_novig_row())
    assert not has_exchange_text(_novig_row(novig_market_desc=None, novig_outcome_desc=None))


def test_has_exchange_text_rejects_out_of_scope_sportsbook():
    assert not has_exchange_text(_kalshi_row(sportsbook="Prophet X"))


def test_exchange_ref_side_and_text_per_exchange():
    kalshi = _kalshi_row()
    assert exchange_ref(kalshi) == "KXATPMATCH-26JUL30NAKMEN-NAK"
    assert exchange_side(kalshi) == "yes"
    assert "Will Brandon Nakashima win" in str(exchange_text(kalshi))

    poly = _poly_row()
    assert exchange_ref(poly) == poly["src_selection_id"]
    assert exchange_side(poly) == "Tom Gentzsch"
    assert exchange_text(poly) == "Bonn: Tom Gentzsch vs Max Dahlin"

    crypto = _crypto_row()
    assert exchange_ref(crypto) == crypto["src_symbol"]
    assert exchange_side(crypto) is None
    assert exchange_text(crypto) == "Brandon Nakashima to win / Nakashima vs Mensik"

    novig = _novig_row()
    assert exchange_ref(novig) == "novig-outcome-under"
    assert exchange_side(novig) is None
    assert exchange_text(novig) == "Under 2.5 / Total Rebounds"


# === Verdict join ===


def _verdict(i: int = 0, **over) -> Verdict:
    fields = {
        "i": i,
        "fixture_ok": True,
        "market_ok": True,
        "side_ok": True,
        "line_ok": True,
        "mapping_ok": True,
    }
    fields.update(over)
    return Verdict(**fields)


def test_verdict_rows_carries_identity_and_exchange_evidence():
    rows = verdict_rows([_kalshi_row()], [_verdict()], "gemini-2.5-flash", "2026-07-30T16:00:00+00:00")
    assert len(rows) == 1
    row = rows[0]
    assert row["row_fingerprint"] == "fp-kalshi"
    assert row["prompt_version"] == PROMPT_VERSION
    assert row["exchange_ref"] == "KXATPMATCH-26JUL30NAKMEN-NAK"
    assert row["start_date"] == START.isoformat()
    assert row["mapping_ok"] is True


def test_verdict_rows_nulls_entity_ok_when_not_a_player_prop():
    """The model sometimes answers anyway; a row with no entity is not a prop."""
    rows = verdict_rows([_kalshi_row()], [_verdict(entity_ok=False)], "m", "t")
    assert rows[0]["entity_ok"] is None


def test_verdict_rows_keeps_entity_ok_on_player_props():
    rows = verdict_rows([_kalshi_row(entity="Aaron Judge")], [_verdict(entity_ok=False)], "m", "t")
    assert rows[0]["entity_ok"] is False


def test_verdict_rows_drops_rows_the_model_skipped():
    """A missing index must not shift verdicts onto the wrong row."""
    chunk = [_kalshi_row(), _poly_row()]
    rows = verdict_rows(chunk, [_verdict(1, side_ok=False, mapping_ok=False)], "m", "t")
    assert len(rows) == 1
    assert rows[0]["row_fingerprint"] == "fp-poly"
    assert rows[0]["side_ok"] is False


def test_verdict_rows_ignores_out_of_range_indices():
    assert verdict_rows([_kalshi_row()], [_verdict(7)], "m", "t") == []


def test_verdict_rows_normalises_empty_reason_to_null():
    rows = verdict_rows([_kalshi_row()], [_verdict(reason="")], "m", "t")
    assert rows[0]["reason"] is None


# === Alert rollup ===


def _verdict_row(**over) -> dict:
    row = {
        "sportsbook": "Kalshi",
        "league": "atp",
        "exchange_ref": "KXATPMATCH-26JUL30NAKMEN-NAK",
        "fixture_ok": True,
        "market_ok": True,
        "side_ok": True,
        "line_ok": True,
        "entity_ok": None,
        "mapping_ok": True,
    }
    row.update(over)
    return row


def test_derive_mapping_ok_passes_when_no_component_failed():
    """An all-in false with every component passing names no contradiction."""
    assert derive_mapping_ok(_verdict(mapping_ok=False), is_prop=False) is True


def test_derive_mapping_ok_fails_when_any_component_failed():
    assert derive_mapping_ok(_verdict(side_ok=False, mapping_ok=True), is_prop=False) is False
    assert derive_mapping_ok(_verdict(line_ok=False, mapping_ok=True), is_prop=False) is False


def test_derive_mapping_ok_only_weighs_entity_on_props():
    v = _verdict(entity_ok=False, mapping_ok=True)
    assert derive_mapping_ok(v, is_prop=False) is True
    assert derive_mapping_ok(v, is_prop=True) is False


def test_verdict_rows_writes_the_derived_all_in_verdict():
    rows = verdict_rows([_kalshi_row()], [_verdict(mapping_ok=False, reason="date mismatch")], "m", "t")
    assert rows[0]["mapping_ok"] is True
    assert rows[0]["reason"] == "date mismatch"


def test_strip_slug_date_removes_only_a_trailing_iso_date():
    """Poly dates slugs by local tournament day, so the date must never be shown."""
    assert strip_slug_date("atp-gentzsc-dahlin-2026-07-30") == "atp-gentzsc-dahlin"
    assert strip_slug_date("mlb-nyy-bos-2026-08-01") == "mlb-nyy-bos"
    assert strip_slug_date("nwsl-hou-gotham") == "nwsl-hou-gotham"
    assert strip_slug_date(None) is None
    assert strip_slug_date("") is None


def test_row_line_poly_shows_no_date_anywhere():
    line = row_line(0, _poly_row())
    assert "slug=atp-gentzsc-dahlin" in line
    assert "2026-07-30" not in line.split("|| POLY")[1]


def test_system_prompt_tells_kalshi_titles_describe_the_yes_side():
    """s=no is the complement of the title, so the other team's name is expected."""
    prompt = system_prompt_for("Kalshi")
    assert "ALWAYS DESCRIBES THE CONTRACT'S" in prompt
    assert "THE TICKER IS AN OPAQUE ID" in prompt


def test_system_prompt_says_market_shape_is_not_a_scope():
    """Rows are per-leg, so a 3-way leg maps onto a binary question by design."""
    assert "MARKET SHAPE IS NOT A SCOPE" in system_prompt_for("Polymarket")


def test_system_prompt_forbids_date_reasons_on_polymarket():
    assert "NO DATE IS SHOWN FOR POLYMARKET" in system_prompt_for("Polymarket")


def test_summarize_flags_ignores_passing_rows():
    assert summarize_flags([_verdict_row(), _verdict_row()]) == []


def test_summarize_flags_groups_by_book_league_and_failed_check():
    rows = [
        _verdict_row(side_ok=False, mapping_ok=False),
        _verdict_row(side_ok=False, mapping_ok=False),
        _verdict_row(sportsbook="crypto.com", league="mlb", line_ok=False, mapping_ok=False),
    ]
    summary = summarize_flags(rows)
    assert [(s.sportsbook, s.failed_check, s.count) for s in summary] == [
        ("Kalshi", "side_ok", 2),
        ("crypto.com", "line_ok", 1),
    ]
    assert summary[0].sample_ref == "KXATPMATCH-26JUL30NAKMEN-NAK"


def test_summarize_flags_labels_a_bare_mapping_failure():
    """mapping_ok=false with every sub-check true still has to be reportable."""
    summary = summarize_flags([_verdict_row(mapping_ok=False)])
    assert summary[0].failed_check == "mapping_ok"


def test_format_summary_reports_totals_and_the_review_query():
    rows = summarize_flags([_verdict_row(fixture_ok=False, mapping_ok=False)])
    text = format_summary(rows, judged=120)
    assert "1 flagged of 120 judged" in text
    assert f"prompt v{PROMPT_VERSION}" in text
    assert "fixture_ok=false" in text
    assert "market_mapping_ai_validation" in text


# === Novig typed fields ===


def test_novig_line_shows_the_typed_market_type_strike_and_outcome():
    row = _novig_row(novig_market_type="SET_SPREAD", novig_strike="1.5", novig_outcome_type="Home")
    line = row_line(0, row)
    assert "type=SET_SPREAD" in line
    assert "strike=1.5" in line
    assert "outcome=Home" in line
    assert "SET_SPREAD 1.5" in (exchange_text(row) or "")


def test_novig_line_without_typed_fields_is_unchanged():
    line = row_line(0, _novig_row())
    assert "type=" not in line
    assert "strike=" not in line


def test_novig_prompt_makes_the_typed_fields_authoritative():
    prompt = system_prompt_for("Novig")
    assert "TYPED fields" in prompt
    assert "SET_SPREAD" in prompt


def test_novig_input_sql_selects_the_typed_fields():
    sql = build_sql("proj", revalidate=False, include_corroborated=False)
    for col in ("novig_market_type", "novig_strike", "novig_outcome_type"):
        assert col in sql
