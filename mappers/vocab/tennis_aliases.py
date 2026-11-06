"""Shared tennis player-name aliases (poly spelling -> optic spelling).

`_name_match` uses EXACT equality on the tennis_prefix path -- deliberately,
never containment, so a bare "rune" can't match "holger_rune". That makes any
spelling divergence between Polymarket's label and Optic's competitor name a
hard drop, and the alias overlay (`team_alias_scope`, consulted on both sides)
is the sanctioned way to reconcile one.

Every pair below was derived from the 2026-07-27 MAPPING_FAILED audit by taking
the distinct poly outcome labels on unmapped atp/wta tennis legs and matching
them against Optic's live tennis moneyline selections. Only pairs meeting all of
these are listed -- each is an individually verifiable same-person match:

  - exactly ONE optic candidate (ambiguous surnames like "Samuel" ->
    toby_samuel / samuel_constantinou, or "Matsuda" -> koki / ryuki, are
    EXCLUDED: guessing a side is the flip-safety failure this repo treats as
    money-critical, so those stay unmapped);
  - the poly label carries at least TWO name tokens (surname-only labels resolve
    through _match_name's granularity="surname" path instead, which already
    compares against the optic name's last token -- aliasing them would be
    redundant at best and a collision risk at worst);
  - the optic candidate is a singles entry (no " // " doubles pair).

Combined declined stake over the audited 48h: ~$4.35M. Sharing one dict across
all tennis leagues is safe and intentional: an alias for a player absent
from a given league's fixtures simply never fires.

Player pools rotate, so this list is expected to grow. Regenerate candidates the
same way (unmapped poly labels x live optic tennis selections, then apply the
three filters above) rather than adding fuzzy matches by hand.
"""

from mappers.exchanges.polymarket import _norm_name

_STYLE = "tennis_prefix"

# (poly spelling, optic spelling, why they diverge)
_PAIRS: tuple[tuple[str, str, str], ...] = (
    # Poly truncates the second half of a Spanish double surname.
    ("Roger Pascual", "Roger Pascual Ferra", "double surname truncated"),
    # Optic misspells the given name ("Deigo").
    ("Diego Dedura-Palomero", "Deigo Dedura-Palomero", "optic typo"),
    # Optic includes the middle name.
    ("Gabi Boitan", "Gabi Adrian Boitan", "middle name"),
    ("Guido Justo", "Guido Ivan Justo", "middle name"),
    # Poly repeats the surname.
    ("Aryan Shah Shah", "Aryan Shah", "poly duplicates surname"),
    # Hyphen vs. space in a compound surname.
    (
        "Sascha Gueymard-Wayenburg",
        "Sascha Gueymard Wayenburg",
        "compound surname hyphenation",
    ),
    # Transliteration variants.
    ("Abedallah Shelbayh", "Abdullah Shelbayh", "transliteration"),
    ("Soon-Woo Kwon", "Soonwoo Kwon", "transliteration"),
)

TENNIS_TEAM_NAME_ALIASES: dict[str, str] = {
    _norm_name(poly, _STYLE): _norm_name(optic, _STYLE) for poly, optic, _ in _PAIRS
}
