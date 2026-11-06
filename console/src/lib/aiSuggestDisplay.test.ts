import { describe, expect, it } from "vitest";

import {
  AI_UNIQUE_BIND_NOTE,
  mappingEvidenceView,
  mappingRowWarnings,
  normalizeAiNoteRef,
  skipReasonDescription,
} from "./aiSuggestDisplay";

describe("mappingEvidenceView", () => {
  it("drops the suggest marker, warns on the AI note, and explains name_ambiguous", () => {
    const view = mappingEvidenceView(
      [
        "ai:suggest",
        "ai:skip:name_ambiguous",
        "AI suggestion — unique-bind did not apply; human must Approve.",
        "ai:needle:Santos FC",
        "optic:competitor:oid:Santos FC Sao Paulo",
      ],
      "Santos FC",
      "Santos FC Sao Paulo",
    );
    expect(view.warnings).toEqual([AI_UNIQUE_BIND_NOTE, "Unsure if Santos FC actually is Santos FC Sao Paulo."]);
    expect(view.items).toEqual([
      "AI searched for: Santos FC",
      "Optic competitor: Santos FC Sao Paulo (oid)",
    ]);
    expect(view.items.join(" ")).not.toMatch(/Suggest: suggest|Needle:/i);
  });

  it("explains collision and name_mismatch skips", () => {
    expect(skipReasonDescription("collision", "CA Mineiro", "Clube Atlético Mineiro")).toBe(
      "Another Optic owner collides with CA Mineiro; unsure if it is Clube Atlético Mineiro.",
    );
    expect(skipReasonDescription("name_mismatch", "Grêmio FBPA", "Grêmio FB Porto Alegrense")).toBe(
      "Grêmio FBPA does not match Grêmio FB Porto Alegrense closely enough.",
    );
    expect(skipReasonDescription("no_optic_canonical", "1HSPREAD", "1h_point_spread")).toBe(
      "No unique Optic market for 1HSPREAD; AI guessed 1h_point_spread.",
    );
  });

  it("collapses duplicate AI notes and drops harvest-only refs", () => {
    const view = mappingEvidenceView(
      [
        "ai:suggest",
        "ai:skip:no_optic_canonical",
        AI_UNIQUE_BIND_NOTE,
        `${AI_UNIQUE_BIND_NOTE} crypto player_prop`,
        "rfq_demand:14",
        "gap:Total Outs Recorded",
        "crypto.com:source_key:Total Outs Recorded",
      ],
      "Total Outs Recorded",
      "player_outs",
    );
    expect(view.warnings).toEqual([
      AI_UNIQUE_BIND_NOTE,
      "No unique Optic market for Total Outs Recorded; AI guessed player_outs.",
    ]);
    expect(view.items).toEqual([
      "Gap: Total Outs Recorded",
      "Source Key: Total Outs Recorded",
    ]);
    expect(normalizeAiNoteRef(`${AI_UNIQUE_BIND_NOTE} crypto player_prop`)).toBe(AI_UNIQUE_BIND_NOTE);
  });

  it("keeps guess reasons in the warning list", () => {
    const warnings = mappingRowWarnings(
      { tier: "guess", reason: "close name", alternatives: [{ name: "Nancy" }] },
      [],
    );
    expect(warnings).toEqual(["close name", "runner-up Nancy"]);
  });
});
