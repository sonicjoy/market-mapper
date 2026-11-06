"""optic:fixture refs carry matchup and date for review cards."""

from mappers.control_plane.evidence_format import (
    cluster_alias_refs,
    optic_competitor_ref,
    optic_fixture_ref,
    optic_identity_refs,
    optic_match_fixture_ref,
    optic_refs_from_pins,
    usa_alias_refs,
)


def test_game_dict_uses_competitor_names_and_date() -> None:
    ref = optic_fixture_ref(
        {
            "id": "fx-1",
            "start_date": "2026-08-29T03:00:00Z",
            "home_competitors": [{"id": "h", "name": "Song Yadong"}],
            "away_competitors": [{"id": "a", "name": "Andre Lima"}],
        }
    )
    assert ref == "optic:fixture:fx-1:Song Yadong vs Andre Lima (2026-08-29)"


def test_probe_optic_dict_uses_home_away() -> None:
    ref = optic_fixture_ref(
        {
            "fixture_id": "fx-2",
            "home": "Valencia",
            "away": "Real Betis",
            "start_date": "2026-08-25T18:00:00Z",
        }
    )
    assert ref == "optic:fixture:fx-2:Valencia vs Real Betis (2026-08-25)"


def test_id_only_when_sides_missing() -> None:
    assert optic_fixture_ref({"id": "fx-3"}) == "optic:fixture:fx-3"


def test_empty_without_id() -> None:
    assert optic_fixture_ref({"home": "A", "away": "B"}) == ""
    assert optic_fixture_ref(None) == ""


def test_identity_refs_include_named_competitors() -> None:
    refs = optic_identity_refs(
        {
            "fixture_id": "fx-sch-mcv",
            "start_date": "2026-08-22T00:00:00Z",
            "home": "Wesley Schultz",
            "away": "Jackson McVey",
            "home_id": "oid-sch",
            "away_id": "oid-mcv",
        }
    )
    assert "optic:fixture:fx-sch-mcv:Wesley Schultz vs Jackson McVey (2026-08-22)" in refs
    assert "optic:competitor:oid-sch:Wesley Schultz" in refs
    assert "optic:competitor:oid-mcv:Jackson McVey" in refs


def test_named_competitor_ref() -> None:
    assert optic_competitor_ref("245B95767109", "Ugo Blanchet") == (
        "optic:competitor:245B95767109:Ugo Blanchet"
    )
    assert optic_competitor_ref("245B95767109") == "optic:competitor:245B95767109"


def test_refs_from_pins_only_optic() -> None:
    refs = optic_refs_from_pins(
        [
            ("crypto.com", "814825", "Ugo Blanchet"),
            ("optic", "245B95767109", "Ugo Blanchet"),
        ]
    )
    assert refs == ["optic:competitor:245B95767109:Ugo Blanchet"]


def test_usa_alias_refs_include_ticker_and_optic_fixture() -> None:
    refs = usa_alias_refs(
        "bulgaria_parva_liga",
        "dun",
        {
            "inner": "pvl",
            "home": "dun",
            "away": "lso",
            "date": "2026-08-31",
            "ticker": "pvl-dun-lso-2026-08-31",
            "title": "FC Dunav Ruse vs. FC Lokomotiv 1929 Sofia",
            "team_names": {
                "dun": "FC Dunav Ruse",
                "lso": "FC Lokomotiv 1929 Sofia",
            },
        },
        "7BFFE59C91FCD0DE",
        "FK Dunav Ruse",
        {
            "d": "2026-08-31",
            "home_id": "7BFFE59C91FCD0DE",
            "away_id": "lok-id",
            "home_name": "FK Dunav Ruse",
            "away_name": "Lokomotiv Sofia",
        },
    )
    assert refs[0] == "polymarket_usa:code:dun"
    assert "polymarket_usa:name:FC Dunav Ruse" in refs
    assert "polymarket_usa:title:FC Dunav Ruse vs. FC Lokomotiv 1929 Sofia" in refs
    assert "polymarket_usa:ticker:pvl-dun-lso-2026-08-31" in refs
    assert "polymarket_usa:match:dun vs lso (2026-08-31)" in refs
    assert "polymarket_usa:inner:pvl" in refs
    assert "gap:usa-inner:bulgaria_parva_liga:dun" in refs
    assert "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse" in refs
    assert any(r.startswith("optic:fixture:") and "FK Dunav Ruse vs Lokomotiv Sofia" in r for r in refs)
    assert "polymarket_usa:name:FC Lokomotiv 1929 Sofia" not in refs


def test_match_fixture_ref_uses_home_name() -> None:
    ref = optic_match_fixture_ref(
        {
            "d": "2026-08-31",
            "home_id": "h",
            "away_id": "a",
            "home_name": "FK Dunav Ruse",
            "away_name": "Lokomotiv Sofia",
        }
    )
    assert ref.endswith(":FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)")


def test_cluster_unrotates_interleaved_fixtures() -> None:
    owners = [
        ({"7bffe59c91fcd0de", "dun"}, "DR FK Dunav Ruse"),
        ({"82eccb05bbaf9851", "atr"}, "ATR7 Atreides"),
        ({"c30ba00000000000", "azu"}, "AZU8 Azuolas"),
    ]
    refs = [
        "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
        "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
        "optic:competitor:82ECCB05BBAF9851:Atreides",
        "optic:fixture:cs2-2:Azuolas vs Entropy (2026-08-31)",
        "optic:competitor:C30BA00000000000:Azuolas",
        "optic:fixture:pvl-1:FK Dunav Ruse vs Slavia Sofia (2026-09-07)",
        "note:pipeline-gap-fix",
    ]
    clustered = cluster_alias_refs(owners, refs)
    dunav = clustered.index("optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse")
    atreides = clustered.index("optic:competitor:82ECCB05BBAF9851:Atreides")
    azuolas = clustered.index("optic:competitor:C30BA00000000000:Azuolas")
    assert clustered[dunav + 1] == "optic:fixture:pvl-1:FK Dunav Ruse vs Slavia Sofia (2026-09-07)"
    assert clustered[atreides + 1] == "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)"
    assert clustered[azuolas + 1] == "optic:fixture:cs2-2:Azuolas vs Entropy (2026-08-31)"
    assert clustered[-1] == "note:pipeline-gap-fix"


def test_cluster_copies_two_sided_fixture_to_both_sides() -> None:
    owners = [
        ({"3971145542b7", "biga"}, "BAI5 BIG Academy"),
        ({"91f77395fc84", "ent"}, "ENT2 Entropy"),
        ({"c30ba6997b9daa39", "azu"}, "AZU8 Azuolas"),
    ]
    shared = "optic:fixture:20260831F4B11488:Azuolas vs Entropy (2026-08-31)"
    clustered = cluster_alias_refs(
        owners,
        [
            "optic:name:BIG Academy",
            "optic:fixture:20260903C7984A91:BIG Academy vs Fortress (2026-09-03)",
            shared,
            "optic:name:Entropy",
            "optic:name:Azuolas",
        ],
    )
    assert clustered.count(shared) == 2
    fortress = "optic:fixture:20260903C7984A91:BIG Academy vs Fortress (2026-09-03)"
    big_at = clustered.index("optic:name:BIG Academy")
    ent_at = clustered.index("optic:name:Entropy")
    assert fortress in clustered[big_at:ent_at]
    assert shared not in clustered[big_at:ent_at]


def test_cluster_sticks_each_kalshi_competitor_id_to_its_own_code() -> None:
    owners = [({"sak"}, "Stefanos Sakellaridis"), ({"shi"}, "Yuta Shimizu")]
    sak = "kalshi:code:SAK:competitor:uid-sak"
    shi = "kalshi:code:SHI:competitor:uid-shi"
    clustered = cluster_alias_refs(owners, [sak, shi])
    assert clustered.count(sak) == 1
    assert clustered.count(shi) == 1
    assert clustered.index(sak) < clustered.index(shi)


def test_cluster_drops_harvest_fixture_when_optic_id_matches() -> None:
    harvest = (
        "optic:fixture:29234-24495-2026-08-31:FC Barcelona vs Rayo Vallecano (2026-08-31)"
    )
    optic = "optic:fixture:2026083179BA180C:FC Barcelona vs Rayo Vallecano (2026-08-31)"
    clustered = cluster_alias_refs(
        [({"4e6e8d0b0ec1"}, "FC Barcelona"), ({"f2ccf38e0a5a"}, "AFC Bournemouth")],
        [
            "optic:name:FC Barcelona",
            harvest,
            optic,
            "optic:competitor:4E6E8D0B0EC1:FC Barcelona",
        ],
    )
    assert optic in clustered
    assert harvest not in clustered
    assert clustered.count(optic) == 1


def test_cluster_does_not_attach_united_to_newcastle_bournemouth() -> None:
    newcastle = (
        "optic:fixture:2026090574A30340:Newcastle United FC vs AFC Bournemouth (2026-09-05)"
    )
    united = "optic:fixture:20260905DA70617A:Everton FC vs Manchester United FC (2026-09-06)"
    clustered = cluster_alias_refs(
        [
            ({"af8ddbc0795a", "mnu"}, "Manchester United FC"),
            ({"f2ccf38e0a5a", "bor"}, "AFC Bournemouth"),
        ],
        [
            "optic:name:Manchester United FC",
            united,
            "optic:name:AFC Bournemouth",
            newcastle,
        ],
    )
    united_at = clustered.index("optic:name:Manchester United FC")
    bou_at = clustered.index("optic:name:AFC Bournemouth")
    assert united in clustered[united_at:bou_at]
    assert newcastle not in clustered[united_at:bou_at]
    assert newcastle in clustered[bou_at:]


def test_cluster_keeps_kalshi_event_off_unrelated_pins() -> None:
    owners = [
        ({"ulc-oid", "ulc"}, "ULC4 Union La Calera"),
        ({"dls-oid", "dls"}, "DLS Deportes La Serena"),
        ({"2d589316fed5", "md", "mary"}, "MD Maryland"),
    ]
    gap = "gap:KXCHLLDPGAME-26AUG31ULCDLS"
    title = "kalshi:title:Union La Calera vs Deportes La Serena"
    market_ulc = "kalshi:market:KXCHLLDP-26-ULC"
    market_dls = "kalshi:market:KXCHLLDP-26-DLS"
    maryland = "optic:name:Maryland"
    clustered = cluster_alias_refs(
        owners,
        [gap, title, market_ulc, market_dls, maryland],
    )
    md_at = clustered.index(maryland)
    chile = clustered[:md_at]
    assert chile.count(gap) == 2
    assert chile.count(title) == 2
    assert market_ulc in chile
    assert market_dls in chile
    assert gap not in clustered[md_at:]
    assert title not in clustered[md_at:]
    assert market_ulc not in clustered[md_at:]
    assert market_dls not in clustered[md_at:]


def test_cluster_does_not_attach_other_state_school_titles() -> None:
    wvsu = "kalshi:title:Robert Morris vs West Virginia State"
    iowa = "kalshi:title:Iowa State vs Iowa"
    clustered = cluster_alias_refs(
        [
            ({"wvs4", "wvsu"}, "West Virginia State"),
            ({"isu"}, "Iowa State"),
        ],
        [wvsu, iowa],
    )
    assert clustered == [wvsu, iowa]
