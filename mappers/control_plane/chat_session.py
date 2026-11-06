"""In-process Mapper Chat session bag (V0/V1; Redis when replicas > 1)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mappers.control_plane.chat_pending import Pending

_HOT_TTL_SEC = 30 * 60
_MAX_CONVOS = 50
_SUMMARY_MAX = 160


@dataclass
class ChatSession:
    """Per-conversation bag: pending confirms, evidence, compact focus."""

    conversation_id: str
    updated_at: float = field(default_factory=time.time)
    turns: list[dict[str, str]] = field(default_factory=list)
    pending: Pending | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    answered_turns: int = 0
    last_skill: str = ""
    last_slots: dict[str, Any] = field(default_factory=dict)
    last_verdict: str = ""
    last_kind: str = ""
    summary: str = ""

    def cool(self) -> None:
        """Drop hot turn state; keep last skill, slots, verdict, summary.

        Staged cart lines outlive the idle window — a trader who steps away
        should not lose pins they already queued.
        """
        from mappers.control_plane.chat_pending import PendingCart, PendingSkill, get_pending

        kept = None
        pending = get_pending(self)
        if isinstance(pending, (PendingCart, PendingSkill)) and (
            pending.cart_items or pending.awaiting_ignore_flip
        ):
            kept = PendingCart(
                cart_items=list(pending.cart_items),
                awaiting_ignore_flip=list(pending.awaiting_ignore_flip),
            )
        self.turns = []
        self.pending = kept
        self.evidence = []
        self.answered_turns = 0

    def has_focus(self) -> bool:
        """True when a completed skill left a subject we can resume."""
        return bool(self.last_skill and any(self.last_slots.values()))

    def worth_keeping(self) -> bool:
        """True when eviction would lose work: resumable focus or a staged cart."""
        from mappers.control_plane.chat_pending import staged_cart_items

        return self.has_focus() or bool(staged_cart_items(self))

    def remember(
        self,
        *,
        skill: str,
        slots: dict[str, Any],
        verdict: str = "",
        kind: str = "",
        message: str = "",
    ) -> None:
        """Keep compact focus after a successful skill turn."""
        self.last_skill = skill
        self.last_slots = dict(slots)
        self.last_verdict = verdict
        self.last_kind = kind
        self.summary = _one_line(message, self.last_slots, verdict)


def _one_line(message: str, slots: dict[str, Any], verdict: str) -> str:
    """Deterministic one-line recap for compact focus."""
    subject = _slot_subject(slots)
    head = " ".join(message.split())[:80]
    if subject and verdict:
        text = f"{head} → {subject} ({verdict})"
    elif subject:
        text = f"{head} → {subject}"
    elif verdict:
        text = f"{head} → {verdict}"
    else:
        text = head
    return text[:_SUMMARY_MAX]


def _slot_subject(slots: dict[str, Any]) -> str:
    for key in ("other", "kalshi", "crypto", "league", "subject"):
        value = str(slots.get(key) or "").strip()
        if value:
            return value
    return ""


class ChatSessionBag:
    """Process-local map keyed by conversation_id.

    Idle 30 minutes cools hot state (pending / turns). Compact focus lives
    until the 50-conversation cap evicts the oldest bag.
    """

    def __init__(self, *, ttl_sec: int = _HOT_TTL_SEC, max_convos: int = _MAX_CONVOS) -> None:
        self._hot_ttl = ttl_sec
        self._max = max_convos
        self._lock = threading.Lock()
        self._bags: dict[str, ChatSession] = {}

    def get_or_create(self, conversation_id: str) -> ChatSession:
        """Return an existing bag or mint a fresh one."""
        now = time.time()
        with self._lock:
            self._purge_unlocked(now)
            bag = self._bags.get(conversation_id)
            if bag is None:
                bag = ChatSession(conversation_id=conversation_id)
                self._bags[conversation_id] = bag
                self._trim_unlocked()
            bag.updated_at = now
            return bag

    def touch(self, bag: ChatSession) -> None:
        """Refresh idle clock after a turn."""
        with self._lock:
            bag.updated_at = time.time()

    def clear(self) -> None:
        """Drop all bags (tests)."""
        with self._lock:
            self._bags.clear()

    def _purge_unlocked(self, now: float) -> None:
        drop: list[str] = []
        for key, bag in self._bags.items():
            if now - bag.updated_at <= self._hot_ttl:
                continue
            bag.cool()
            # cool() deliberately keeps staged pins; do not delete them here.
            if not bag.worth_keeping():
                drop.append(key)
        for key in drop:
            del self._bags[key]

    def _trim_unlocked(self) -> None:
        if len(self._bags) <= self._max:
            return
        ordered = sorted(self._bags.items(), key=lambda kv: kv[1].updated_at)
        for key, _ in ordered[: len(self._bags) - self._max]:
            del self._bags[key]


_BAG = ChatSessionBag()


def session_bag() -> ChatSessionBag:
    """Process singleton session bag."""
    return _BAG
