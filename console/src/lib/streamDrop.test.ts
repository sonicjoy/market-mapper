import { describe, expect, it } from "vitest";

import { isStreamDrop } from "./streamDrop";

describe("isStreamDrop", () => {
  it("matches Chromium mid-stream reset copy", () => {
    expect(isStreamDrop(new Error("network error"))).toBe(true);
    expect(isStreamDrop(new Error("Failed to fetch"))).toBe(true);
    expect(isStreamDrop(new Error("stream ended without final event"))).toBe(true);
  });

  it("leaves application errors alone", () => {
    expect(isStreamDrop(new Error("HTTP 400"))).toBe(false);
    expect(isStreamDrop(new Error("unknown_tool"))).toBe(false);
  });
});
