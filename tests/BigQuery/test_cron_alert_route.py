"""VM cron-wrapper alerts take the mapping channel route, with the webhook as fallback.

The cron wrappers (Polymarket bridge, pipeline, raw stashes, ...) used to post
straight to the host's incoming webhook, which is bound to the trader channel,
while every other mmmapper alert went Pub/Sub -> relay -> ALERT_SLACK_CHANNEL.
send_cron_alert (infra/slack_webhook.sh) now tries the Pub/Sub route first via
``python -m BigQuery.alerts`` and only falls back to the webhook when that route
is not configured or the publish fails.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from BigQuery import alerts

REPO = Path(__file__).resolve().parents[2]


class _FakePublisher:
    def __init__(self, *, routable: bool, message_id: str | None) -> None:
        self.routable = routable
        self._message_id = message_id
        self.published: list[tuple[str, str]] = []
        self.closed = False

    def publish(self, severity: str, text: str) -> str | None:
        self.published.append((severity, text))
        return self._message_id

    def close(self) -> None:
        self.closed = True


def _run_main(monkeypatch, publisher: _FakePublisher, stdin: str) -> int:
    monkeypatch.setattr(alerts, "build_publisher", lambda: publisher)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return alerts.main(["--severity", "critical"])


def test_cli_publishes_stdin_when_routable(monkeypatch) -> None:
    publisher = _FakePublisher(routable=True, message_id="42")
    assert _run_main(monkeypatch, publisher, "*Polymarket bridge failed*\n") == 0
    assert publisher.published == [("critical", "*Polymarket bridge failed*")]
    assert publisher.closed


def test_cli_refuses_when_not_routable(monkeypatch) -> None:
    publisher = _FakePublisher(routable=False, message_id="42")
    assert _run_main(monkeypatch, publisher, "boom") == alerts.EXIT_NOT_ROUTABLE
    assert publisher.published == []
    assert publisher.closed


def test_cli_reports_a_failed_publish(monkeypatch) -> None:
    publisher = _FakePublisher(routable=True, message_id=None)
    assert _run_main(monkeypatch, publisher, "boom") == 1


def test_cli_refuses_empty_text(monkeypatch) -> None:
    publisher = _FakePublisher(routable=True, message_id="42")
    assert _run_main(monkeypatch, publisher, "  \n") == 1
    assert publisher.published == []


@pytest.mark.parametrize(
    ("enabled", "channel", "expected"),
    [
        (True, "#marketmaking-mapping-alerts", True),
        (True, "", False),
        (False, "#marketmaking-mapping-alerts", False),
    ],
)
def test_routable_needs_publishing_and_a_channel(enabled, channel, expected) -> None:
    # Built disabled so no Pub/Sub client is created, then flipped: routable
    # is a pure function of the enabled flag and the channel.
    publisher = alerts.AlertPublisher(enabled=False, project_id=None, topic_id="t", channel=channel)
    publisher._enabled = enabled
    assert publisher.routable is expected


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def cron_host(tmp_path: Path) -> dict[str, Path]:
    """A throwaway repo layout with a fake venv python and a fake curl."""
    repo = tmp_path / "mmmapper"
    (repo / "infra").mkdir(parents=True)
    shutil.copy(REPO / "infra" / "slack_webhook.sh", repo / "infra" / "slack_webhook.sh")
    (repo / ".env").write_text("ALERT_SLACK_CHANNEL=#marketmaking-mapping-alerts\n")

    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    _executable(
        venv_bin / "python",
        "#!/usr/bin/env bash\n"
        'echo "$ALERT_SLACK_CHANNEL" > "$FAKE_OUT/python_channel"\n'
        'echo "$*" > "$FAKE_OUT/python_args"\n'
        'cat > "$FAKE_OUT/python_stdin"\n'
        'exit "$FAKE_PYTHON_EXIT"\n',
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in -d) printf "%s" "$2" > "$FAKE_OUT/curl_body"; shift 2 ;;\n'
        '  *) last="$1"; shift ;; esac\n'
        "done\n"
        'echo "$last" > "$FAKE_OUT/curl_url"\n',
    )
    # macOS has no coreutils timeout; the VM does. Same contract either way.
    _executable(bin_dir / "timeout", '#!/usr/bin/env bash\nshift\nexec "$@"\n')

    home = tmp_path / "home"
    home.mkdir()
    (home / ".slack_webhook_url").write_text("https://hooks.example/T/B/X")

    out = tmp_path / "out"
    out.mkdir()
    return {"repo": repo, "bin": bin_dir, "home": home, "out": out, "log": tmp_path / "x.log"}


def _send(cron_host: dict[str, Path], python_exit: int) -> None:
    body = 'Traceback (most recent call last):\n  File "a.py", line 1\nHTTPError: 400 "Bad Request"'
    script = (
        f'. "{cron_host["repo"]}/infra/slack_webhook.sh"; '
        f'send_cron_alert critical "Polymarket bridge failed (exit 1)" \'{body}\' "{cron_host["log"]}"'
    )
    env = {
        **os.environ,
        "PATH": f"{cron_host['bin']}:{os.environ['PATH']}",
        "HOME": str(cron_host["home"]),
        "FAKE_OUT": str(cron_host["out"]),
        "FAKE_PYTHON_EXIT": str(python_exit),
    }
    env.pop("ALERT_SLACK_CHANNEL", None)
    subprocess.run(["bash", "-c", script], env=env, check=True)


def test_routable_host_publishes_and_skips_the_webhook(cron_host) -> None:
    _send(cron_host, python_exit=0)
    out = cron_host["out"]
    assert (out / "python_args").read_text().strip() == "-m BigQuery.alerts --severity critical"
    assert (out / "python_channel").read_text().strip() == "#marketmaking-mapping-alerts"
    text = (out / "python_stdin").read_text()
    assert text.startswith("*Polymarket bridge failed (exit 1)* on `")
    assert 'HTTPError: 400 "Bad Request"' in text
    assert not (out / "curl_body").exists()


@pytest.mark.parametrize("python_exit", [1, alerts.EXIT_NOT_ROUTABLE])
def test_unroutable_or_failed_publish_falls_back_to_the_webhook(cron_host, python_exit) -> None:
    _send(cron_host, python_exit=python_exit)
    out = cron_host["out"]
    assert (out / "curl_url").read_text().strip() == "https://hooks.example/T/B/X"
    payload = json.loads((out / "curl_body").read_text())
    assert payload["text"].startswith(":red_circle: *Polymarket bridge failed (exit 1)* on `")
    assert 'HTTPError: 400 "Bad Request"' in payload["text"]
    assert "\n```\nTraceback" in payload["text"]


def test_no_route_at_all_is_logged_not_silent(cron_host) -> None:
    (cron_host["home"] / ".slack_webhook_url").unlink()
    _send(cron_host, python_exit=alerts.EXIT_NOT_ROUTABLE)
    assert "no alert route" in cron_host["log"].read_text()
    assert not (cron_host["out"] / "curl_body").exists()


def test_every_cron_wrapper_alerts_through_the_shared_route() -> None:
    wrappers = sorted((REPO / "infra").glob("cron_*.sh"))
    alerting = [w for w in wrappers if "send_cron_alert" in w.read_text()]
    assert len(alerting) >= 9
    for wrapper in wrappers:
        source = wrapper.read_text()
        assert "WEBHOOK_URL" not in source, f"{wrapper.name} posts to the webhook directly"
        assert "curl " not in source, f"{wrapper.name} posts to Slack directly"
