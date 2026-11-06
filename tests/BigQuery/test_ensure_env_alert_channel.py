"""infra/ensure_env.sh pins the test VM's alert channel; prod keeps its own."""

import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "ensure_env.sh"


def _run(tmp_path: Path, env_text: str) -> str:
    (tmp_path / "infra").mkdir()
    shutil.copy(_SCRIPT, tmp_path / "infra" / "ensure_env.sh")
    (tmp_path / ".env").write_text(env_text)
    subprocess.run(["bash", str(tmp_path / "infra" / "ensure_env.sh")], check=True,
                   capture_output=True)
    return (tmp_path / ".env").read_text()


@pytest.mark.parametrize("before", ["", "ALERT_SLACK_CHANNEL=#marketmaking-mapping-alerts\n"])
def test_test_project_is_pinned_to_test_channel(tmp_path, before):
    out = _run(tmp_path, "GCP_PROJECT=marketmaking-test\n" + before)
    assert "ALERT_SLACK_CHANNEL=#mm-test-app-alerts\n" in out
    assert "#marketmaking-mapping-alerts" not in out


def test_prod_project_keeps_operator_channel(tmp_path):
    out = _run(tmp_path,
               "GCP_PROJECT=rs-marketmaking\nALERT_SLACK_CHANNEL=#marketmaking-mapping-alerts\n")
    assert "ALERT_SLACK_CHANNEL=#marketmaking-mapping-alerts\n" in out


def test_stx_fetch_is_demo_direct_on_test_and_production_via_toronto_proxy_on_prod(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "p").mkdir()
    test_out = _run(tmp_path / "t", "GCP_PROJECT=marketmaking-test\n")
    prod_out = _run(tmp_path / "p", "GCP_PROJECT=rs-marketmaking\n")
    assert "STX_ENV=demo\n" in test_out and "STX_HTTPS_PROXY" not in test_out
    assert "STX_ENV=prod\n" in prod_out and "STX_REGION=ontario\n" in prod_out
    assert "STX_HTTPS_PROXY=http://34.130.95.249:3128\n" in prod_out
