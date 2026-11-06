"""Alias mapping-row source labels use full names, not codes."""

from __future__ import annotations

from mappers.control_plane.console_mapping_rows import _alias_row, mapping_rows_from_proposal
from mappers.control_plane.gap_fix_ai_suggest import AI_NOTE, AI_REF
from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ExchangePin,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
    ProposalRecord,
)
from mappers.control_plane.rows import LeagueRow, MarketRuleRow


def _row(
    book: str,
    code: str,
    name: str,
    evidence: list[str],
    *,
    alias_kind: str = "code",
    pin_evidence: list[str] | None = None,
) -> dict:
    ea = EntityAliasPayload(
        league="atp",
        canonical_key="SHE",
        canonical_name=name,
        aliases=[AliasPin(sportsbook=book, alias_kind=alias_kind, alias_value=code)],
        evidence_refs=pin_evidence or [],
    )
    return _alias_row(
        ea,
        ea.aliases[0],
        evidence=evidence,
        action="add",
        sport="tennis",
        league_is_new=False,
    )


def test_optic_source_uses_competitor_name() -> None:
    row = _row(
        "optic",
        "167522086300",
        "Ben Shelton",
        ["optic:competitor:167522086300:Ben Shelton"],
    )
    assert row["source"]["name"] == "Ben Shelton"
    assert row["source"]["code"] == "167522086300"


def test_poly_usa_source_uses_gateway_name_not_code() -> None:
    row = _row(
        "polymarket_usa",
        "benshe",
        "Ben Shelton",
        [
            "polymarket_usa:name:Ben Shelton",
            "polymarket_usa:code:benshe",
            "polymarket_usa:name:Hubert Hurkacz",
        ],
    )
    assert row["source"]["name"] == "Ben Shelton"
    assert row["source"]["code"] == "benshe"


def test_crypto_source_uses_participant_not_matchup_title() -> None:
    row = _row(
        "crypto.com",
        "1098193",
        "Dusan Obradovic",
        [
            "gap:NX.F.OPT.TENNIS-0001-260904-M.O.1.2.20261231",
            "crypto:name:Thomas Faurel @ Dusan Obradovic",
            "crypto:name:Thomas Faurel",
            "crypto:name:Dusan Obradovic",
            "optic:fixture:fx:Dusan Obradovic vs Thomas Faurel (2026-09-04)",
        ],
        alias_kind="external_id",
        pin_evidence=[
            "crypto:name:Thomas Faurel @ Dusan Obradovic",
            "crypto:name:Thomas Faurel",
            "crypto:name:Dusan Obradovic",
        ],
    )
    assert row["source"]["name"] == "Dusan Obradovic"
    assert "@" not in row["source"]["name"]
    assert row["source"]["description"] == "Thomas Faurel @ Dusan Obradovic"


def test_crypto_source_uses_title_ref_for_fixture() -> None:
    row = _row(
        "crypto.com",
        "1098193",
        "Dusan Obradovic",
        [],
        alias_kind="external_id",
        pin_evidence=[
            "crypto:title:Thomas Faurel @ Dusan Obradovic",
            "crypto:name:Thomas Faurel",
            "crypto:name:Dusan Obradovic",
        ],
    )
    assert row["source"]["name"] == "Dusan Obradovic"
    assert row["source"]["description"] == "Thomas Faurel @ Dusan Obradovic"


def test_polymarket_source_includes_slug_from_evidence() -> None:
    row = _row(
        "polymarket",
        "Barbados Tridents",
        "Barbados Royals",
        [
            "polymarket:name:Barbados Tridents",
            "polymarket:slug:cpl-brb-vs-ttk-2026-09-04",
        ],
        alias_kind="name",
        pin_evidence=["polymarket:slug:cpl-brb-vs-ttk-2026-09-04"],
    )
    assert row["source"]["name"] == "Barbados Tridents"
    assert row["source"]["alias_kind"] == "name"
    assert row["source"]["slug"] == "cpl-brb-vs-ttk-2026-09-04"


def test_name_kind_source_keeps_pin_not_canonical() -> None:
    row = _row(
        "polymarket",
        "Klara Veldman",
        "Veldman Klara",
        [],
        alias_kind="name",
    )
    assert row["source"]["name"] == "Klara Veldman"
    assert row["target"]["name"] == "Veldman Klara"


def test_optic_row_keeps_identity_not_poly_questions() -> None:
    row = _row(
        "optic",
        "4E10DF885122",
        "Dane Sweeny",
        [
            "polymarket:question:W15 Haren: Nina Kruijer vs Klara Veldman",
            "polymarket:slug:w15-haren-nina-kruijer-klara-veldman",
            "polymarket:market:Winner",
            "polymarket:outcome:Nina Kruijer",
        ],
        alias_kind="external_id",
        pin_evidence=[
            "optic:competitor:4E10DF885122:Dane Sweeny",
            "optic:name:Dane Sweeny",
            "optic:fixture:fx1:Dane Sweeny vs Lorenzo Musetti (2026-09-03)",
            "optic:abbr:SWE",
        ],
    )
    assert row["source"]["name"] == "Dane Sweeny"
    assert row["target"]["code"] == "SHE"
    assert row["source"]["abbr"] == "SWE"
    assert row["target"]["abbr"] == "SWE"
    assert row["evidence"] == [
        "optic:competitor:4E10DF885122:Dane Sweeny",
        "optic:name:Dane Sweeny",
        "optic:fixture:fx1:Dane Sweeny vs Lorenzo Musetti (2026-09-03)",
        "optic:abbr:SWE",
    ]
    assert all(not ref.startswith("polymarket:") for ref in row["evidence"])


def test_poly_row_keeps_own_event_drops_other_league_evidence() -> None:
    own = [
        "polymarket:slug:atp-shapova-assche-2026-09-02-set-handicap-home-1pt5",
        "polymarket:question:Set Handicap: Shapovalov (-1.5) vs Assche (+1.5)",
        "polymarket:name:Shapovalov (-1.5)",
        "optic:fixture:fx1:Denis Shapovalov vs Luca Van Assche (2026-09-02)",
    ]
    row = _row(
        "polymarket",
        "Shapovalov (-1.5)",
        "Denis Shapovalov",
        [
            *own,
            "polymarket:slug:itf-kruijer-veldma-2026-09-02",
            "polymarket:question:W15 Haren: Nina Kruijer vs Klara Veldman",
            "polymarket:slug:mlb-oak-tex-2026-09-02-total-11pt5",
            "polymarket:question:Athletics vs. Texas Rangers: O/U 11.5",
            "polymarket:slug:atp-milev-parisca-2026-09-03",
            "polymarket:question:Plovdiv 3: Yanaki Milev vs Ignacio Parisca",
            "optic:fixture:fx2:Yanaki Milev vs Ignacio Parisca (2026-09-03)",
        ],
        alias_kind="name",
        pin_evidence=own,
    )
    ev = row["evidence"]
    assert own[0] in ev
    assert own[1] in ev
    assert own[3] not in ev
    assert row["source"]["slug"] == own[0].split(":", 2)[-1]
    joined = "\n".join(ev).lower()
    assert "kruijer" not in joined
    assert "mlb-oak" not in joined
    assert "milev" not in joined
    assert "rangers" not in joined
    assert all(ref.startswith("polymarket:") for ref in ev)


def test_mapping_rows_omit_selection_aliases() -> None:
    rec = ProposalRecord(
        proposal_id="P1",
        request_id="r1",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="x",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            entity_aliases=[
                EntityAliasPayload(
                    league="atp",
                    canonical_key="SHA",
                    canonical_name="Denis Shapovalov",
                    aliases=[
                        AliasPin(
                            sportsbook="polymarket",
                            alias_kind="name",
                            alias_value="Shapovalov (-1.5)",
                        ),
                        AliasPin(
                            sportsbook="polymarket",
                            alias_kind="name",
                            alias_value="Over 11.5",
                        ),
                        AliasPin(
                            sportsbook="polymarket",
                            alias_kind="name",
                            alias_value="Austin FC to score first",
                        ),
                        AliasPin(
                            sportsbook="polymarket",
                            alias_kind="name",
                            alias_value="Denis Shapovalov",
                        ),
                    ],
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues={}, new_leagues=set())
    codes = [str(row["source"]["code"]) for row in rows]
    assert codes == ["Denis Shapovalov"]


def test_ai_suggest_alias_defaults_to_keep() -> None:
    row = _row(
        "polymarket",
        "Santos FC",
        "Santos FC Sao Paulo",
        ["optic:competitor:oid:Santos FC Sao Paulo"],
        alias_kind="name",
        pin_evidence=[AI_REF, "ai:skip:name_ambiguous", AI_NOTE],
    )
    assert row["tier"] == "ai"
    assert row["keep_default"] is True


def test_market_rule_notes_stay_on_the_row_not_the_evidence() -> None:
    sentence = "Yes side is unset"
    rec = ProposalRecord(
        proposal_id="P-notes",
        request_id="r-notes",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="notes stay on the row",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            market_rules=[
                MappingMarketRulesPayload(
                    league="ufc",
                    rules=[
                        MarketRulePin(
                            sportsbook="kalshi",
                            rule_kind="taxonomy",
                            source_key_type="ticker_type",
                            source_key="ROUNDS",
                            action="map",
                            canonical_market_type="total_rounds",
                            notes=sentence,
                        )
                    ],
                    evidence_refs=["kalshi:series:KXUFCROUNDS"],
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues={}, new_leagues=set())
    assert len(rows) == 1
    assert rows[0]["notes"] == sentence
    assert sentence not in rows[0]["evidence"]
    assert rows[0]["evidence"] == ["kalshi:series:KXUFCROUNDS"]


def test_context_rules_render_read_only_and_keep_the_card() -> None:
    sentence = "Yes side is unset"
    rec = ProposalRecord(
        proposal_id="P-ctx",
        request_id="r-ctx",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="context",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            market_rules=[
                MappingMarketRulesPayload(
                    league="ufc",
                    rules=[
                        MarketRulePin(
                            sportsbook="polymarket_usa",
                            rule_kind="taxonomy",
                            source_key_type="ticker_suffix",
                            source_key="mov",
                            action="ignore",
                        )
                    ],
                    context_rules=[
                        MarketRulePin(
                            sportsbook="polymarket_usa",
                            rule_kind="taxonomy",
                            source_key_type="ticker_suffix",
                            source_key="rof-before-r",
                            action="map",
                            canonical_market_type="total_rounds",
                            line_offset=-0.5,
                            yes_side="under",
                            notes=sentence,
                        )
                    ],
                    evidence_refs=["polymarket_usa:ticker:aec-ufc-ryagan-ozzdia-2026-09-19-rof-before-r"],
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues={}, new_leagues=set())
    assert [row["source"]["code"] for row in rows] == ["mov", "rof-before-r"]
    context = rows[1]
    assert context["read_only"] is True
    assert context["notes"] == sentence
    assert sentence not in context["evidence"]
    assert rows[0]["evidence"] == []
    assert context["evidence"] == ["polymarket_usa:ticker:aec-ufc-ryagan-ozzdia-2026-09-19-rof-before-r"]
    assert context["line_offset"] == -0.5
    assert context["yes_side"] == "under"
    assert context["venue"].startswith("Polymarket US rof-before-r")
    assert "offset -0.5" in context["transform"]


def test_ai_suggest_market_rule_defaults_to_ai_tier() -> None:
    rec = ProposalRecord(
        proposal_id="P-ai-mr",
        request_id="r-ai-mr",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="ai market",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            market_rules=[
                MappingMarketRulesPayload(
                    league="nba",
                    rules=[
                        MarketRulePin(
                            sportsbook="kalshi",
                            rule_kind="taxonomy",
                            source_key_type="ticker_type",
                            source_key="1HSPREAD",
                            action="map",
                            canonical_market_type="1h_point_spread",
                            notes=AI_NOTE,
                        )
                    ],
                    evidence_refs=[AI_REF, "ai:skip:no_optic_canonical", AI_NOTE],
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues={}, new_leagues=set())
    assert len(rows) == 1
    assert rows[0]["kind"] == "market_rule"
    assert rows[0]["tier"] == "ai"
    assert rows[0]["keep_default"] is True
    assert rows[0]["evidence"] == [AI_REF, "ai:skip:no_optic_canonical", AI_NOTE]
    assert rows[0]["notes"] == AI_NOTE


def test_market_rule_cards_keep_only_their_source_key_evidence() -> None:
    spread_note = "Kalshi integer suffix. line_offset -0.5 is the series config"
    total_note = "total stays in notes"
    refs = [
        "kalshi:series:KXNHLSPREAD",
        "spine:kalshi_ticker_types:SPREAD",
        "optic:market_id:puck_line",
        "kalshi:series:KXNHLTOTAL",
        "spine:kalshi_ticker_types:TOTAL",
        "optic:market_id:total_goals",
    ]
    rec = ProposalRecord(
        proposal_id="P-nhl",
        request_id="r-nhl",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="nhl evidence split",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            market_rules=[
                MappingMarketRulesPayload(
                    league="nhl",
                    rules=[
                        MarketRulePin(
                            sportsbook="kalshi",
                            rule_kind="taxonomy",
                            source_key_type="ticker_type",
                            source_key="SPREAD",
                            action="map",
                            canonical_market_type="puck_line",
                            notes=spread_note,
                        ),
                        MarketRulePin(
                            sportsbook="kalshi",
                            rule_kind="taxonomy",
                            source_key_type="ticker_type",
                            source_key="TOTAL",
                            action="map",
                            canonical_market_type="total_goals",
                            notes=total_note,
                        ),
                    ],
                    context_rules=[
                        MarketRulePin(
                            sportsbook="kalshi",
                            rule_kind="taxonomy",
                            source_key_type="ticker_type",
                            source_key="GAME",
                            action="map",
                            canonical_market_type="moneyline",
                        )
                    ],
                    evidence_refs=refs,
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues={}, new_leagues=set())
    by_key = {row["source"]["code"]: row for row in rows}
    assert by_key["SPREAD"]["evidence"] == refs[:3]
    assert by_key["TOTAL"]["evidence"] == refs[3:]
    assert by_key["GAME"]["evidence"] == []
    assert spread_note == by_key["SPREAD"]["notes"]
    assert total_note == by_key["TOTAL"]["notes"]
    assert spread_note not in by_key["SPREAD"]["evidence"]
    assert total_note not in by_key["TOTAL"]["evidence"]
    assert all("TOTAL" not in ref for ref in by_key["SPREAD"]["evidence"])
    assert all("SPREAD" not in ref for ref in by_key["TOTAL"]["evidence"])


def test_ai_suggest_market_rule_notes_fallback_without_ai_ref() -> None:
    rec = ProposalRecord(
        proposal_id="P-ai-note",
        request_id="r-ai-note",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="ai market note",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            market_rules=[
                MappingMarketRulesPayload(
                    league="nba",
                    rules=[
                        MarketRulePin(
                            sportsbook="kalshi",
                            rule_kind="taxonomy",
                            source_key_type="ticker_type",
                            source_key="1HSPREAD",
                            action="map",
                            canonical_market_type="1h_point_spread",
                            notes=AI_NOTE,
                        )
                    ],
                    evidence_refs=[],
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues={}, new_leagues=set())
    assert rows[0]["tier"] == "ai"


def _onboard_rec() -> ProposalRecord:
    return ProposalRecord(
        proposal_id="P2",
        request_id="r2",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="onboard",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            leagues=[
                MappingLeaguePayload(
                    league="austria_ofb_cup",
                    sport="soccer",
                    optic_league_id="at-cup",
                    exchanges=[
                        ExchangePin(sportsbook="polymarket", parser_profile="x", enabled=True)
                    ],
                    clone_market_rules_from="epl",
                    market_rules=[
                        MarketRulePin(
                            sportsbook="kalshi",
                            rule_kind="taxonomy",
                            source_key_type="ticker_type",
                            source_key="GAME",
                            action="map",
                            canonical_market_type="moneyline_3way",
                        )
                    ],
                )
            ]
        ),
        proposer_subject="t",
    )


def _tip_rule(source_key: str, canonical: str) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"epl-{source_key}",
        league="epl",
        sportsbook="px",
        rule_kind="taxonomy",
        source_key_type="market_name",
        source_key=source_key,
        action="map",
        canonical_market_type=canonical,
        priority=100,
        enabled=True,
        confidence="manual",
    )


def test_mapping_rows_clone_expands_one_card_per_rule() -> None:
    rows = mapping_rows_from_proposal(
        _onboard_rec(),
        groups=None,
        tip_leagues={},
        new_leagues={"austria_ofb_cup"},
        tip_market_rules=[_tip_rule("TOTAL", "total"), _tip_rule("SPREAD", "spread")],
    )
    kinds = [str(row["kind"]) for row in rows]
    assert kinds.count("league") == 1
    assert kinds.count("market_rule") == 3
    league = next(row for row in rows if row["kind"] == "league")
    assert league["clone_from"] == "epl"
    assert len(league["cloned_rules"]) == 2
    cloned = [row for row in rows if row.get("clone_from") == "epl" and row["kind"] == "market_rule"]
    assert {row["source"]["code"] for row in cloned} == {"TOTAL", "SPREAD"}
    assert all(str(row["key"]).startswith("rule:") for row in cloned)
    explicit = next(
        row for row in rows if str(row["key"]).startswith("rule:") and not row.get("clone_from")
    )
    assert explicit["source"]["code"] == "GAME"
    assert league["league_diff"]["enable"]
    assert league["reason"]


def test_league_row_lists_new_books_vs_already_live() -> None:
    prior = LeagueRow(
        league="poland_ekstraklasa",
        sport="soccer",
        optic_league_id="poland_-_ekstraklasa",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "optic",
                "enabled": True,
                "parser_profile": "optic_standard_v1",
                "source_league_id": "poland_-_ekstraklasa",
            }
        ],
    )
    rec = ProposalRecord(
        proposal_id="P3",
        request_id="r3",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="poly prefix",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            leagues=[
                MappingLeaguePayload(
                    league="poland_ekstraklasa",
                    sport="soccer",
                    optic_league_id="poland_-_ekstraklasa",
                    exchanges=[
                        ExchangePin(
                            sportsbook="optic",
                            parser_profile="optic_standard_v1",
                            enabled=True,
                            source_league_id="poland_-_ekstraklasa",
                        ),
                        ExchangePin(
                            sportsbook="polymarket",
                            parser_profile="poly_generic_v1",
                            enabled=True,
                            source_league_id="poland_-_ekstraklasa",
                            settings={"slug_prefix": "pol"},
                        ),
                        ExchangePin(
                            sportsbook="polymarket_usa",
                            parser_profile="poly_usa_generic_v1",
                            enabled=True,
                            source_league_id="ekst",
                            settings={"slug_prefix": "ekst"},
                        ),
                    ],
                    evidence_refs=[
                        "gap:poly-prefix:pol",
                        "optic:league:poland_-_ekstraklasa",
                        "league:poland_ekstraklasa",
                    ],
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(
        rec,
        groups=None,
        tip_leagues={"poland_ekstraklasa": prior},
        new_leagues=set(),
    )
    league = next(row for row in rows if row["kind"] == "league")
    assert league["action"] == "update"
    diff = league["league_diff"]
    assert any("prefix pol" in item for item in diff["enable"])
    assert any("ekst" in item for item in diff["enable"])
    assert any(item.startswith("Optic") for item in diff["already"])
    assert "Enable" in str(league["reason"])
    assert "Optic already on" in str(league["reason"])


def test_remove_alias_row_action_is_delete() -> None:
    rec = ProposalRecord(
        proposal_id="P-del",
        request_id="r-del",
        status="validated",
        expected_rule_set_id="S",
        artifact_type="batch_changes",
        summary="remove",
        evidence_refs=[],
        work_item_id=None,
        payload=BatchChangesPayload(
            entity_aliases=[
                EntityAliasPayload(
                    league="atp",
                    canonical_key="SVA2",
                    canonical_name="Trevor Svajda",
                    aliases=[
                        AliasPin(
                            sportsbook="kalshi",
                            alias_kind="code",
                            alias_value="SVA",
                            remove=True,
                        )
                    ],
                )
            ]
        ),
        proposer_subject="t",
    )
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues={}, new_leagues=set())
    assert len(rows) == 1
    assert rows[0]["action"] == "delete"
    assert rows[0]["source"]["code"] == "SVA"
