import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { postChatWithFallback } from "../api";
import { applyChatUiActions } from "../chatActions";
import {
  appendMessage,
  createThread,
  deleteThread,
  ensureActiveThread,
  readChatHeight,
  setActiveThreadId,
  useChatStore,
  writeChatHeight,
} from "../chatStore";
import { useCart } from "../cartStore";
import { getConsoleSnapshot, publishCartItems } from "../consoleView";
import { ChatMarkdown } from "./ChatMarkdown";

const MIN_HEIGHT = 96;
const DEFAULT_HEIGHT = 160;
const KEY_STEP = 24;

function openingHint(message: string): string {
  const text = message.trim();
  if (/\b(fix|harvest)\s+(the\s+)?gaps\b/i.test(text)) {
    return "Gap pins land in Proposed after each mapper tick…";
  }
  if (/\b(sweep|harvest)\b/i.test(text) && /\bcrypto/i.test(text)) {
    return "Sweeping crypto.com team ids…";
  }
  if (/\bNX\.F\./i.test(text) || /\bKX[A-Z0-9-]/i.test(text)) {
    return "Probing live catalogue…";
  }
  return "Working…";
}

/** Keep the transcript between a usable minimum and most of the viewport. */
function clampHeight(px: number): number {
  const max = Math.max(MIN_HEIGHT, Math.round(window.innerHeight * 0.85));
  return Math.min(max, Math.max(MIN_HEIGHT, Math.round(px)));
}

export function AgentChat() {
  const location = useLocation();
  const navigate = useNavigate();
  const cart = useCart();
  const { threads, activeId, active } = useChatStore();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [status, setStatus] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [agentAvailable, setAgentAvailable] = useState<boolean | null>(null);
  const [height, setHeight] = useState(() => readChatHeight() ?? DEFAULT_HEIGHT);
  const bottomRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const heightRef = useRef(height);

  useEffect(() => {
    ensureActiveThread();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages.length, sending, streaming, status, height]);

  useEffect(() => {
    if (!sending) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [sending]);

  function applyHeight(px: number) {
    const next = clampHeight(px);
    heightRef.current = next;
    setHeight(next);
  }

  function startDrag(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    dragRef.current = { startY: e.clientY, startHeight: heightRef.current };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onDrag(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    applyHeight(drag.startHeight + (drag.startY - e.clientY));
  }

  function endDrag(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    dragRef.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
    writeChatHeight(heightRef.current);
  }

  function onHandleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const step = e.key === "ArrowUp" ? KEY_STEP : e.key === "ArrowDown" ? -KEY_STEP : 0;
    if (step === 0) return;
    e.preventDefault();
    applyHeight(heightRef.current + step);
    writeChatHeight(heightRef.current);
  }

  useEffect(() => {
    publishCartItems(cart);
  }, [cart]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    const thread = ensureActiveThread();
    setDraft("");
    appendMessage(thread.id, { role: "user", content: trimmed });
    setSending(true);
    setStreaming("");
    setStatus(openingHint(trimmed));
    try {
      const view = getConsoleSnapshot();
      const page_context = {
        path: location.pathname,
        tab: view.tab ?? view.entry.tab,
        entry: view.entry,
        rules: view.rules,
        coverage: view.coverage,
        unmapped: view.unmapped,
        cart: view.cart,
        cart_ids: cart.map((c) => c.id),
        conversation_id: thread.id,
        review_ref: view.review_ref ?? "",
      };
      const res = await postChatWithFallback(
        {
          message: trimmed,
          conversation_id: thread.id,
          page_context,
        },
        (chunk) => setStreaming((prev) => prev + chunk),
        (text) => setStatus(text),
      );
      setAgentAvailable(res.agent_available !== false);
      setStreaming("");
      appendMessage(thread.id, {
        role: "assistant",
        content: res.reply_markdown || "(empty reply)",
        reply_buttons: res.reply_buttons,
      });
      applyChatUiActions(res.ui_actions, (to, opts) => {
        void navigate(to, opts);
      });
    } catch (err) {
      setAgentAvailable(false);
      setStreaming("");
      appendMessage(thread.id, {
        role: "assistant",
        content:
          err instanceof Error
            ? `Agent unavailable: ${err.message}`
            : "Agent unavailable.",
      });
    } finally {
      setSending(false);
      setStatus("");
    }
  }

  return (
    <div className="relative border-t border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize chat"
        tabIndex={0}
        title="Drag to resize (double-click to reset)"
        className="group absolute -top-1 left-0 right-0 z-30 flex h-2 cursor-row-resize items-center justify-center focus:outline-none"
        onPointerDown={startDrag}
        onPointerMove={onDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={() => {
          applyHeight(DEFAULT_HEIGHT);
          writeChatHeight(DEFAULT_HEIGHT);
        }}
        onKeyDown={onHandleKeyDown}
      >
        <span className="h-1 w-10 rounded-full bg-slate-200 group-hover:bg-brand-400 group-focus:bg-brand-400 dark:bg-slate-700" />
      </div>

      {drawerOpen ? (
        <div className="absolute bottom-full left-0 right-0 z-20 mb-0 flex max-h-72 w-full max-w-full flex-col border border-b-0 border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
          <div className="border-b border-slate-100 px-3 py-2 dark:border-slate-800">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Chats
            </span>
          </div>
          <ul className="min-h-0 flex-1 overflow-auto p-1">
            {threads.map((t) => (
              <li key={t.id} className="flex items-start gap-1">
                <button
                  type="button"
                  className={`min-w-0 flex-1 break-words rounded px-2 py-1.5 text-left text-sm ${
                    t.id === activeId
                      ? "bg-brand-50 font-medium text-brand-900 dark:bg-brand-950/60 dark:text-brand-100"
                      : "text-slate-700 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                  onClick={() => {
                    setActiveThreadId(t.id);
                    setDrawerOpen(false);
                  }}
                >
                  {t.title}
                </button>
                <button
                  type="button"
                  className="shrink-0 px-1 text-xs text-slate-400 hover:text-red-600"
                  title="Delete"
                  onClick={() => deleteThread(t.id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-1.5 dark:border-slate-800">
        <button
          type="button"
          className="btn-ghost text-xs"
          onClick={() => setDrawerOpen((o) => !o)}
        >
          {drawerOpen ? "Hide chats" : "Chats ▸"}
        </button>
        <button
          type="button"
          className="btn-ghost text-xs"
          onClick={() => createThread()}
        >
          New
        </button>
        <span className="truncate text-xs text-slate-500 dark:text-slate-400">
          {active?.title ?? "New chat"}
        </span>
        {agentAvailable === false ? (
          <span className="ml-auto shrink-0 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-800 dark:bg-amber-950/60 dark:text-amber-200">
            Agent unavailable
          </span>
        ) : null}
      </div>

      <div className="overflow-auto px-3 py-2 text-sm" style={{ height }}>
        {(active?.messages ?? []).length === 0 ? (
          <p className="text-xs text-slate-400">
            Ask about mappings, aliases, or leagues. Coverage and Unmapped Why
            are the Explore pages; pins confirm into the cart.
          </p>
        ) : (
          (active?.messages ?? []).map((m) => (
            <div
              key={m.id}
              className={`mb-2 ${
                m.role === "user" ? "whitespace-pre-wrap text-slate-900 dark:text-slate-100" : "text-slate-600 dark:text-slate-300"
              }`}
            >
              <span className="mr-1 text-[10px] font-semibold uppercase text-slate-400">
                {m.role === "user" ? "You" : "Agent"}
              </span>
              {m.role === "user" ? m.content : <ChatMarkdown text={m.content} />}
              {m.reply_buttons && m.reply_buttons.length > 0 ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {m.reply_buttons.map((b) => (
                    <button
                      key={b.id}
                      type="button"
                      className="btn-ghost text-xs"
                      disabled={sending}
                      onClick={() => void send(b.send)}
                    >
                      {b.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ))
        )}
        {sending ? (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            <span
              className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-sky-500 align-middle"
              aria-hidden
            />
            <span className="whitespace-pre-wrap align-middle text-slate-600 dark:text-slate-300">
              {streaming || status || "Working…"}
            </span>
            {elapsed > 0 ? <span className="align-middle text-slate-400"> {elapsed}s</span> : null}
          </p>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <form
        className="flex gap-2 border-t border-slate-100 px-3 py-2 dark:border-slate-800"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <input
          className="input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Message the mapping agent…"
          disabled={sending}
        />
        <button type="submit" className="btn-primary shrink-0" disabled={sending || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
