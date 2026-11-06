/** Client-side Mapper Chat threads (localStorage). Not the server session bag. */

import { useEffect, useState } from "react";

export type ChatRole = "user" | "assistant" | "system";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  created_at: string;
  reply_buttons?: { id: string; label: string; send: string }[];
};

export type ChatThread = {
  id: string;
  title: string;
  updated_at: string;
  messages: ChatMessage[];
};

const PREFIX = "mapping-console-chat:";
const LIST_KEY = `${PREFIX}threads`;
const ACTIVE_KEY = `${PREFIX}active`;
const HEIGHT_KEY = `${PREFIX}height`;
const MAX_THREADS = 50;
const MAX_MSGS = 100;

export function readChatHeight(): number | null {
  try {
    const raw = Number.parseInt(localStorage.getItem(HEIGHT_KEY) ?? "", 10);
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  } catch {
    return null;
  }
}

export function writeChatHeight(px: number): void {
  try {
    localStorage.setItem(HEIGHT_KEY, String(Math.round(px)));
  } catch {
    // Private mode / quota — a height preference is not worth failing over.
  }
}

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  for (const fn of listeners) fn();
}

function readList(): ChatThread[] {
  try {
    const raw = localStorage.getItem(LIST_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatThread[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeList(threads: ChatThread[]) {
  const trimmed = threads
    .slice()
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, MAX_THREADS)
    .map((t) => ({
      ...t,
      messages: t.messages.slice(-MAX_MSGS),
    }));
  localStorage.setItem(LIST_KEY, JSON.stringify(trimmed));
  notify();
}

function newId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
}

export function subscribeChat(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function listThreads(): ChatThread[] {
  return readList();
}

export function getActiveThreadId(): string | null {
  return localStorage.getItem(ACTIVE_KEY);
}

export function setActiveThreadId(id: string | null) {
  if (id) localStorage.setItem(ACTIVE_KEY, id);
  else localStorage.removeItem(ACTIVE_KEY);
  notify();
}

export function getThread(id: string): ChatThread | null {
  return readList().find((t) => t.id === id) ?? null;
}

export function ensureActiveThread(): ChatThread {
  const active = getActiveThreadId();
  if (active) {
    const existing = getThread(active);
    if (existing) return existing;
  }
  return createThread();
}

export function createThread(title = "New chat"): ChatThread {
  const thread: ChatThread = {
    id: newId("conv"),
    title,
    updated_at: new Date().toISOString(),
    messages: [],
  };
  writeList([thread, ...readList()]);
  setActiveThreadId(thread.id);
  return thread;
}

export function renameThread(id: string, title: string) {
  const threads = readList().map((t) =>
    t.id === id
      ? { ...t, title: title.trim() || t.title, updated_at: new Date().toISOString() }
      : t,
  );
  writeList(threads);
}

export function deleteThread(id: string) {
  const next = readList().filter((t) => t.id !== id);
  writeList(next);
  if (getActiveThreadId() === id) {
    setActiveThreadId(next[0]?.id ?? null);
  }
}

export function appendMessage(
  threadId: string,
  msg: Omit<ChatMessage, "id" | "created_at"> & { id?: string },
): ChatMessage {
  const full: ChatMessage = {
    id: msg.id ?? newId("msg"),
    role: msg.role,
    content: msg.content,
    created_at: new Date().toISOString(),
    reply_buttons: msg.reply_buttons,
  };
  const threads = readList().map((t) => {
    if (t.id !== threadId) return t;
    const title =
      t.messages.length === 0 && msg.role === "user"
        ? msg.content.trim().slice(0, 48) || t.title
        : t.title;
    return {
      ...t,
      title,
      updated_at: full.created_at,
      messages: [...t.messages, full].slice(-MAX_MSGS),
    };
  });
  writeList(threads);
  return full;
}

export function useChatStore(): {
  threads: ChatThread[];
  activeId: string | null;
  active: ChatThread | null;
} {
  const [, setTick] = useState(0);
  useEffect(() => subscribeChat(() => setTick((n) => n + 1)), []);
  const threads = listThreads();
  const activeId = getActiveThreadId();
  const active = activeId ? (threads.find((t) => t.id === activeId) ?? null) : null;
  return { threads, activeId, active };
}
