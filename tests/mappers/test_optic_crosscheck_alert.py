"""Cross-check alert: only real disagreements, and only once across cron runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from mappers.exchanges.optic_passthrough_crosscheck import TWO_WAY_NO, CrosscheckLedger
from mappers.optic_crosscheck_alert import publish_new_disagreements

_SYM = "astatc-atp-cletab-nickja-2026-10-19-sw1"


class _Pub:
    routable = True

    def __init__(self) -> None:
        self.sent: list[str] = []

    def publish(self, severity: str, text: str) -> str:
        self.sent.append(text)
        return "1"


def _ledger(*rows: tuple[str, str]) -> CrosscheckLedger:
    ledger = CrosscheckLedger()
    for token, detail in rows:
        ledger.record_disagree(
            league="atp",
            sportsbook="Polymarket (USA)",
            token=token,
            our_key="",
            optic_key="('atp',)",
            rfq_key=f"polymarket (usa)|{token}|",
            detail=detail,
        )
    return ledger


def _run_dir(root: Path, hhmm: str) -> Path:
    d = root / "2026-10-19" / hhmm
    d.mkdir(parents=True)
    return d


def test_two_way_no_is_not_alerted(tmp_path):
    pub = _Pub()
    publish_new_disagreements(
        _ledger((_SYM, TWO_WAY_NO)),
        data_dir=_run_dir(tmp_path, "12_30"),
        publisher=cast(Any, pub),
    )
    assert pub.sent == []


def test_alert_names_full_token_and_reason(tmp_path):
    pub = _Pub()
    publish_new_disagreements(
        _ledger((_SYM, "unbound")),
        data_dir=_run_dir(tmp_path, "12_30"),
        publisher=cast(Any, pub),
    )
    (text,) = pub.sent
    assert f"token {_SYM} [unbound] ours (none)" in text


def test_next_cron_run_only_alerts_what_is_new(tmp_path):
    pub = _Pub()
    publish_new_disagreements(
        _ledger(("a", "contradicts")),
        data_dir=_run_dir(tmp_path, "12_30"),
        publisher=cast(Any, pub),
    )
    publish_new_disagreements(
        _ledger(("a", "contradicts")),
        data_dir=_run_dir(tmp_path, "12_45"),
        publisher=cast(Any, pub),
    )
    assert len(pub.sent) == 1
    assert (tmp_path / "optic_crosscheck_alert_state.json").is_file()
    publish_new_disagreements(
        _ledger(("a", "contradicts"), ("b", "contradicts")),
        data_dir=_run_dir(tmp_path, "13_00"),
        publisher=cast(Any, pub),
    )
    assert len(pub.sent) == 2
    assert "1 new disagreement(s)" in pub.sent[1]
    assert "token b " in pub.sent[1]


def test_cleared_disagreement_alerts_again_when_it_returns(tmp_path):
    pub = _Pub()
    for hhmm, rows in (("12_30", [("a", "")]), ("12_45", []), ("13_00", [("a", "")])):
        publish_new_disagreements(
            _ledger(*rows),
            data_dir=_run_dir(tmp_path, hhmm),
            publisher=cast(Any, pub),
        )
    assert len(pub.sent) == 2


def test_non_run_dir_keeps_state_inside_it(tmp_path):
    pub = _Pub()
    publish_new_disagreements(_ledger(("a", "")), data_dir=tmp_path, publisher=cast(Any, pub))
    assert (tmp_path / "optic_crosscheck_alert_state.json").is_file()
