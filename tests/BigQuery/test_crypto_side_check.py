"""crypto.com live side check (epic &91): flips, spread signs, blindness."""

from __future__ import annotations

from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

from BigQuery import crypto_side_check as check
from BigQuery.crypto_side_check import Row, format_alert, names_fit, verdict


def _row(
    sel: str,
    own: str,
    sibs: tuple[str, ...] = (),
    *,
    market_type: str = "moneyline",
    line: float | None = None,
    ev: str = "",
    in_cat: bool = True,
) -> Row:
    return Row(
        league="ufc",
        market_type=market_type,
        symbol="NX.F.OPT.UFC-00008-261003-M.O.1.1",
        sel=sel,
        line=line,
        commit="8959d90f8706",
        own=own,
        ev=ev,
        in_cat=in_cat,
        sibs=sibs,
    )


def _judge(rows: list[Row]) -> tuple[str, str] | None:
    return format_alert(rows, Counter(verdict(r) for r in rows))


def test_names_fit_ignores_word_order_accents_and_suffixes() -> None:
    assert names_fit("Cong Wang", "Wang Cong")
    assert names_fit("Club de Fútbol América", "club de futbol america")
    assert names_fit("Wyoming", "Wyoming Cowboys")
    assert not names_fit("Bruce Whitehead", "Jacobe Smith")
    assert not names_fit("", "Jacobe Smith")


def test_incident_row_is_a_flip() -> None:
    """09-30: symbol is Jacobe Smith's, we priced Bruce Whitehead."""
    assert verdict(_row("Bruce Whitehead", "Jacobe Smith", ("Bruce Whitehead",))) == "FLIP"


def test_reversed_name_order_flip_is_caught() -> None:
    """The row the first cleanup missed: Natalia Silva's symbol mapped to Cong Wang."""
    assert verdict(_row("Cong Wang", "Natalia Silva", ("Wang Cong",))) == "FLIP"


def test_correct_row_and_spelling_noise_do_not_alert() -> None:
    assert verdict(_row("Jacobe Smith", "Jacobe Smith", ("Bruce Whitehead",))) == "ok"
    assert verdict(_row("Miami (OH)", "Miami Ohio RedHawks", ("Toledo",))) == "name_noise"
    assert verdict(_row("Draw", "", ("Fnatic", "BIG"))) == "no_participant"


def test_spread_sign_flip() -> None:
    wrong = _row(
        "CA Velez Sarsfield",
        "CA Velez Sarsfield",
        market_type="point_spread",
        line=0.5,
        ev="CA Velez Sarsfield -0.5 to win",
    )
    right = _row(
        "CA Velez Sarsfield",
        "CA Velez Sarsfield",
        market_type="point_spread",
        line=-0.5,
        ev="CA Velez Sarsfield -0.5 to win",
    )
    assert verdict(wrong) == "SIGN_FLIP"
    assert verdict(right) == "ok"


def test_flip_raises_critical_alert() -> None:
    rows = [_row("fnatic", "BIG", ("Fnatic",)), _row("Jacobe Smith", "Jacobe Smith")] * 5
    alert = _judge(rows)
    assert alert is not None
    severity, text = alert
    assert severity == "critical"
    assert text.startswith("[CRITICAL] crypto.com SIDE FLIP: 5 live mapping row(s)")
    assert "mapped 'fnatic'" in text and "lists 'BIG'" in text


def test_clean_result_is_silent() -> None:
    assert _judge([_row("Jacobe Smith", "Jacobe Smith")] * 20) is None


def test_blind_when_catalogue_missing_or_empty(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "rs-marketmaking")
    monkeypatch.delenv("CRYPTO_SIDE_CHECK_EXPECT_ROWS", raising=False)
    assert _judge([]) is not None
    blind = [_row("Jacobe Smith", "", in_cat=False)] * 20 + [_row("Jacobe Smith", "Jacobe Smith")]
    alert = _judge(blind)
    assert alert is not None and alert[0] == "warning" and "BLIND" in alert[1]


def test_crash_publishes_warning_and_never_fails() -> None:
    publisher = MagicMock()
    with (
        patch.object(check, "ro_client", side_effect=RuntimeError("no creds")),
        patch.object(check, "build_publisher", return_value=publisher),
    ):
        assert check.main() == 0
    severity, text = publisher.publish.call_args.args
    assert severity == "warning" and "FAILED to run" in text
    publisher.close.assert_called_once()


def test_flip_prints_one_alert_line_even_when_publish_fails(capsys) -> None:
    """cron_pipeline.sh greps ``^ALERT:`` — that path must not depend on Pub/Sub."""
    publisher = MagicMock()
    publisher.publish.side_effect = RuntimeError("topic gone")
    flip = _judge([_row("Bruce Whitehead", "Jacobe Smith", ("Bruce Whitehead",))])
    assert flip is not None and flip[0] == "critical"
    with (
        patch.object(check, "build_publisher", return_value=publisher),
        pytest.raises(RuntimeError),
    ):
        check.publish("critical", flip[1])
    alerts = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ALERT: ")]
    assert len(alerts) == 1 and "SIDE FLIP" in alerts[0] and "Jacobe Smith" in alerts[0]
    publisher.close.assert_called_once()


def test_empty_result_is_silent_where_crypto_is_not_live(monkeypatch) -> None:
    """TEST has no crypto.com rows; an empty result there must not page."""
    monkeypatch.setenv("GCP_PROJECT", "marketmaking-test")
    monkeypatch.delenv("CRYPTO_SIDE_CHECK_EXPECT_ROWS", raising=False)
    assert _judge([]) is None
    monkeypatch.setenv("CRYPTO_SIDE_CHECK_EXPECT_ROWS", "true")
    assert _judge([]) is not None
    # A flip still pages everywhere.
    monkeypatch.setenv("CRYPTO_SIDE_CHECK_EXPECT_ROWS", "false")
    assert _judge([_row("Bruce Whitehead", "Jacobe Smith", ("Bruce Whitehead",))]) is not None
