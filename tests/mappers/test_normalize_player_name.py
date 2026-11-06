import pytest

from mappers.name_match import levenshtein
from mappers.shared import normalize_player_name


@pytest.mark.parametrize("raw, expected", [
    # Plain name
    ("LeBron James", "lebron_james"),
    # Diacritics
    ("Nikola Jokić", "nikola_jokic"),
    ("Nolan Traoré", "nolan_traore"),
    # Generational suffixes
    ("Wendell Carter Jr.", "wendell_carter"),
    ("Jaren Jackson Jr", "jaren_jackson"),
    ("Dennis Smith Sr.", "dennis_smith"),
    ("Bogdan Bogdanović III", "bogdan_bogdanovic"),
    ("Marcus Morris II", "marcus_morris"),
    ("Walker Kessler IV", "walker_kessler"),
    # Periods in initials
    ("P.J. Washington", "pj_washington"),
    ("O.G. Anunoby", "og_anunoby"),
    ("R.J. Barrett", "rj_barrett"),
    # Extra whitespace
    ("  LeBron   James  ", "lebron_james"),
    # Diacritics + generational suffix combined
    ("Théo Maledon Jr.", "theo_maledon"),
    # Only first matching suffix is stripped (Jr not re-applied)
    ("Kenyon Martin Jr", "kenyon_martin"),
    # NFD-immune base letters folded explicitly (_BASE_LETTER_FOLD):
    # these carry no combining mark, so the Mn-strip alone leaves
    # them non-ASCII and the entity can't merge with an ASCII source
    ("Martin Ødegaard", "martin_odegaard"),
    ("Alexander Sørloth", "alexander_sorloth"),
    ("Barış Alper Yılmaz", "baris_alper_yilmaz"),   # ş decomposes, ı doesn't
    ("Pascal Groß", "pascal_gross"),
    ("Łukasz Fabiański", "lukasz_fabianski"),
    ("Henrik Sælebakke Falchener", "henrik_saelebakke_falchener"),
    ("Albert Guðmundsson", "albert_gudmundsson"),
    # Hyphens and apostrophes are KEPT — they live in persisted
    # entities (gold, market_mapping) and all sources spell them
    # consistently for mapped players; see the docstring
    ("Karl-Anthony Towns", "karl-anthony_towns"),
    ("De'Aaron Fox", "de'aaron_fox"),
])
def test_normalize_player_name(raw, expected):
    assert normalize_player_name(raw) == expected


@pytest.mark.parametrize("a, b, expected", [
    ("nikola_jokic", "nikola_jokic", 0),
    ("nikola_joki", "nikola_jokic", 1),
    ("jamal_murry", "jamal_murray", 1),
    ("", "abc", 3),
    ("abc", "", 3),
    ("", "", 0),
])
def test_levenshtein(a, b, expected):
    assert levenshtein(a, b) == expected
    assert levenshtein(b, a) == expected  # symmetry
