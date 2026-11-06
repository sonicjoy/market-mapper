"""Compact session focus survives the 30-minute hot cool until the 50-cap trim."""

from __future__ import annotations

import time

from mappers.control_plane.chat_pending import PendingSkill
from mappers.control_plane.chat_session import ChatSessionBag


def test_hot_ttl_keeps_focus() -> None:
    bag = ChatSessionBag(ttl_sec=1, max_convos=10)
    session = bag.get_or_create("conv_a")
    session.remember(
        skill="probe_gap",
        slots={"other": "itf-cagnina-preda-2026-09-07"},
        verdict="expected_residual",
        kind="unmapped",
        message="do we map itf-cagnina-preda-2026-09-07",
    )
    session.pending = PendingSkill(skill="probe_gap")
    session.turns = [{"role": "user", "content": "do we map"}]
    session.updated_at = time.time() - 2
    again = bag.get_or_create("conv_a")
    assert again.last_skill == "probe_gap"
    assert again.last_slots["other"] == "itf-cagnina-preda-2026-09-07"
    assert again.last_verdict == "expected_residual"
    assert "itf-cagnina-preda-2026-09-07" in again.summary
    assert again.pending is None
    assert again.turns == []


def test_hot_ttl_drops_bags_without_focus() -> None:
    bag = ChatSessionBag(ttl_sec=1, max_convos=10)
    session = bag.get_or_create("empty")
    session.updated_at = time.time() - 2
    bag.get_or_create("other")
    fresh = bag.get_or_create("empty")
    assert fresh.last_skill == ""
    assert fresh.summary == ""


def test_cap_evicts_oldest_including_focus() -> None:
    now = time.time()
    bag = ChatSessionBag(ttl_sec=3600, max_convos=2)
    first = bag.get_or_create("old")
    first.remember(skill="probe_gap", slots={"other": "keep-me"}, message="probe")
    first.updated_at = now - 20
    bag.get_or_create("mid").updated_at = now - 10
    bag.get_or_create("new")
    revived = bag.get_or_create("old")
    assert revived.last_skill == ""
    assert revived.last_slots == {}
