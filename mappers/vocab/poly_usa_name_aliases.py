"""Polymarket US team name → the same club's Optic display name.

Exact pairs only, for clubs the gateway spells in a way no name rule here
fits (``Beşiktaş JK`` / ``Beşiktaş Jimnastik Kulübü``). The key is the
gateway's own ``team.name`` casefolded, the value Optic's competitor name as
listed on its fixture (read 2026-10-19). A hit only adds the Optic name to
the names tried against a fixture side; kickoff window, both teams fitting
and uniqueness still decide the bind. Never add a pair that is not the same
club, and never a stem: a wrong bind is worse than an unmapped market.
"""

from __future__ import annotations

POLY_USA_NAME_ALIASES: dict[str, str] = {
    "beşiktaş jk": "Beşiktaş Jimnastik Kulübü",
    "van spor fk": "Van Spor Futbol Kulübü",
    "lkp motor lublin": "Motor Lublin SA",
    "zaglebie lubin": "KGHM Zagłębie Lubin",
    "fk rodina moskva": "Rodina Moscow",
    "el ahly sc": "Al Ahly FC",
    "el qanah club": "Alqana",
    "krasava eny ypsonas fc": "Krasava Ypsona FC",
    "ca mineiro": "Clube Atlético Mineiro",
    "sk slavia prague b": "SK Slavia Praha II",
    # Süper Lig / TFF 1. Lig, read 2026-10-26: the gateway's SK / FK / -spor
    # spellings vs Optic's Spor / Futbol Kulübü; opponent binds on the same
    # Optic fixture (id after each pair).
    "rams başakşehir fk": "Medipol İstanbul Başakşehir Futbol Kulübü",  # 2026102630861878
    "galatasaray sk": "Galatasaray Spor Kulübü",  # 20261030D8F672EB
    "fenerbahçe sk": "Fenerbahçe Spor Kulübü",  # 202610260014BDE8
    "gençlerbirliği sk": "Gençlerbirliği Spor Kulübü",  # 202610252DDC2B1A
    "göztepe sk": "Göztepe Spor Kulübü",  # 2026102562BB91DE
    "gaziantep fk": "Gaziantep Futbol Kulübü",  # 202610240CFE91B7
    "eyüpspor": "Eyüp Spor Kulübü",  # 2026102456A952AD
    "bandirmaspor": "Bandırma Spor Kulübü",  # 2026103157F5DF47
    "batman petrolspor": "Batman Petrol Spor Kulübü",  # 2026103193B1ABB4
    "fatih karagumruk istanbul": "Fatih Karagümrük Spor Kulübü",  # 20261031AA8C426C
    "umraniyespor": "Ümraniye Spor Kulübü",  # 202611014E5DAF63
    # Greek Cup / DFB-Pokal, read 2026-10-27; opponent binds on its own.
    # The cup Darmstadt is a second gateway team (svd), not the bun2 d98.
    "sv darmstadt 98": "SV Darmstadt 1898",  # 20261027F58B4439
    "panathinaikos athens": "Panathinaikos FC",  # 20261028E63829B0
    "nestos chrysoupoli fc": "AS Nestos Chrysoupolis",  # 20261028A8F37259
    # Saudi Pro League, read 2026-11-05: gateway "<club> Saudi Club" vs Optic
    # competitor names on saudi_arabia_-_saudi_league (NEOM SC is identical).
    "abha saudi club": "Abha FC",
    "al fateh saudi club": "Al Fateh SC",
    "al fayha saudi club": "Al Fayha FC",
    "al hazem sc": "Al Hazm",
    "al ittihad saudi club": "Al Ittihad FC",
    "al khaleej saudi club": "Al Khaleej FC",
    "al kholood saudi club": "Al Kholood Club",
    "al nassr saudi club": "Al Nassr FC",
    "al qadisiyah saudi club": "Al-Qadsiah Al Khubar",
    "al riyadh saudi club": "Al Riyadh SC",
    "al shabab saudi club": "Al Shabab FC",
}


def optic_names_for(names: list[str]) -> list[str]:
    """Optic spellings of the gateway names that have a pinned pair."""
    return [
        POLY_USA_NAME_ALIASES[n.casefold()]
        for n in names if n.casefold() in POLY_USA_NAME_ALIASES
    ]
