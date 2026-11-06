/** Browser / gateway resets of an open SSE body. */
const STREAM_DROP =
  /HTTP 502|HTTP 503|HTTP 504|Failed to fetch|NetworkError|network error|Load failed|stream ended without final/i;

export function isStreamDrop(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return STREAM_DROP.test(msg);
}
