"""Fit a DKEX team display name onto one side of an Optic fixture.

DKEX's ``metadata.participants[].name`` for a pro team is the city as an
upper-case abbreviation plus the nickname -- ``DEN Broncos``, ``NY Jets``,
``LA Dodgers``, ``CHI White Sox`` -- where Optic spells the city out
(``Denver Broncos``, ``New York Jets``).  The shared ``names_fit`` does
not treat those as the same club, so on its own it resolves no NFL, MLB,
NBA or WNBA team at all (measured on the 2026-09-28 staging book: 0 of
32 NFL, 0 of 30 MLB, 0 of 8 WNBA).  College names are school names and
fit as-is.

:func:`city_abbrev_fits` is the one extra rule, and it is deliberately
narrow: the DKEX name's first word must be WRITTEN as an abbreviation
(upper case, at most three characters), every remaining word must equal
the tail of the Optic name, and the abbreviation must be the Optic abbrev,
the initials of the Optic city words, a prefix of the first city word, or
letters of the city in order from its first (``WPG`` Winnipeg, ``STL``
St. Louis).
:func:`team_side_for` applies it next to ``team_side`` and keeps
``team_side``'s rule: a name that fits both sides, or neither, is no side.

Soccer has the opposite problem.  DKEX writes the common short name
(``Palmeiras``, ``Dortmund``, ``Man City``) where Optic writes the
official one (``SE Palmeiras``, ``BV Borussia 09 Dortmund``,
``Manchester City FC``).  :func:`club_short_fits` accepts a DKEX name
whose every word, in order, is an Optic word or the start of one; it is
switched on per league (``DkexConfig.club_short_names``), and the same
exactly-one-side rule applies, so ``Sao Paulo`` against Optic's
``São Paulo FC`` and ``Santos FC Sao Paulo`` is no side at all.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from mappers.canonical_codes import names_close, tokens
from mappers.shared import normalize_player_name
from mappers.team_side import team_side

#: A trailing ``[ARG]`` DKEX adds to a club name.
_TEAM_TAG = re.compile(r"\s*\[[^\]]*\]\s*$")
#: The longest city abbreviation DKEX writes ("DEN", "CHI", "JAX").
_MAX_CITY_ABBREV = 3
#: Shortest DKEX word accepted as the start of an Optic word ("Man" for
#: "Manchester", "Atl" for "Athletico").
_MIN_PREFIX = 3
#: At least one DKEX word this long must land, so noise such as "FC" or
#: "RB" never carries a match on its own.
_MIN_ANCHOR = 4
#: Letters NFKD does not decompose, and the apostrophe DKEX drops
#: ("Newells" / "Newell's").  ``tokens`` folds every other accent.
_CLUB_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss",
                            "đ": "d", "Đ": "D", "'": "", "\u2019": ""})
#: Word abbreviations DKEX writes that stand for one Optic word only
#: ("Sheffield Utd" / "Sheffield United FC").  Nicknames ("Wolves",
#: "Spurs") are not abbreviations: those are tip aliases.
_CLUB_WORDS = {"UTD": "UNITED"}


#: DKEX team display names no name rule fits, pinned to the Optic
#: competitor id(s) they name.  Optic ids are the same in test and prod.
#: Measured on the staging book of 2026-09-29 against Optic the same day
#: (the event's other team fit by name); the Optic fixture is the evidence.
#: Optic keeps per-competition competitors, so one club can carry two ids.
OPTIC_IDS_BY_DKEX_NAME: dict[str, frozenset[str]] = {
    name.casefold(): frozenset(ids)
    for name, ids in (
        # ncaaf
        ("UConn", ("A273A3133F39",)),                     # 202610039BD21BC3
        ("UMass", ("C3DB5719FDE6",)),                     # 20261003CD6FAB1B
        ("Georgia Bulldogs", ("04C37B5D7034",)),          # 20261003664393DD
        ("Miami OH", ("1788A761CD62",)),                  # 2026100364F93E5F
        ("Miami FL", ("412D810EA674",)),                  # 20261003396D0662
        ("Southern Miss", ("826709E8B05C",)),             # 202610249E254BB3 Southern Mississippi
        # ncaaf, FCS (subTopic "NCAA FCS"), 2026-10-03 catalogue
        ("Albany NY", ("4505BACF6CF8",)),                 # 20261003C408A5BE UAlbany
        ("ETSU", ("386F83F6DAFE",)),                      # 20261003F7F0DBC8
        ("Nicholls State", ("111B0E50F653",)),            # 20261003715CEE44 Nicholls
        ("St. Thomas MN", ("ABB51CDF8C3F",)),             # 202610038ED1D604
        ("Central Connecticut State", ("A79562960B7D",)),  # 20261003420F097A
        ("Alcorn", ("6D5A5DA16039",)),                    # 20261003FEE2CCF6 Alcorn State
        ("Arkansas-Pine Bluff", ("70518837B5E5",)),       # 202610035622D5DB
        ("Southern University", ("E92D5ABFC445",)),       # 202610035622D5DB Southern
        # Renamed from Texas A&M Commerce in 2025; Optic keeps the old name.
        ("East Texas A&M", ("39CFDC90083D",)),            # 20261003E57EB85A
        # nfl: "JAX" spells no letters of Jacksonville in order (no X)
        ("JAX Jaguars", ("9CCE4CA64CF2",)),               # 2026101118C77B29
        # ufc: a given-name nickname no name rule fits (Optic "Loopy Godínez")
        ("Lupita Godinez", ("9E55CCC0A9EE",)),            # 20261011814C4060
        ("Seokhyeon Ko", ("99CC61D9718D",)),              # 20261107850B64AC, Optic "Seok Hyun Ko"
        ("Gabriel Lorenco", ("834CB3D4ED4288C0",)),       # 202611074729B03A, Optic "Gabriel Lourenco"
        ("Su Young You", ("338A4EF20A5E",)),              # 202610174116C26E, Optic "SuYoung You"
        ("Ramazonbek Temirov", ("45BF28A082B6",)),        # 202610243DE1155B, Optic "Ramazan Temirov"
        ("Cam Rowston", ("27A28382FDBD",)),               # 202610241831626A, Optic "Cameron Rowston"
        ("Timothy Cuamba", ("C30B4A71FFEB",)),            # 20261017847483C9, Optic "Timmy Cuamba"
        # wta: given-name variants no name rule fits (Optic "Catherine", "Yulia")
        ("Caty McNally", ("77A1D24EB085",)),              # 2026101211BD30D7 Wuhan
        ("Yuliia Starodubtseva", ("B0285346B076",)),      # 2026101211BD30D7 Wuhan
        ("Anastasiia Sobolieva", ("B7E70108C926",)),      # 202610128D779B10 Mallorca 125, Optic "Anastasiya"
        ("Raluca Georgiana Serban", ("1BE9F0D675DC",)),   # 202610122C6123C9 Lisbon 125, Optic "Raluka"
        # nhl: "CBJ" spells no letters of Columbus in order (no J)
        ("CBJ Blue Jackets", ("B59FF9985C9C",)),          # 202610092F1D4ADA
        # soccer
        ("Wolves", ("94CB52205FE40CB1",)),                # 202610107FAE14ED
        # Optic "FK Crvena zvezda Beograd"
        ("Red Star Belgrade", ("DA099181EE5BD01B",)),     # 202611051710AAFC Europa Conf.
        ("Cologne", ("743038E111E7",)),                   # 20261011F2AE7F40
        ("RB Leipzig", ("23643B23434A",)),                # 202610102B0C44A0
        ("Monza Brianza", ("E7387B29ADEA",)),             # 20261011841DC9E7
        ("Paris St-Germain", ("6CE2C0F47875",)),          # 2026101020672937
        ("Auxerre", ("A4308EBB94DA",)),                   # 2026101881477B69
        # Ligue 1 202610110AFA3EAC; Europa League 20261015AD5EE4BD
        ("Stade Rennes", ("C9C064312E88", "A7C018E79716")),
        ("Sparta Prague", ("79891BC6EE01",)),             # 20261015702CEFDC
        ("AZ Alkmaar", ("2ED2D66DA3BB",)),                # 202610154CDF2251
        ("OFI Crete", ("F1D467111C602536",)),             # 20261015AD5EE4BD
        ("Sao Paulo", ("ED1D58650278",)),                 # 202610027D2F55E6
        ("Remo Belem", ("ED5DD8FBB720954A",)),            # 202610079CD9DD84
        ("Vitoria Salvador", ("AC171558B6FF",)),          # 20261007195BE6F5
        ("Internacional RS", ("E132F56A7003",)),          # 20261007B22A8BBE
        ("Atl Paranaense", ("83831C785BD4",)),            # 20261008D22DB070
        ("Botafogo RJ", ("E7282CC46B95",)),               # 20261007F7D9D3CA
        ("Atletico Tucuman", ("A7E6EF4755F5",)),          # 20261004EED2D0A4
        ("Deportivo Riestra", ("A08FA7D7EF43",)),         # 20261004249D5F7C
        # liga_mx, 2026-10-05 catalogue
        ("Tigres UANL", ("5C23D58C3F8F",)),               # 202610100D7489C4
        ("Atlas Gdj", ("DF9AF28C07E7",)),                 # 20261011B6393E08 Atlas FC
        ("Guadalajara Chivas", ("CAE317C7E908",)),        # 20261011B6393E08 CD Guadalajara
        # 2026-11-05 catalogue, fixture 12440-72234-2026-11-07 (Optic "Pumas de la Universidad
        # Nacional Autonoma de Mexico" / "Club de Fútbol América")
        ("Pumas UNAM", ("A3DA6E9D1669",)),
        ("Club America", ("B4088A0A4C58",)),
        # atp_challenger Taipei 20261105A44A3CCE, Optic "Hou Chun Chien" (family name first);
        # the same player carries a second competitor "Chun-Chien Hou"
        ("Chun-Chien Hou", ("EAAABF97CEE5DCA3", "1138A5187752B0DA")),
        # itf_men Fergana 202611052F752000, Optic "Digvijaypratap Singh"
        ("Digvijay Pratap Singh", ("0419A719CAD7E3BC",)),
    )
}


#: DKEX player names no name rule fits (a nickname or a short form of a
#: given name), pinned to the Optic player id they name.  Optic player ids
#: are the same in test and prod; the fixture is the evidence.
OPTIC_PLAYER_IDS_BY_DKEX_NAME: dict[str, frozenset[str]] = {
    name.casefold(): frozenset(ids)
    for name, ids in (
        ("Joseph Gomez", ("F46E0B68D1EB",)),              # Liverpool v Man City, Optic "Joe Gomez"
        ("Konstantinos Tsimikas", ("058B4D2BD48F",)),     # Liverpool v Man City, Optic "Kostas Tsimikas"
        ("Nana Burris", ("AB35001BB072",)),               # South Alabama @ Arkansas State, Optic "Nazeviah Burris"
        # 2026-11-05 book: DKEX short / truncated forms of Optic's names
        ("Zachary Bolduc", ("CF74533DDE3E",)),            # 2026110540A33E47, Optic "Zack Bolduc"
        ("Gabe Perreault", ("80065152FF8073EF",)),        # 20261105CA007972, Optic "Gabriel Perreault"
        ("Marquise Brown", ("9AF71136A8B6",)),            # 20261108A1A2490E, Optic "Hollywood Brown"
        ("Kamal-Deen Sulemana", ("CC1AA46FEE8104DC",)),   # 202611051C0B4DA2, Optic "Kamaldeen Sulemana"
        ("Max Rosenfelde", ("5EC54D60865770D1",)),        # 20261105B7707E46, Optic "Maximilian Rosenfelder"
        ("Nicolas Moumi", ("B4A61EFE19E50CCF",)),         # 20261105D98D91F6, Optic "Moumi Ngamaleu"
        ("Bekhruz Karimov", ("DE847442AF017283",)),       # 20261105A37747F6, Optic "Behruzjon Karimov"
        ("Toni Garcia", ("4D3704B58B65",)),               # 202611050949C222, Optic "Antonio García Montero"
        ("Chema Andres", ("C1DC38FF7A71E838",)),          # Sunderland v Brighton, Optic "Jose Maria Andres Baixauli"
    )
}


def optic_id_side(dkex_name: str, team_map: dict[str, str]) -> str | None:
    """Fixture side a pinned DKEX name names, via its Optic competitor id.

    ``team_map`` is the fixture's ``{optic_team_id: side}``; a name that
    is not pinned, or whose ids hit no side or both, is no side.
    """
    ids = OPTIC_IDS_BY_DKEX_NAME.get(dkex_name.strip().casefold(), frozenset())
    sides = {team_map[i] for i in ids if i in team_map}
    return sides.pop() if len(sides) == 1 else None


def city_abbrev_fits(dkex_name: str, optic_name: str, optic_abbr: str = "") -> bool:
    """True for ``DEN Broncos`` vs ``Denver Broncos`` (abbrev ``DEN``)."""
    raw = tokens(dkex_name)
    if len(raw) < 2:
        return False
    lead = raw[0]
    if not lead.isupper() or len(lead) > _MAX_CITY_ABBREV:
        return False
    nick = [t.upper() for t in raw[1:]]
    full = [t.upper() for t in tokens(optic_name)]
    if len(full) <= len(nick) or full[-len(nick):] != nick:
        return False
    city = full[: -len(nick)]
    if optic_abbr and lead == optic_abbr.strip().upper():
        return True
    if len(city) >= 2 and lead == "".join(word[0] for word in city):
        return True
    if len(lead) >= 2 and city[0].startswith(lead):
        return True
    return _letters_in_order(lead, "".join(city))


def _letters_in_order(abbrev: str, city: str) -> bool:
    """True when ``abbrev`` opens ``city`` and its letters follow in order.

    ``WPG`` / ``WINNIPEG``, ``STL`` / ``STLOUIS``, ``OKC`` /
    ``OKLAHOMACITY``, ``BKN`` / ``BROOKLYN``.  Only reached once the
    nickname has matched the Optic name's tail word for word, which is
    what carries the match; this just checks the city is not another.
    """
    if len(abbrev) < 2 or not city.startswith(abbrev[0]):
        return False
    at = 1
    for letter in abbrev[1:]:
        at = city.find(letter, at) + 1
        if at == 0:
            return False
    return True


#: Shortest all-capitals DKEX name read as initials (``LAFC``).
_MIN_ACRONYM = 3
_CONNECTORS = frozenset({"DE", "LA", "DEL", "DA", "DO", "OF", "THE"})


def _acronym(words: list[str]) -> str:
    """Initials of an Optic club name; a two-letter word stays whole (``Los Angeles FC`` -> ``LAFC``)."""
    return "".join(w if len(w) <= 2 else w[0] for w in words if w not in _CONNECTORS)


def club_short_fits(dkex_name: str, optic_name: str) -> bool:
    """True for ``Dortmund`` vs ``BV Borussia 09 Dortmund``.

    Every DKEX word, in order, must equal an Optic word or be the start
    of one (three letters at least), and one DKEX word of four letters or
    more must land.  Accents fold (``Gremio`` / ``Grêmio``), as do ``ł``,
    ``ø``, ``ß`` and apostrophes; ``Utd`` reads as ``United``.
    """
    raw = tokens(dkex_name.translate(_CLUB_FOLD))
    short = [_CLUB_WORDS.get(t.upper(), t.upper()) for t in raw]
    full = [t.upper() for t in tokens(optic_name.translate(_CLUB_FOLD))]
    if not short or not full:
        return False
    if len(raw) == 1 and raw[0].isupper() and len(raw[0]) >= _MIN_ACRONYM:
        return raw[0] == _acronym(full)
    at = 0
    anchored = False
    for word in short:
        hit = next(
            (j for j in range(at, len(full))
             if full[j] == word or (len(word) >= _MIN_PREFIX and full[j].startswith(word))),
            None,
        )
        if hit is None:
            return False
        anchored = anchored or len(word) >= _MIN_ANCHOR
        at = hit + 1
    return anchored


def school_prefix_fits(dkex_name: str, optic_name: str) -> bool:
    """True for ``Sam Houston`` vs ``Sam Houston State``.

    DKEX sometimes writes a school without the word Optic ends its name
    on.  Every DKEX word must equal the matching leading word of the Optic
    name, and the Optic name must go on.  This is only a fallback: it runs
    when no other rule places the name, so ``Michigan`` still means
    ``Michigan`` and never ``Michigan State`` when both are on the card.
    """
    short = [t.upper() for t in tokens(dkex_name)]
    full = [t.upper() for t in tokens(optic_name)]
    return bool(short) and len(full) > len(short) and full[: len(short)] == short


def team_side_for(
    claimed: str,
    *,
    home: str,
    away: str,
    home_name: str = "",
    away_name: str = "",
    club_short: bool = False,
) -> str | None:
    """``home`` or ``away`` when the DKEX name fits exactly one fixture side.

    A side fits when the shared ``team_side`` names it on its own, when
    :func:`city_abbrev_fits` holds, or -- only with ``club_short`` -- when
    :func:`club_short_fits` holds.  Every side any rule hits is counted,
    so a name the rules would place on different sides is no side at all.
    When none of those places the name, :func:`school_prefix_fits` is tried.
    """
    claimed = _TEAM_TAG.sub("", claimed).strip()
    hits: list[str] = []
    for side, name in ((home, home_name), (away, away_name)):
        if not side:
            continue
        alone = team_side(claimed, home=side, away="", home_name=name)
        if (
            alone == side
            or (name and city_abbrev_fits(claimed, name, side))
            or (club_short and name and club_short_fits(claimed, name))
        ):
            hits.append(side)
    if not hits:
        hits = [
            side for side, name in ((home, home_name), (away, away_name))
            if side and name and school_prefix_fits(claimed, name)
        ]
    unique = list(dict.fromkeys(hits))
    return unique[0] if len(unique) == 1 else None


def person_side_for(
    claimed: str,
    *,
    home: str,
    away: str,
    home_name: str = "",
    away_name: str = "",
) -> str | None:
    """``home`` or ``away`` for a tennis player or fighter named ``claimed``.

    The exact canonical name first, then ``names_close`` (same first and
    last word, so a middle name or initials may differ), and the first
    tier that hits decides.  A name that fits both sides is no side.  The
    looser ``names_fit`` tier is not used: a fixture is two people, and
    a wrong side here puts every contract on the other competitor.
    """
    want = normalize_player_name(claimed)
    if not want:
        return None
    sides = [(side, name) for side, name in ((home, home_name), (away, away_name)) if side and name]
    for fits in (
        lambda name: normalize_player_name(name) == want,
        lambda name: names_close(claimed, name, player=True),
        # A second family name (``Dellien`` / ``Dellien Velasco``): both
        # players of the fixture must still land.  A misspelt name is no fit.
        lambda name: _both_ways_alike(want, normalize_player_name(name)),
    ):
        hits = list(dict.fromkeys(side for side, name in sides if fits(name)))
        if hits:
            return hits[0] if len(hits) == 1 else None
    return None


#: Shared leading letters that make two given names one ("matthew" / "matty").
_MIN_SHARED_PREFIX = 4
#: How alike two spellings of one name part must be ("tristan" / "trystan").
_MIN_NAME_RATIO = 0.8
#: How alike two whole names must be when no part is spelled the same
#: (``yegor_yarmolyuk`` / ``yehor_yarmoliuk``).
_MIN_WHOLE_RATIO = 0.85


def _name_parts(normalized: str) -> list[str]:
    return [p for p in re.split(r"[_-]", normalized) if p]


def _part_alike(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) <= 2 or len(b) <= 2:  # an initialism: "KC" for "Kevin"
        short, long_ = sorted((a, b), key=len)
        return len(long_) > 2 and long_.startswith(short[0])
    if len(a) >= _MIN_SHARED_PREFIX and len(b) >= _MIN_SHARED_PREFIX and a[:_MIN_SHARED_PREFIX] == b[:_MIN_SHARED_PREFIX]:
        return True
    return SequenceMatcher(None, a, b).ratio() >= _MIN_NAME_RATIO


def player_alike(want: str, shown: str) -> bool:
    """True when two normalized player names are one person spelled differently.

    Any of: the DKEX parts are an in-order subset of Optic's with the family
    name last (a dropped middle or second family name -- ``joao_klauss`` /
    ``joao_klauss_de_mello``); the same parts in another order
    (``jeong_sang-bin`` / ``sang-bin_jeong``); same number of parts, one
    exactly equal and the rest spelled alike (``connor_antley`` /
    ``conner_antley``, ``kc_concepcion`` / ``kevin_concepcion``); or a single
    word that is one whole part of the Optic name (``artur``).  The caller
    accepts only a unique hit, which is what keeps this loose.
    """
    a, b = _name_parts(want), _name_parts(shown)
    if not a or not b or a == b:
        return a == b and bool(a)
    if len(a) == 1:
        return a[0] in b and len(a[0]) >= _MIN_SHARED_PREFIX
    if sorted(a) == sorted(b):
        return True
    it = iter(b)
    if all(part in it for part in a):
        return True
    if len(a) == len(b):
        if any(x == y for x, y in zip(a, b)):
            return all(_part_alike(x, y) for x, y in zip(a, b))
        return SequenceMatcher(None, "_".join(a), "_".join(b)).ratio() >= _MIN_WHOLE_RATIO
    # A short given name and a family name inside a longer Optic name
    # (``dani_lorenzo`` / ``daniel_lorenzo_guerrero``).
    return len(a) == 2 and len(b) > 2 and a[1] in b[1:] and _part_alike(a[0], b[0])


def _both_ways_alike(a: str, b: str) -> bool:
    """One name's parts are an in-order subset of the other's (a second family name, dropped or added)."""
    pa, pb = _name_parts(a), _name_parts(b)
    if len(pa) < 2 or len(pb) < 2 or pa == pb:
        return False
    short, long_ = sorted((pa, pb), key=len)
    it = iter(long_)
    return all(part in it for part in short)
