"""team_side names one fixture side, or nothing."""

from mappers.team_side import team_side


def test_code_and_display_name_both_resolve() -> None:
    assert team_side("ALB", home="ALB", away="SMR") == "ALB"
    assert team_side(
        "Albania", home="ALB", away="SMR",
        home_name="Albania", away_name="San Marino",
    ) == "ALB"


def test_both_sides_or_neither_is_unnamed() -> None:
    assert team_side(
        "Albania", home="ALB", away="SMR",
        home_name="Albania", away_name="Albania",
    ) is None
    assert team_side("ZZZ", home="ALB", away="SMR", home_name="Albania", away_name="San Marino") is None
    assert team_side("", home="ALB", away="SMR") is None
