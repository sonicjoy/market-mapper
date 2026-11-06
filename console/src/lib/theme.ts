/** Console color scheme: Auto follows the OS, Light/Dark are sticky overrides. */

import { useEffect, useState } from "react";

export type ThemeMode = "auto" | "light" | "dark";

const STORAGE_KEY = "mapping-console-theme";
const ORDER: ThemeMode[] = ["auto", "light", "dark"];

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  for (const fn of listeners) fn();
}

function parseTheme(raw: string | null): ThemeMode {
  if (raw === "light" || raw === "dark" || raw === "auto") return raw;
  return "auto";
}

export function readTheme(): ThemeMode {
  try {
    return parseTheme(localStorage.getItem(STORAGE_KEY));
  } catch {
    return "auto";
  }
}

function prefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolvedDark(mode: ThemeMode): boolean {
  return mode === "dark" || (mode === "auto" && prefersDark());
}

export function applyTheme(mode: ThemeMode): void {
  document.documentElement.classList.toggle("dark", resolvedDark(mode));
}

let mode: ThemeMode = typeof window !== "undefined" ? readTheme() : "auto";

if (typeof document !== "undefined") {
  applyTheme(mode);
}

export function setTheme(next: ThemeMode): void {
  mode = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Private mode / quota — theme preference is not worth failing over.
  }
  applyTheme(next);
  notify();
}

export function cycleTheme(current: ThemeMode): ThemeMode {
  return ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
}

export function bootTheme(): () => void {
  mode = readTheme();
  applyTheme(mode);
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onSystem = () => {
    if (mode === "auto") applyTheme("auto");
  };
  mq.addEventListener("change", onSystem);
  return () => mq.removeEventListener("change", onSystem);
}

export function useTheme(): ThemeMode {
  const [current, setCurrent] = useState(mode);
  useEffect(() => {
    const listener = () => setCurrent(mode);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return current;
}
