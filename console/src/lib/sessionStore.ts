/** sessionStorage access that is safe in SSR, private mode, and tests. */

export function sessionStore(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

export function readSessionItem(key: string): string | null {
  const store = sessionStore();
  if (!store || !key) return null;
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

export function writeSessionItem(key: string, value: string): void {
  const store = sessionStore();
  if (!store || !key) return;
  try {
    store.setItem(key, value);
  } catch {
    // Quota or private-mode — keep working in memory.
  }
}

export function removeSessionItem(key: string): void {
  const store = sessionStore();
  if (!store || !key) return;
  try {
    store.removeItem(key);
  } catch {
    // ignore
  }
}
