/**
 * Detects a submit that died in transit rather than being rejected.
 *
 * Submit runs propose + validate server-side; when that outlives the gateway
 * timeout the browser sees a 502/504 or a dead socket even though the card was
 * created. Treat these as "unknown outcome" and point the trader at Review
 * instead of at a retry that used to mint a duplicate.
 */
export function isGatewayDrop(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /HTTP 502|HTTP 503|HTTP 504|Failed to fetch|NetworkError|Load failed/i.test(msg);
}

export const GATEWAY_DROP_NOTE =
  "Submit timed out. Check Review — this change may already be waiting.";
