"""Which Polymarket US leagues map onto which Optic league.

Keyed on both venues' typed league ids: the Optic league id and the
gateway's numeric league ``id`` (``GET /v2/sports`` → ``leagues[].id``).
The gateway's league ``slug`` is never an identity here; the fetch reads it
from the catalogue only to build the ``/v2/leagues/{slug}/events`` URL.

One Optic league can take several US leagues (Optic files Serie C as one
league; Polymarket US splits it by girone), and one US league can feed
several Optic leagues (``ATP`` carries tour and Challenger events).  The
mapper runs Polymarket US on every Optic league here and on no other; a tip
``polymarket_usa`` exchange row is ignored.  Comments are the gateway's
league ``name``; catalogue read 2026-10-14.
"""

from __future__ import annotations

from mappers.seed.pdc_leagues import PDC_OPTIC_LEAGUES

US_LEAGUE_IDS_BY_OPTIC: dict[str, frozenset[int]] = {
    "afc_-_champions_league": frozenset({235}),  # AFC Champions League Elite
    "argentina_-_primera_division": frozenset({94}),  # Liga Argentina
    "argentina_-_primera_nacional": frozenset({155}),  # Primera Nacional
    "atp": frozenset({12}),  # ATP
    "atp_challenger": frozenset({12}),  # ATP
    "atp_doubles": frozenset({214}),  # ATP Doubles
    "australia_-_cup": frozenset({109}),  # Australia Cup
    "australia_-_nbl": frozenset({250}),  # Australia NBL (catalogue read 2026-11-05)
    "austria_-_bundesliga": frozenset({139}),  # Austrian Bundesliga
    "belgium_-_jupiler_pro_league": frozenset({296}),  # Belgian Pro League
    "bolivia_-_division_professional": frozenset({172}),  # Liga Boliviana
    "boxing_matches": frozenset({55}),  # Boxing
    "brazil_-_copa_do_brasil": frozenset({171}),  # Copa do Brasil
    "brazil_-_serie_a": frozenset({89}),  # Brasileirão
    "brazil_-_serie_b": frozenset({90}),  # Série B
    "brazil_-_serie_c": frozenset({309}),  # Brasileirão Série C
    "bulgaria_-_parva_liga": frozenset({136}),  # Parva Liga
    "caf_-_africa_cup_of_nations_qualifiers": frozenset({320}),  # Africa Cup of Nations Qualification
    "chile_-_primera_division": frozenset({100}),  # Primera Chile
    "china_-_super_league": frozenset({93}),  # CSL
    "colombia_-_primera_a": frozenset({97}),  # Liga Colombia
    "concacaf_-_nations_league": frozenset({281}),  # CONCACAF Nations League
    "conmebol_-_copa_libertadores": frozenset({188}),  # Copa Libertadores
    "conmebol_-_copa_sudamericana": frozenset({108}),  # Sudamericana
    "costa_rica_-_primera_division": frozenset({104}),  # Liga Promérica
    "croatia_-_1_hnl": frozenset({300}),  # Croatian HNL
    "cs2": frozenset({21}),  # CS2
    "call_of_duty": frozenset({23}),  # Call of Duty
    "cyprus_-_first_division": frozenset({312}),  # Cyprus First Division
    "czech_republic_-_first_league": frozenset({98}),  # Chance Liga
    "czech_republic_-_fnl": frozenset({297}),  # Czech National Football League
    "czech_republic_-_nbl": frozenset({375}),  # Czech NBL
    "denmark_-_1st_division": frozenset({145}),  # Danish 1. Division
    "denmark_-_superliga": frozenset({102}),  # Superliga
    "dota_2": frozenset({41}),  # Dota 2
    "ecuador_-_serie_a": frozenset({144}),  # LigaPro Ecuador
    "egypt_-_premier_league": frozenset({231}),  # Egyptian Premier League
    "england_-_championship": frozenset({194}),  # EFL Championship
    "england_-_county_championship": frozenset({224}),  # County Championship
    "england_-_efl_cup": frozenset({190}),  # EFL Cup (catalogue read 2026-10-26)
    "england_-_league_1": frozenset({301}),  # EFL League One
    "england_-_league_2": frozenset({302}),  # EFL League Two
    "england_-_national_league": frozenset({303}),  # English National League
    "england_-_premier_league": frozenset({9}),  # EPL
    "england_-_womens_super_league": frozenset({202}),  # WSL
    "euroleague": frozenset({255}),  # EuroLeague
    "france_-_lnb_pro_a": frozenset({269}),  # France LNB Elite (Optic keeps the old Pro A name)
    "france_-_lnb_pro_b": frozenset({278}),  # France Elite 2 (Optic: Pro B)
    "finland_-_veikkausliiga": frozenset({148}),  # Veikkausliiga
    "finland_-_ykkosliiga": frozenset({149}),  # Ykkösliiga
    "france_-_ligue_1": frozenset({186}),  # Ligue 1
    "france_-_ligue_2": frozenset({187}),  # Ligue 2
    "germany_-_bbl": frozenset({252}),  # Basketball Bundesliga
    "germany_-_bundesliga": frozenset({14}),  # Bundesliga
    "germany_-_bundesliga_2": frozenset({294}),  # 2. Bundesliga
    "germany_-_frauen_bundesliga": frozenset({313}),  # Frauen-Bundesliga
    "germany_-_dfb_pokal": frozenset({197}),  # DFB-Pokal
    "greece_-_cup": frozenset({280}),  # Greek Cup (catalogue read 2026-10-27)
    "greece_-_super_league": frozenset({298}),  # Super League Greece
    "greece_-_a1_league": frozenset({273}),  # Greece GBL (Optic: A1 League)
    "guatemala_-_liga_nacional": frozenset({103}),  # Liga Nacional
    "hungary_-_nb_i": frozenset({234}),  # Hungarian NB I
    "iceland_-_besta_deild_karla": frozenset({156}),  # Besta deild
    "indonesia_-_liga_1": frozenset({299}),  # Indonesia Super League
    "international_-_champions_league": frozenset({254}),  # Basketball Champions League
    "international_-_club_friendlies": frozenset({141}),  # Club Friendlies
    "international_-_friendlies": frozenset({51}),  # Friendlies
    "international_-_vtb_united_league": frozenset({266}),  # VTB United League
    "international_-_odi_matches": frozenset({121}),  # ODI (M)
    "international_-_odi_matches_women": frozenset({122}),  # ODI Intl (W)
    "international_-_t20_matches_women": frozenset({119}),  # T20 Intl (W)
    "international_-_test_matches": frozenset({123}),  # Test Intl
    "ireland_-_division_1": frozenset({147}),  # LOI First Division
    "ireland_-_premier_league": frozenset({146}),  # LOI Premier Division
    "italy_-_coppa_italia": frozenset({185}),  # Coppa Italia
    "italy_-_serie_a": frozenset({15}),  # Serie A
    "italy_-_serie_b": frozenset({198}),  # Serie B
    "italy_-_serie_c": frozenset({306, 307, 308}),  # Serie C Girone A, Serie C Girone B, Serie C Girone C
    "itf_men": frozenset({58}),  # ITF Mens
    "itf_men_doubles": frozenset({58}),  # ITF Mens (doubles events)
    "itf_women": frozenset({59}),  # ITF Womens
    "itf_women_doubles": frozenset({59}),  # ITF Womens (doubles events)
    "japan_-_b1_league": frozenset({315}),  # Japan B.League Premier (Optic: B1)
    "japan_-_j1_league": frozenset({291}),  # J1 League
    "japan_-_j2_league": frozenset({292}),  # J2 League
    "kbo": frozenset({60}),  # KBO
    "korea_-_k1_league": frozenset({91}),  # K League 1
    "korea_-_kbl": frozenset({323}),  # Korean Basketball League
    "laver_cup": frozenset({268}),  # Laver Cup
    "league_of_legends": frozenset({22}),  # League of Legends
    "malaysia_-_super_league": frozenset({305}),  # Malaysia Super League
    "mexico_-_liga_de_expansion_mx": frozenset({154}),  # Liga de Expansión MX
    "mexico_-_liga_mx": frozenset({88}),  # Liga MX
    "mexico_-_lnbp": frozenset({253}),  # LNBP
    "mlb": frozenset({5}),  # MLB
    "nba": frozenset({2}),  # NBA
    "ncaab": frozenset({4}),  # CBB
    "ncaaw": frozenset({17}),  # WCBB
    "ncaaf": frozenset({7}),  # CFB
    # WCBB: moneyline / spread / total read "full game, overtime included",
    # the CBB wording. Live replay 2026-11-03: 222 of 501 events bind on
    # teams + kickoff, every one the right game; the rest stay unbound.
    "ncaaw": frozenset({17}),  # WCBB
    "netherlands_-_eredivisie": frozenset({232}),  # Eredivisie
    "nfl": frozenset({1}),  # NFL
    "nhl": frozenset({3}),  # NHL
    "north_america_-_leagues_cup": frozenset({178}),  # Leagues Cup
    "overwatch": frozenset({130}),  # Overwatch
    "norway_-_1_divisjon": frozenset({143}),  # OBOS-ligaen
    "norway_-_eliteserien": frozenset({92}),  # Eliteserien
    "npb": frozenset({61}),  # NPB
    "paraguay_-_division_intermedia": frozenset({157}),  # Paraguay Segunda
    "paraguay_-_primera_division": frozenset({293}),  # Paraguay Primera División
    "peru_-_primera_division": frozenset({95}),  # Liga 1
    "poland_-_ekstraklasa": frozenset({135}),  # Ekstraklasa
    "portugal_-_primeira_liga": frozenset({189}),  # Liga Portugal
    "portugal_-_taca_de_portugal": frozenset({200}),  # Taça de Portugal
    "rainbow_six_siege": frozenset({131}),  # Rainbow Six Siege
    "romania_-_liga_i": frozenset({96}),  # SuperLiga
    "russia_-_khl": frozenset({258}),  # KHL
    "russia_-_premier_league": frozenset({99}),  # RPL
    "saudi_arabia_-_saudi_league": frozenset({193}),  # Saudi Pro League
    "scotland_-_premiership": frozenset({105}),  # Scottish Prem
    "slovakia_-_2_liga": frozenset({321}),  # Slovak 2. Liga
    "slovakia_-_sbl": frozenset({276}),  # Slovakia SBL
    "slovakia_-_superliga": frozenset({101}),  # Niké Liga
    "slovenia_-_prvaliga": frozenset({137}),  # PrvaLiga
    "south_africa_-_premier_league": frozenset({311}),  # South African Premiership
    "spain_-_liga_acb": frozenset({74}),  # Spain Liga ACB
    "spain_-_la_liga": frozenset({16}),  # La Liga
    "spain_-_la_liga_2": frozenset({196}),  # LaLiga 2
    "spain_-_liga_f": frozenset({310}),  # Liga F
    "sweden_-_allsvenskan": frozenset({142}),  # Allsvenskan
    "sweden_-_superettan": frozenset({151}),  # Superettan
    "switzerland_-_challenge_league": frozenset({152}),  # Challenge League
    "switzerland_-_super_league": frozenset({134}),  # Swiss Super League
    "thailand_-_thai_league_1": frozenset({304}),  # Thai League 1
    "turkey_-_1_lig": frozenset({295}),  # TFF 1. Lig
    "turkey_-_bsl": frozenset({270}),  # Turkey BSL
    "turkey_-_super_lig": frozenset({195}),  # Süper Lig
    "uae_-_pro_league": frozenset({221}),  # UAE Pro League
    "uefa_-_champions_league": frozenset({10}),  # UCL
    "uefa_-_champions_league_women": frozenset({112}),  # UWCL
    "uefa_-_europa_conference_league": frozenset({107}),  # UECL
    "uefa_-_europa_league": frozenset({106}),  # UEL
    "uefa_-_nations_league": frozenset({279}),  # UEFA Nations League
    "uefa_-_super_cup": frozenset({201}),  # UEFA Super Cup
    "ufc": frozenset({6}),  # UFC
    "uruguay_-_primera_division": frozenset({153}),  # Primera Uruguay
    "usa_-_major_league_soccer": frozenset({8}),  # MLS
    "usa_-_nwsl": frozenset({111}),  # NWSL
    "usa_-_usl_championship": frozenset({140}),  # USL Championship
    "uzbekistan_-_super_league": frozenset({150}),  # Uzbekistan Superliga
    "valorant": frozenset({40}),  # Valorant
    "utr_men": frozenset({251}),  # UTR
    "utr_women": frozenset({251}),  # UTR
    "west_indies_-_caribbean_premier_league": frozenset({120}),  # Caribbean Premier League CR
    "wnba": frozenset({28}),  # WNBA
    "wta": frozenset({13}),  # WTA
    "wta_doubles": frozenset({222}),  # WTA Doubles
}


# Darts: one gateway league per circuit, every Optic PDC competition reads it.
US_LEAGUE_IDS_BY_OPTIC.update(
    {optic_id: frozenset({175}) for optic_id in PDC_OPTIC_LEAGUES}  # PDC
)
US_LEAGUE_IDS_BY_OPTIC["modus_-_super_series"] = frozenset({211})  # MODUS Super Series


def us_league_ids(optic_league_ids: tuple[str, ...]) -> frozenset[int]:
    """Gateway league ids for a run-set league's Optic league ids."""
    out: set[int] = set()
    for optic_id in optic_league_ids:
        out |= US_LEAGUE_IDS_BY_OPTIC.get(optic_id, frozenset())
    return frozenset(out)


def all_us_league_ids() -> frozenset[int]:
    """Every gateway league id the mapper reads (the fetch walks these)."""
    return frozenset().union(*US_LEAGUE_IDS_BY_OPTIC.values())
