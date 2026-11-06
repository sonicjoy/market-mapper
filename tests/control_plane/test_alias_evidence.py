"""Proposal evidence stays on the same entity and league."""

from __future__ import annotations

import pytest

from mappers.control_plane.alias_evidence import (
    hay_mentions,
    league_slug_prefix,
    pin_alias_refs,
    refs_for_alias,
    slug_prefix_from,
)

# A short last name or code must never match the ref's own key word.
_SCHEME_COLLISIONS = [
    ("Oumar Sy", "crypto:symbol:999:NX.F.OPT.TENNIS-0024-260904-M.O.1.1"),
    ("Bob Na", "crypto:name:Someone Else"),
    ("Ed Ti", "crypto:tip:Someone Else"),
    ("Ana Ti", "polymarket_usa:ticker:ABC"),
    ("Amy Co", "polymarket_usa:code:xyz"),
    ("Ivo Na", "polymarket_usa:name:Someone Else"),
    ("Jon Ma", "polymarket_usa:match:A vs B"),
    ("Lea In", "polymarket_usa:inner:zzz"),
    ("Kim Ti", "polymarket_usa:title:Unrelated"),
    ("Rex Ma", "kalshi:market:KXEPL-26-ARS"),
    ("Sam Ti", "kalshi:title:Unrelated question"),
]


def test_league_slug_prefix_strips_sex_suffix() -> None:
    assert league_slug_prefix("itf_men") == "itf"
    assert league_slug_prefix("atp") == "atp"


def test_slug_prefix_from_own_refs() -> None:
    assert slug_prefix_from(["polymarket:slug:atp-shapova-assche-2026-09-02"]) == "atp"


def test_hay_mentions_full_name_only() -> None:
    assert hay_mentions("Denis Shapovalov vs Luca Van Assche", "denis shapovalov")
    assert not hay_mentions(
        "Set Handicap: Shapovalov (-1.5) vs Assche (+1.5)", "denis shapovalov",
    )
    assert not hay_mentions("W15 Haren: Nina Kruijer vs Klara Veldman", "denis shapovalov")
    assert not hay_mentions("polymarket_usa:name:erhard", "fc hradec kralove")


def test_hay_mentions_school_suffix_is_not_a_surname() -> None:
    assert hay_mentions("Robert Morris vs West Virginia State", "west virginia state")
    assert not hay_mentions("Iowa State vs. Iowa", "west virginia state")
    assert not hay_mentions("Arizona State vs. Memphis", "west virginia state")
    assert hay_mentions("Georgia Tech vs. Colorado", "georgia tech")
    assert not hay_mentions("Texas Tech vs. Oregon State", "georgia tech")


@pytest.mark.parametrize(("name", "ref"), _SCHEME_COLLISIONS)
def test_short_name_never_matches_ref_key_word(name: str, ref: str) -> None:
    assert refs_for_alias([ref], "140005193", name, "crypto.com") == []


def test_crypto_symbol_sticks_to_the_pin_that_probed_it() -> None:
    mine = "crypto:symbol:140005193:NX.F.OPT.UFC-00009-260905-M.O.1.2"
    theirs = "crypto:symbol:140005194:NX.F.OPT.EPL-00001-260904-M.O.1.13"
    kept = refs_for_alias([mine, theirs], "140005193", "Oumar Sy", "crypto.com")
    assert kept == [mine]


def test_shared_refs_need_entity_and_same_league() -> None:
    extra = [
        "polymarket:slug:itf-kruijer-veldma-2026-09-02",
        "polymarket:question:W15 Haren: Nina Kruijer vs Klara Veldman",
        "polymarket:slug:atp-shapova-assche-2026-09-02-set-handicap-home-1pt5",
        "polymarket:question:Denis Shapovalov vs Luca Van Assche",
        "optic:fixture:fx2:Yanaki Milev vs Ignacio Parisca (2026-09-03)",
    ]
    kept = refs_for_alias(
        extra,
        "Shapovalov (-1.5)",
        "Denis Shapovalov",
        "polymarket",
        slug_prefix="atp",
    )
    joined = "\n".join(kept).lower()
    assert "denis shapovalov" in joined
    assert "kruijer" not in joined
    assert "milev" not in joined


def test_pin_keeps_truncated_own_slug() -> None:
    own = ["polymarket:slug:atp-shapova-assche-2026-09-02-set-handicap-home-1pt5"]
    refs = pin_alias_refs(
        own,
        ["polymarket:slug:mlb-oak-tex-2026-09-02-total-11pt5"],
        "Shapovalov (-1.5)",
        "Denis Shapovalov",
        "polymarket",
        "atp",
    )
    assert own[0] in refs
    assert all("mlb-oak" not in ref for ref in refs)


def test_school_suffix_does_not_claim_other_state_titles() -> None:
    extra = [
        "polymarket_usa:title:Robert Morris vs West Virginia State",
        "polymarket_usa:title:Iowa State vs. Iowa",
        "polymarket_usa:title:Arizona State vs. Memphis",
        "optic:fixture:fx1:Colorado State vs Southern Utah (2026-09-12)",
        "optic:fixture:fx2:Robert Morris vs West Virginia State (2026-09-05)",
    ]
    kept = refs_for_alias(extra, "wvsu", "West Virginia State", "polymarket_usa")
    joined = "\n".join(kept).lower()
    assert "west virginia state" in joined
    assert "iowa state" not in joined
    assert "arizona state" not in joined
    assert "colorado state" not in joined
    assert all(ref.startswith("polymarket_usa:") for ref in kept)


def test_own_optic_fixture_does_not_land_on_poly_usa_card() -> None:
    own = [
        "polymarket_usa:code:wvsu",
        "polymarket_usa:title:Robert Morris vs West Virginia State",
        "optic:competitor:1285ED1571BD6FF6:West Virginia State",
        "optic:fixture:fx2:Robert Morris vs West Virginia State (2026-09-05)",
    ]
    extra = [
        "polymarket_usa:title:Iowa State vs. Iowa",
        "optic:fixture:fx1:Colorado State vs Southern Utah (2026-09-12)",
    ]
    refs = pin_alias_refs(
        own, extra, "wvsu", "West Virginia State", "polymarket_usa", "ncaaf",
    )
    joined = "\n".join(refs).lower()
    assert "polymarket_usa:title:robert morris vs west virginia state" in joined
    assert "iowa state" not in joined
    assert all(ref.startswith(("polymarket_usa:", "gap:usa-inner:")) for ref in refs)
