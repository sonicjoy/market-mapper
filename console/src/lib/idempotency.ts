import { useRef } from "react";

/**
 * Stable key for one submit intent.
 *
 * The form submits have no preview token to derive an idempotency key from, so
 * the client supplies one. Retries after a gateway timeout reuse the key and
 * the server returns the existing review card; a fresh key is only minted once
 * the previous intent has been resolved.
 */
export function useIdempotencyKey() {
  const ref = useRef<string | null>(null);
  return {
    current(): string {
      ref.current ??= crypto.randomUUID();
      return ref.current;
    },
    reset(): void {
      ref.current = null;
    },
  };
}
