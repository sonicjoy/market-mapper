"""Suite C — live model parity (opt-in; requires MAPPING_CP_CHAT_API_KEY).

Runs the Suite A/B fixtures against the configured Flash model and one stronger
model. Because the playbook lives in Python, `path`, `outcome`, `verdict`,
`ui_action_types`, and staged kinds must match exactly; narration may differ.

    $env:MAPPING_CP_CHAT_API_KEY="..."
    $env:MAPPING_CP_CHAT_EVAL_MODEL="gemini-2.5-pro"
    python -m pytest tests/control_plane/chat_skills/test_eval_live.py -q
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_tip_cache import clear_tip_league_cache
from tests.control_plane.chat_skills.harness import load_fixture, run_turn
from tests.control_plane.chat_skills.test_eval_routing import SUITES

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAPPING_CP_CHAT_API_KEY"),
    reason="live chat eval requires MAPPING_CP_CHAT_API_KEY",
)

_ALL: list[dict[str, Any]] = [row for name in SUITES for row in load_fixture(name)]
_IDS = [str(r["id"]) for r in _ALL]


def _observe(row: dict[str, Any], model: str) -> dict[str, Any]:
    session_bag().clear()
    clear_tip_league_cache()
    rec = run_turn(
        row["message"],
        page=row.get("page"),
        conversation_id=f"{row['id']}-{model}",
        stubs=row.get("stubs"),
        chat_provider="gemini",
        chat_model=model,
    )
    staged = cart_items(session_bag().get_or_create(f"{row['id']}-{model}"))
    return {
        "path": rec.path,
        "outcome": rec.outcome,
        "verdict": rec.verdict,
        "ui_action_types": sorted(set(rec.ui_action_types)),
        "staged_kinds": sorted({str(i.get("kind") or "") for i in staged}),
    }


@pytest.mark.parametrize("row", _ALL, ids=_IDS)
def test_flash_matches_a_stronger_model(row: dict[str, Any]) -> None:
    flash = os.environ.get("MAPPING_CP_CHAT_MODEL", "gemini-2.5-flash")
    strong = os.environ.get("MAPPING_CP_CHAT_EVAL_MODEL")
    if not strong:
        pytest.skip("set MAPPING_CP_CHAT_EVAL_MODEL to compare against a stronger model")
    assert _observe(row, flash) == _observe(row, strong), row["id"]
