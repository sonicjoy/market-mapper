"""market_mapping lookup (all sportsbooks) and Kalshi event-ticker helpers."""

from __future__ import annotations

import json

from mappers.control_plane.chat_console import ConsolePage
from mappers.control_plane.chat_intent import IntentScore
from mappers.control_plane.chat_resolve import other_probe_id, resolve_query
from mappers.control_plane.chat_skills.probe_gap import match, slots
from mappers.control_plane.chat_tools_mapping import (
    classify_source_id,
    kalshi_event_ticker,
    lookup_mapping,
    mapping_fn_from_args,
    mapping_sql,
    probe_source_mapping,
    source_aliases,
)
from mappers.control_plane.chat_tools_probe import (
    _FETCH_RAW_LOOKBACK,
    _novig_sql,
    _px_sql,
    probe_novig_id,
    probe_px_id,
)
from tests.conftest import us_gateway_market


def test_strips_market_suffix() -> None:
    assert kalshi_event_ticker("KXUEFASCGAME-26AUG12PSGAVL-TIE") == (
        "KXUEFASCGAME-26AUG12PSGAVL"
    )
    assert kalshi_event_ticker("KXUEFASCGAME-26AUG12PSGAVL") == (
        "KXUEFASCGAME-26AUG12PSGAVL"
    )
    assert kalshi_event_ticker("KXWNBASPREAD-26FEB25MORGSCST-SCST1") == (
        "KXWNBASPREAD-26FEB25MORGSCST"
    )


def test_crypto_base_strips_maturity() -> None:
    sym = "NX.F.OPT.UFC-00011-260822-M.O.1.1.20260822"
    _id, event, base = source_aliases(sym)
    assert _id == sym
    assert event == sym
    assert base == "NX.F.OPT.UFC-00011-260822-M.O.1.1"


def test_sql_covers_all_source_id_fields() -> None:
    sql = mapping_sql("marketmaking-test")
    assert "markets_us.market_mapping" in sql
    assert "sportsbook = 'Kalshi'" not in sql
    assert "$.market_id" in sql
    assert "$.symbol" in sql
    assert "$.selection_id" in sql
    assert "$.event_id" in sql
    assert "start_date > timestamp_sub" in sql
    assert "@id" in sql
    assert "@event" in sql
    assert "@base" in sql


def test_lookup_uses_query_fn() -> None:
    captured: list[dict[str, str]] = []

    def query_fn(_sql: str, params: dict[str, str]) -> list[dict[str, str]]:
        captured.append(params)
        return [
            {
                "market_ticker": params["id"],
                "sportsbook": "Kalshi",
                "league": "uefa_super_cup",
                "side": "_TIE",
                "selection": "Draw",
            }
        ]

    rows = lookup_mapping("KXUEFASCGAME-26AUG12PSGAVL-TIE", query_fn=query_fn)
    assert captured == [{
        "id": "KXUEFASCGAME-26AUG12PSGAVL-TIE",
        "event": "KXUEFASCGAME-26AUG12PSGAVL",
        "base": "KXUEFASCGAME-26AUG12PSGAVL-TIE",
    }]
    assert rows[0]["sportsbook"] == "Kalshi"
    assert rows[0]["side"] == "_TIE"


def test_probe_source_mapping_poly_token() -> None:
    token = "ab" * 32

    def query_fn(_sql: str, params: dict[str, str]) -> list[dict[str, str]]:
        assert params["id"] == token
        return [{
            "sportsbook": "Polymarket",
            "source_selection_id": token,
            "league": "epl",
            "home": "Arsenal",
            "away": "Chelsea",
            "market_type": "moneyline",
            "side": "ARS",
            "selection": "Arsenal",
            "fixture_id": "fx-ars",
        }]

    out = probe_source_mapping(token, query_fn=query_fn)
    row = out["results"][0]
    assert row["kind"] == "already_mapped"
    assert row["sportsbook"] == "Polymarket"
    assert row["league"] == "epl"


def test_probe_source_mapping_miss() -> None:
    out = probe_source_mapping("deadbeef" * 8, query_fn=lambda _s, _p: [])
    row = out["results"][0]
    assert row["kind"] == "unmapped"
    assert row["mapped_rows"] == []
    assert row["sportsbook"] == "polymarket"
    assert row["id_kind"] == "condition_id"
    assert row["norm_id"].startswith("0x")


def test_classify_poly_and_px_ids(us_gateway: dict[str, dict]) -> None:
    cid = classify_source_id("0x" + "ab" * 32)
    assert cid["sportsbook"] == "polymarket"
    assert cid["id_kind"] == "condition_id"
    clob = classify_source_id("9" * 24)
    assert clob["sportsbook"] == "polymarket"
    assert clob["id_kind"] == "clob_token_id"
    px = classify_source_id("730003207")
    assert px["sportsbook"] == "px"
    assert px["id_kind"] == "px_id"
    nv = classify_source_id("01a03c33-d23f-7040-90cb-d64c165ae185")
    assert nv["sportsbook"] == "novig"
    assert nv["id_kind"] == "novig_id"
    assert classify_source_id('aec-atp-benbon-botzan-2026-08-27')["sportsbook"] != "polymarket_usa"
    us_gateway['aec-atp-benbon-botzan-2026-08-27'] = us_gateway_market(
        'aec-atp-benbon-botzan-2026-08-27', league="atp", smt="tennis_match_winner",
        teams=(("benbon", "Benjamin Bonzi"), ("botzan", "Botic van de Zandschulp")),
        start="2026-08-27T10:00:00Z",
    )
    usa = classify_source_id('aec-atp-benbon-botzan-2026-08-27')
    assert usa["sportsbook"] == "polymarket_usa"
    assert usa["id_kind"] == "us_symbol"


def test_probe_source_mapping_px_catalogue() -> None:
    out = probe_source_mapping(
        "730003207",
        query_fn=lambda _s, _p: [],
        catalogue_fn=lambda _c: {
            "seen": True,
            "title": "Lakers vs Celtics",
            "home": "Lakers",
            "away": "Celtics",
            "scheduled": "2026-08-28T19:00:00Z",
            "tournament": "NBA",
        },
    )
    row = out["results"][0]
    assert row["sportsbook"] == "px"
    assert row["title"] == "Lakers vs Celtics"
    assert row["meta_event_date"] == "2026-08-28T19:00:00Z"
    assert row["tournament"] == "NBA"


def test_probe_source_mapping_poly_catalogue() -> None:
    token = "ab" * 32
    out = probe_source_mapping(
        token,
        query_fn=lambda _s, _p: [],
        catalogue_fn=lambda _c: {
            "seen": True,
            "question": "Will Arsenal win?",
            "slug": "epl-ars-che",
            "outcomes": ["Yes", "No"],
            "game_start_time": "2026-08-25T14:00:00Z",
        },
    )
    row = out["results"][0]
    assert row["sportsbook"] == "polymarket"
    assert row["title"] == "Will Arsenal win?"
    assert row["slug"] == "epl-ars-che"
    assert row["outcomes"] == ["Yes", "No"]


def test_injected_catalogue_fn_skips_live_mapping() -> None:
    fn = mapping_fn_from_args({"catalogue_fn": lambda _s: {}})
    assert fn("NX.F.OPT.UFC-00011-260822-M.O.1.1") == []


def test_probe_gap_matches_poly_hex(us_gateway: dict[str, dict]) -> None:
    token = "ab" * 32
    page = ConsolePage()
    scored = IntentScore("other", 0.1, resolved=resolve_query(token))
    assert match(scored, token, page)
    assert slots(token, page, scored)["other"] == token
    assert other_probe_id("hello") == ""
    assert other_probe_id("123456") == "123456"
    assert other_probe_id("0x" + "ab" * 32) == "0x" + "ab" * 32
    assert other_probe_id("01a03c33-d23f-7040-90cb-d64c165ae185") == (
        "01a03c33-d23f-7040-90cb-d64c165ae185"
    )
    ticker = "aec-atp-benbon-botzan-2026-08-27"
    us_gateway['aec-atp-benbon-botzan-2026-08-27'] = us_gateway_market(
        'aec-atp-benbon-botzan-2026-08-27', league="atp", smt="tennis_match_winner",
        teams=(("benbon", "Benjamin Bonzi"), ("botzan", "Botic van de Zandschulp")),
        start="2026-08-27T10:00:00Z",
    )
    assert other_probe_id("map " + ticker) == ticker
    ticker_scored = IntentScore("other", 0.1, resolved=resolve_query("map " + ticker))
    assert match(ticker_scored, "map " + ticker, page)
    slug = "bun-stu-koe-2026-09-04-exact-score-0-0"
    asked = "do we map this ticker: `" + slug + "`"
    assert other_probe_id(asked) == slug
    slug_scored = IntentScore("other", 0.1, resolved=resolve_query(asked))
    assert match(slug_scored, asked, page)


def test_probe_gap_slots_keep_every_ticker() -> None:
    page = ConsolePage()
    text = "probe KXEPLGAME-26AUG25ARSCHE and KXATPGAME-25AUG24SINALC"
    scored = IntentScore("other", 0.1, resolved=resolve_query(text))
    filled = slots(text, page, scored)
    assert filled["kalshi"] == "KXEPLGAME-26AUG25ARSCHE"
    assert filled["kalshi_all"] == [
        "KXEPLGAME-26AUG25ARSCHE",
        "KXATPGAME-25AUG24SINALC",
    ]


def test_probe_slots_ignore_unmapped_page_filters() -> None:
    """Unmapped Sport/League/Sportsbook must not scope a pasted ticker."""
    page = ConsolePage(
        path="/unmapped",
        unmapped={"league": "epl", "sport": "soccer", "platform": "crypto", "q": "honor"},
        entry={"league": "mlb"},
    )
    text = "NX.F.OPT.TENNIS-0026-260904-M.O.1.2.20261231"
    scored = IntentScore("other", 0.1, resolved=resolve_query(text))
    filled = slots(text, page, scored)
    assert filled["crypto"] == text
    assert filled["league"] == ""


def test_probe_px_id_uses_query_fn() -> None:
    out = probe_px_id(
        "730003207",
        query_fn=lambda _s, _p: [
            {
                "kind": "event",
                "tournament_id": "nba",
                "data": {
                    "competitors": [{"name": "Lakers"}, {"name": "Celtics"}],
                    "scheduled": "2026-08-28T19:00:00Z",
                    "tournament_name": "NBA",
                    "sport_name": "Basketball",
                    "name": "Lakers vs Celtics",
                },
            }
        ],
    )
    assert out["seen"] is True
    assert out["home"] == "Lakers"
    assert out["tournament"] == "NBA"


def test_probe_source_mapping_novig_catalogue() -> None:
    ident = "01a03c33-d23f-7040-90cb-d64c165ae185"
    out = probe_source_mapping(
        ident,
        query_fn=lambda _s, _p: [],
        catalogue_fn=lambda _c: {
            "seen": True,
            "title": "Lakers vs Celtics",
            "league": "NBA",
            "scheduled": "2026-08-28T19:00:00Z",
            "fixture_id": "20260828ABC",
            "novig_type": "GAME",
            "sportsbook": "novig",
            "id_kind": "novig_event",
        },
    )
    row = out["results"][0]
    assert row["sportsbook"] == "novig"
    assert row["title"] == "Lakers vs Celtics"
    assert row["optic"]["fixture_id"] == "20260828ABC"


def test_probe_novig_id_uses_query_fn() -> None:
    ident = "01a03c33-d23f-7040-90cb-d64c165ae185"
    out = probe_novig_id(
        ident,
        query_fn=lambda _s, _p: [
            {
                "hit": "event",
                "league": "NBA",
                "data": {
                    "id": ident,
                    "description": "Lakers vs Celtics",
                    "league": "NBA",
                    "scheduledStart": "2026-08-28T19:00:00Z",
                    "opticOddsId": "20260828ABC",
                    "type": "GAME",
                },
            }
        ],
    )
    assert out["seen"] is True
    assert out["title"] == "Lakers vs Celtics"
    assert out["fixture_id"] == "20260828ABC"
    assert out["id_kind"] == "novig_event"


def _assert_lookback_on_each_branch(sql: str, branches: int) -> None:
    """Every UNION branch must carry the partition predicate, not QUALIFY."""
    assert sql.count(_FETCH_RAW_LOOKBACK) == branches, sql
    for branch in sql.split("union all"):
        where_at = branch.lower().find("where")
        qualify_at = branch.lower().find("qualify")
        assert where_at != -1, branch
        assert _FETCH_RAW_LOOKBACK in branch[where_at:qualify_at], branch


def test_px_probe_sql_prunes_fetch_time() -> None:
    _assert_lookback_on_each_branch(_px_sql(), 2)


def test_novig_probe_sql_prunes_fetch_time() -> None:
    _assert_lookback_on_each_branch(_novig_sql(), 3)


def test_probe_source_mapping_udx_ticker_anatomy() -> None:
    ticker = "UDXNFLGAMEWIN_ARINYG26OCT041300_ARI"
    out = probe_source_mapping(ticker, query_fn=lambda _s, _p: [])
    row = out["results"][0]
    assert row["sportsbook"] == "underdog"
    assert row["title"] == "ARI @ NYG"
    assert row["league"] == "NFL"
    assert row["optic"]["home"] == "NYG"
    assert row["optic"]["away"] == "ARI"


def test_classify_dkex_symbol_before_px(tmp_path, monkeypatch) -> None:
    from mappers.control_plane.chat_tools_mapping import classify_source_id

    sym = "NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024"
    (tmp_path / "dkex_markets.jsonl").write_text(json.dumps({"symbol": sym}) + "\n")
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    out = classify_source_id(sym)
    assert out["sportsbook"] == "dkex"
    assert out["id_kind"] == "dkex_symbol"


def test_probe_source_mapping_ncaaf_udx_ticker() -> None:
    ticker = "UDXNCAAMFBGAMEWIN_AAMUFAMU26SEP261900_AAMU"
    out = probe_source_mapping(ticker, query_fn=lambda _s, _p: [])
    row = out["results"][0]
    assert row["sportsbook"] == "underdog"
    assert row["league"] == "NCAAMFB"
    assert row["title"] == "AAMU @ FAMU"


def test_probe_source_mapping_us_symbol_anatomy(us_gateway: dict[str, dict]) -> None:
    """Anatomy is the gateway's typed fields; the symbol text is never split."""
    ticker = "aec-atp-benbon-botzan-2026-08-27"
    us_gateway['aec-atp-benbon-botzan-2026-08-27'] = us_gateway_market(
        'aec-atp-benbon-botzan-2026-08-27', league="atp", smt="tennis_match_winner",
        teams=(("benbon", "Benjamin Bonzi"), ("botzan", "Botic van de Zandschulp")),
        start="2026-08-27T10:00:00Z",
    )
    out = probe_source_mapping(ticker, query_fn=lambda _s, _p: [])
    row = out["results"][0]
    assert row["sportsbook"] == "polymarket_usa"
    assert row["title"] == "Benjamin Bonzi vs Botic van de Zandschulp"
    assert row["league"] == "atp"
    assert row["sports_market_type"] == "tennis_match_winner"
    assert row["optic"]["home"] == "benbon"


def test_probe_source_mapping_poly_slug_exact_score() -> None:
    slug = "bun-stu-koe-2026-09-04-exact-score-0-0"
    out = probe_source_mapping(slug, query_fn=lambda _s, _p: [])
    row = out["results"][0]
    assert row["sportsbook"] == "polymarket"
    assert row["kind"] == "exact_score"
    assert row["title"] == "stu vs koe"
    assert row["league"] == "bun"
    assert row["suffix"] == "exact-score-0-0"
    assert row["optic"]["home"] == "stu"
