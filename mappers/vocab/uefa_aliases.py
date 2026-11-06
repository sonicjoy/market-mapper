"""Shared UEFA club-name aliases (poly spelling -> optic spelling).

One table across Champions League, Europa League and Europa Conference League
because the club POOL is shared by construction: UEFA's qualifying rounds drop
losers down a tier, so the same club appears in two or three of these
competitions within weeks (Egnatia, Omonia, Hapoel Be'er Sheva and Sheriff all
do in the 2026 qualifiers alone). Keeping three copies would guarantee drift —
an alias added for the tier where the club was first seen and missing from the
tier it drops into. An alias for a club absent from a given league's fixtures
simply never fires, so sharing is safe (same argument as tennis_aliases.py).

Every pair below was derived on 2026-08-06 by resolving the live Polymarket
bridge slugs (`ucl-` / `uel-` / `col-`) against the live Optic fixtures for
`uefa_-_champions_league` / `uefa_-_europa_league` /
`uefa_-_europa_conference_league`, and keeping only pairs where:

  - Optic actually carries that fixture on that date (+-1 day), so the pair is
    a NAME divergence and not Optic simply missing the game; and
  - the poly matchup pairs to exactly one Optic fixture, both sides agreeing.

Pairs are NOT added by string similarity alone. Three similarity candidates were
rejected here for failing the first rule -- "FC Spartak Trnava" and "FC Atert
Bissen" have no Optic fixture at all, and "ETO FC" / "Floriana FC" already
reconcile by containment against "Győri ETO FC" / "Floriana FC".

Deliberately NOT aliased: anything CSKA. Optic carries "PFK CSKA Sofia" AND
"FK CSKA 1948 Sofia" as two distinct clubs, and _name_match is containment-based
on this style ("fk cska sofia" is a substring of "pfk cska sofia"), so an alias
here could silently bind the wrong Sofia club. Both already match exactly.

OFI is in `_DISAMBIGUATE_PAIRS`, not `_PAIRS`: "ofi" already contain-matches
"OFI FC", but it also contain-matches "pfk cska sofia". Rewriting the poly
token to the optic spelling makes the Sofia hit fail. build_rows drops when
a name still hits both sides (see `_unique_fixture_side`).
"""

from mappers.exchanges.polymarket import _norm_name

_STYLE = "mlb_suffix"

# (poly spelling, optic spelling, why they diverge)
_PAIRS: tuple[tuple[str, str, str], ...] = (
    # --- Poly abbreviates the club's legal/long form. ---
    ("Aarhus GF", "Aarhus Gymnastikforening", "poly abbreviates"),
    ("Kuopion PS", "Kuopion Palloseura", "poly abbreviates"),
    ("Helsingin JK", "Helsingin Jalkapalloklubi", "poly abbreviates"),
    ("Fenerbahçe SK", "Fenerbahçe Spor Kulübü", "poly abbreviates"),
    ("Beşiktaş JK", "Beşiktaş Jimnastik Kulübü", "poly abbreviates"),
    ("NEC", "Nijmegen Eendracht Combinatie", "poly uses the initialism"),
    ("RU Saint-Gilloise", "Royale Union Saint-Gilloise", "poly abbreviates"),
    (
        "Universitatea Craiova CS",
        "Universitatea Craiova 1948 Club Sportiv",
        "poly abbreviates",
    ),
    ("GKS GieKSa Katowice", "GKS Katowice", "poly spells out the GKS initialism"),
    # --- Optic abbreviates instead. ---
    ("Sport Lisboa e Benfica", "SL Benfica", "optic abbreviates"),
    ("SK Puntigamer Sturm Graz", "SK Sturm Graz", "poly carries the sponsor"),
    ("FC Red Bull Salzburg", "FC Salzburg", "poly carries the sponsor"),
    ("Rams Başakşehir FK", "Medipol İstanbul Başakşehir Futbol Kulübü",
     "different sponsor prefixes"),
    ("FK ML Viciebsk", "FK Maxline Vitebsk", "sponsor abbreviated + transliteration"),
    # --- Club-type prefix differs (FC/FK/KF/SK/CS/SP/IK are not interchangeable
    # across sources, and containment cannot bridge a differing first token). ---
    ("FC Sheriff Tiraspol", "FK Sheriff Tiraspol", "club-type prefix"),
    ("FC Petrocub Hînceşti", "CS Petrocub Hînceşti", "club-type prefix"),
    ("FK Dynamo Kyiv", "FC Dynamo Kyiv", "club-type prefix"),
    ("FC Malisheva", "KF Malisheva", "club-type prefix"),
    ("FC Ballkani", "KF Ballkani", "club-type prefix"),
    ("FC Drita", "KF Drita", "club-type prefix"),
    ("SK Dinamo Tbilisi", "FC Dinamo Tbilisi", "club-type prefix"),
    ("SK Iberia 1999", "FC Iberia 1999", "club-type prefix"),
    ("Alashkert FA", "Alashkert FC", "club-type suffix"),
    ("Pyunik FA", "Pyunik FC", "club-type suffix"),
    ("Noah FA", "FC Noah", "club-type suffix vs prefix"),
    ("Ararat-Armenia FA", "Ararat-Armenia FC", "club-type suffix"),
    ("FC CFR 1907 Cluj", "SCS CFR 1907 Cluj", "club-type prefix"),
    ("Tre Fiori FC", "SP Tre Fiori", "club-type suffix vs prefix"),
    ("Zirə FK", "Zira IK", "club-type suffix + schwa dropped by normalization"),
    ("FK LNZ Cherkasy", "LNZ Cherkasy FC", "club-type prefix vs suffix"),
    ("Panathinaikós AO", "Panathinaikos FC", "club-type suffix"),
    ("SC Braga", "Sporting Braga", "poly abbreviates Sporting"),
    # --- Israeli clubs: poly prefixes the "Moadon Hasport" (MH) form. ---
    ("MH Hapoel Be'er Sheva", "Hapoel Be'er Sheva FC", "MH prefix"),
    ("MH Hapoel Tel Aviv", "Hapoel Tel Aviv FC", "MH prefix"),
    ("MH Maccabi Tel Aviv", "Maccabi Tel Aviv FC", "MH prefix"),
    ("MH Beitar Jerusalem", "Beitar Jerusalem FC", "MH prefix"),
    # --- Transliteration / local-language rendering. ---
    ("Qairat FK", "Kairat Almaty", "transliteration + city suffix"),
    ("Tobyl FK", "FK Tobol Kostanay", "transliteration + city suffix"),
    ("AS Omónoia Leukosías", "AC Omonia Nicosia", "greek vs english rendering"),
    ("Apóllon Lemesoú", "Apollon Limassol", "greek vs english rendering"),
    ("AEK Lárnakas", "AEK Larnaca", "greek vs english rendering"),
    ("Olympiakós SFP", "Olympiakos CFP", "greek vs english rendering"),
    ("FK Dynama-Minsk", "FC Dinamo Minsk", "belarusian vs russian rendering"),
    ("FK BATE Barysaŭ", "FC BATE Borisov", "belarusian vs russian rendering"),
    ("FK Polissia", "Polissya Zhytomyr", "transliteration + city suffix"),
    ("Neftçi PFK", "Neftçi PFC Bakı", "club-type suffix + city suffix"),
    ("KF Egnatia Rrogozhinë", "KS Egnatia Rrogozhinë", "club-type prefix"),
    ("KF Dukagjini Klinë", "KF Dukagjini Klina", "albanian vs serbian city form"),
    # --- Poly drops the city, Optic keeps it (or vice versa). ---
    ("KF Víkingur", "Víkingur Reykjavík", "city dropped by poly"),
    ("KF Valur", "Valur Reykjavík", "city dropped by poly"),
    ("Ilves Tampere", "Tampereen Ilves", "city leads in optic"),
    ("Hammarby Fotboll", "Hammarby IF", "club-type suffix"),
)

# Already contain-match the optic name; the rewrite stops a false opponent hit.
# Live 2026-08-21: uel-csk1-ofi-2026-08-27 bound OFI markets onto CSK.
_DISAMBIGUATE_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("OFI", "OFI FC", "ofi is a substring of sofia"),
)

UEFA_TEAM_NAME_ALIASES: dict[str, str] = {
    _norm_name(poly, _STYLE): _norm_name(optic, _STYLE)
    for poly, optic, _ in _PAIRS + _DISAMBIGUATE_PAIRS
}

# Disambiguation rewrites stay in Python until a tip entity alias is seeded;
# they are not lossless relocations to the entity catalog yet.
UEFA_DISAMBIGUATION_ALIAS_KEYS: frozenset[str] = frozenset(
    _norm_name(poly, _STYLE) for poly, _, _ in _DISAMBIGUATE_PAIRS
)
