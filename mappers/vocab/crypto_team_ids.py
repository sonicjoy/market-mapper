"""crypto.com EXTERNAL team ids -> canonical team keys, per league (code-owned, not the tip).

crypto.com renumbered CFB teams (50000xxx) and the tip carries no crypto_id
alias for most of them, so the FIX semantic path could not attach those games
to an Optic fixture: on 2026-10-10 84 of 106 CFB crypto games went unmatched
and every period line / alt line / prop on them stayed unmapped.

Derived from id evidence only: market_mapping crypto.com moneyline and
point_spread rows whose symbol Optic itself stamped (Optic source_ids decode,
via kalshi_ticker / dkex_symbol / crypto_fixture matches), joined to
crypto_security_def — outcome Home/Away gives the crypto team id, the row's
side gives the canonical key.  Each id resolved to exactly one canonical; no
name matching.  The tip wins on any conflict (see pipeline), except for
CRYPTO_TEAM_ID_OVERRIDES below.

The soccer / tennis / esports entries (2026-10-22) bind crypto ids the mapper
logged as unresolved ("crypto [<league>]: no schedule game ... <raw id>@...")
to the canonical key of the same Optic fixture, read from live
markets_us.market_mapping rows (any book) for that fixture.  Most of these
keys have no tip entity in the league, so the pipeline also accepts Optic
schedule keys as canonicals for this table.  Evidence: Optic fixture id,
crypto underlying, kickoff UTC.
"""

from __future__ import annotations

CRYPTO_TEAM_IDS: dict[str, dict[str, str]] = {
    "ncaaf": {
        "50000221": "AFA",  # Air Force Falcons
        "50000177": "AKR",  # Akron Zips
        "50000275": "ALA",  # Alabama Crimson Tide
        "50000331": "APP",  # Appalachian State Mountaineers
        "50000255": "ASU",  # Arizona State Sun Devils
        "50000247": "ARIZ",  # Arizona Wildcats
        "50000276": "ARK",  # Arkansas Razorbacks
        "50000327": "ARST",  # Arkansas State Red Wolves
        "50000263": "ARMY",  # Army Black Knights
        "50000279": "AUB",  # Auburn Tigers
        "50000336": "BYU",  # BYU Cougars
        "50000184": "BALL",  # Ball State Cardinals
        "50000108": "BAY",  # Baylor Bears
        "50000215": "BSU",  # Boise State Broncos
        "50000035": "BC",  # Boston College Eagles
        "50000181": "BGSU",  # Bowling Green Falcons
        "50000179": "BUFF",  # Buffalo Bulls
        "50000251": "CAL",  # California Golden Bears
        "50000185": "CMU",  # Central Michigan Chippewas
        "50000088": "CSH8",  # Charleston Southern Buccaneers
        "50000142": "CLT",  # Charlotte 49ers
        "50000004": "CIN",  # Cincinnati Bearcats
        "50000081": "CCU",  # Coastal Carolina Chanticleers
        "50000217": "CSU",  # Colorado State Rams
        "50000003": "CONN",  # Connecticut Huskies
        "50000026": "DUKE",  # Duke Blue Devils
        "50000009": "ECU",  # East Carolina Pirates
        "50000187": "EMU",  # Eastern Michigan Eagles
        "50000130": "ELON",  # Elon Phoenix
        "50000145": "FAU",  # Florida Atlantic Owls
        "50000271": "FLA",  # Florida Gators
        "50000140": "FIU",  # Florida International Panthers
        "50000029": "FSU",  # Florida State Seminoles
        "50000213": "FRES",  # Fresno State Bulldogs
        "50000272": "UGA",  # Georgia Bulldogs
        "50000329": "GASO",  # Georgia Southern Eagles
        "50000328": "GSE7",  # Georgia State Panthers
        "50000032": "GTE8",  # Georgia Tech Yellow Jackets
        "50000115": "HAW",  # Hawaii Rainbow Warriors
        "50000006": "HOUSTON",  # Houston Cougars
        "50000102": "ILL3",  # Illinois Fighting Illini
        "50000093": "Indiana",  # Indiana Hoosiers
        "50000091": "IOWA",  # Iowa Hawkeyes
        "50000110": "ISU",  # Iowa State Cyclones
        "50000238": "JVST",  # Jacksonville State Gamecocks
        "50000126": "JMU",  # James Madison Dukes
        "50000106": "KU",  # Kansas Jayhawks
        "50000112": "KSU",  # Kansas State Wildcats
        "50000042": "KENN",  # Kennesaw State Owls
        "50000178": "KENT",  # Kent State Golden Flashes
        "50000268": "UK",  # Kentucky Wildcats
        "50000269": "LSU",  # LSU Tigers
        "50000137": "LT",  # Louisiana Tech Bulldogs
        "50000324": "UL",  # Louisiana-Lafayette Ragin' Cajuns
        "50000326": "UML6",  # Louisiana-Monroe Warhawks
        "50000024": "LOU",  # Louisville Cardinals
        "50000136": "MRSH",  # Marshall Thundering Herd
        "50000092": "MD",  # Maryland Terrapins
        "50000055": "MAS6",  # Massachusetts Minutemen
        "50000007": "MEM",  # Memphis Tigers
        "50000182": "M-OH",  # Miami (OH) RedHawks
        "50000023": "MFI4",  # Miami Hurricanes
        "50000097": "MSI9",  # Michigan State Spartans
        "50000135": "MTSU",  # Middle Tennessee Blue Raiders
        "50000104": "MIN3",  # Minnesota Golden Gophers
        "50000278": "MSST",  # Mississippi State Bulldogs
        "50000208": "MSI3",  # Missouri State Bears
        "50000280": "MIS6",  # Missouri Tigers
        "50000258": "NAVY",  # Navy Midshipmen
        "50000099": "NEB",  # Nebraska Cornhuskers
        "50000216": "NEV",  # Nevada Wolf Pack
        "50000214": "UNM",  # New Mexico Lobos
        "50000033": "NCSU",  # North Carolina State Wolfpack
        "50000021": "UNC",  # North Carolina Tar Heels
        "50000318": "NDSU",  # North Dakota State Bison
        "50000141": "UNT",  # North Texas Mean Green
        "50000186": "NIU",  # Northern Illinois Huskies
        "50000100": "NU",  # Northwestern Wildcats
        "50000025": "ND",  # Notre Dame Fighting Irish
        "50000180": "OHIO",  # Ohio Bobcats
        "50000098": "OSU",  # Ohio State Buckeyes
        "50000105": "OKL",  # Oklahoma Sooners
        "50000113": "OSK9",  # Oklahoma State Cowboys
        "50000138": "ODU",  # Old Dominion Monarchs
        "50000274": "OML8",  # Ole Miss Rebels
        "50000245": "ORE",  # Oregon Ducks
        "50000252": "ORST",  # Oregon State Beavers
        "50000101": "PSU",  # Penn State Nittany Lions
        "50000028": "PITT",  # Pittsburgh Panthers
        "50000094": "PUR",  # Purdue Boilermakers
        "50000146": "RIC7",  # Rice Owls
        "50000103": "RUTG",  # Rutgers Scarlet Knights
        "50000001": "SMU",  # SMU Mustangs
        "50000077": "SAC",  # Sacramento State Hornets
        "50000295": "SHSU",  # Sam Houston Bearkats
        "50000212": "SDSU",  # San Diego State Aztecs
        "50000222": "SJSU",  # San Jose State Spartans
        "50000267": "SCO2",  # South Carolina Gamecocks
        "50000011": "USF",  # South Florida Bulls
        "50000143": "USM",  # Southern Miss Golden Eagles
        "50000254": "STA3",  # Stanford Cardinal
        "50000030": "SYR",  # Syracuse Orange
        "50000114": "TCU6",  # TCU Horned Frogs
        "50000002": "TEM",  # Temple Owls
        "50000277": "TENN",  # Tennessee Volunteers
        "50000270": "TAM3",  # Texas A&M Aggies
        "50000109": "TEX",  # Texas Longhorns
        "50000332": "TXST",  # Texas State Bobcats
        "50000111": "TTE",  # Texas Tech Red Raiders
        "50000288": "CIT",  # The Citadel Bulldogs
        "50000183": "TOL",  # Toledo Rockets
        "50000333": "TROY",  # Troy Trojans
        "50000010": "TULN",  # Tulane Green Wave
        "50000005": "TLSA",  # Tulsa Golden Hurricane
        "50000134": "UAB",  # UAB Blazers
        "50000008": "UCF",  # UCF Knights
        "50000253": "UCLA",  # UCLA Bruins
        "50000218": "UNLV",  # UNLV Runnin' Rebels
        "50000246": "USC",  # USC Trojans
        "50000139": "UTE6",  # UTEP Miners
        "50000147": "UTSA",  # UTSA Roadrunners
        "50000220": "USU",  # Utah State Aggies
        "50000248": "UTA7",  # Utah Utes
        "50000273": "VAN",  # Vanderbilt Commodores
        "50000022": "UVA",  # Virginia Cavaliers
        "50000031": "VT",  # Virginia Tech Hokies
        "50000034": "WAKE",  # Wake Forest Demon Deacons
        "50000249": "WASH",  # Washington Huskies
        "50000256": "WSU",  # Washington State Cougars
        "50000107": "WVU",  # West Virginia Mountaineers
        "50000144": "WKU",  # Western Kentucky Hilltoppers
        "50000188": "WMU",  # Western Michigan Broncos
        "50000219": "WYO",  # Wyoming Cowboys
    },
    "europa_league": {
        # 20261022BF5917CC Ararat-Armenia v Alkmaar Zaanstreek / UEL-00001-261022 16:45
        "90000679": "AZ",  # AZ
        # 202610229808C143 GNK Dinamo Zagreb v Nijmegen / UEL-00003-261022 16:45
        "90000585": "DIN",  # GNK Dinamo Zagreb (was an in-memory name pin only)
        "90000685": "NEC",  # NEC
        # 202610228C423C0A Royale Union Saint-Gilloise v Hapoel Be'er Sheva / UEL-00007-261022 16:45
        "90002586": "STG",  # RU Saint-Gilloise
        # 202610226ED81A32 SK Sturm Graz v Olympique de Marseille / UEL-00008-261022 16:45
        "90000840": "STU",  # SK Puntigamer Sturm Graz
        "90000822": "OM",  # Olympique de Marseille (was an in-memory name pin only)
        # 20261022A03BAB5C Celtic FC v Real Club Celta de Vigo / UEL-00012-261022 19:00
        "90000622": "CEL",  # RC Celta de Vigo (tip entity CEL, optic 4997D3D67C77D711)
        # 2026102251D10F54 Olympiakos CFP v AC Sparta Praha / UEL-00017-261022 19:00
        "90000598": "OLY",  # Olympiakos SFP
        # NOT bound: NK Celje 90000816. Optic also keys Celje "CEL" in this
        # league (20261022866D52E6 NK Celje v FC Salzburg), same as Celta.
    },
    "europa_conference_league": {
        # 20261022D6E817FC Kairat Almaty v Panathinaikos / UCOL-00001-261022 14:30
        "90000768": "ALM",  # Qairat FK
        # 202610227D79D2C8 FC Nordsjaelland v PFK CSKA Sofia / UCOL-00002-261022 16:45
        "90001158": "CSK",  # PFK CSKA Sofia
        # 202610225CBA8AC9 Inter Club d'Escaldes v Universitatea Craiova / UCOL-00007-261022 16:45
        "90001132": "UCR",  # Universitatea Craiova
        # 20261022AB9183A5 FC Iberia 1999 v Mjallby AIF / UCOL-00009-261022 16:45
        "90001544": "IBE",  # SK Iberia 1999
        "90005324": "MJA",  # Mjallby AIF (was an in-memory name pin only)
        # 202610228ACFE08C Trabzonspor v Heart of Midlothian / UCOL-00010-261022 16:45
        "90000847": "TS",  # Trabzonspor
        "90001024": "HOMF6",  # Heart of Midlothian FC (tip entity, optic FE132DEEFF52)
        # 202610220FA9E53A Aarhus GF v KS Egnatia / UCOL-00011-261022 19:00
        "90002380": "AGF",  # Aarhus GF
        "90002782": "EGN",  # KF Egnatia Rrogozhine
        # 20261022912931CD AFC Ajax v Atalanta / UCOL-00012-261022 19:00
        "90000664": "ATA",  # Atalanta BC
        # 2026102281A08B7F FC Midtjylland v Sint-Truidense VV / UCOL-00014-261022 19:00
        "90005402": "STV",  # K. Sint-Truidense VV
        # 20261022B5ED891C FC Thun v HNK Hajduk Split / UCOL-00015-261022 19:00
        "90000753": "THU",  # FC Thun
        # 202610228780A671 FK Borac Banja Luka v Kuopion Palloseura / UCOL-00016-261022 19:00
        "90001487": "KUP",  # Kuopion PS (tip entity, optic 4D7E16232E3B)
    },
    "atp_challenger": {
        # TENNIS-0016-261021 Jie Cui v Yibing Wu, 2026-10-22 02:00.  Mapper
        # tick 2026-10-22 09:30: "crypto.com selection teams {JCI9, 730131} !=
        # fixture {JCI9, YWI5}" (Wu is aliased only in atp, as YWI6).
        "730131": "YWI5",  # Yibing Wu
    },
    "cs2": {
        # 202610229627079D TheMongolz v BIG / CS2-00001-261022 11:00
        "754871": "MGLZ",  # The MongolZ (also unbound on 2026-10-19)
        "819434": "BIG",  # BIG
    },
    "dota_2": {
        # 202610237F8B4B9D OG v 1win / DOTA2-00001-261023 08:00 (crypto "1w Team");
        # 1win also v Team Liquid 20261022FC14CE7C / DOTA2-00003-261022 14:00
        "754826": "OG",  # OG
        "1972900": "1WI5",  # 1w Team (tip entity 1win, optic 2DC78492C930)
    },
}

# Code beats the tip for these (known-wrong or duplicate tip alias).
CRYPTO_TEAM_ID_OVERRIDES: dict[str, dict[str, str]] = {
    "ufc": {
        # Tip binds 140005785 to a duplicate entity GUG; the Optic fixture
        # 2026102411F0C8B7 (Kody Steele v Noah Gugnon, 2026-10-24 14:20) keys
        # Gugnon NGO7, so UFC-00013-261024 logged "no schedule game KSO5@GUG".
        "140005785": "NGO7",  # Noah Gugnon
    },
}
