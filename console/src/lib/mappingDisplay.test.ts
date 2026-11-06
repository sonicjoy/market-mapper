import { describe, expect, it } from "vitest";

import {
  readableAliasSourceName,
  readableAliasSourceSubline,
  readableAliasTargetSubline,
  isOpticMapping,
  opticIdentityEvidence,
} from "./mappingDisplay";

describe("readableAliasSourceName", () => {
  it("shows the mapped pin, not the Optic target", () => {
    expect(
      readableAliasSourceName({
        kind: "alias",
        source: { name: "Missouri", code: "MIZZ", alias_kind: "code" },
        target: { name: "Missouri" },
      }),
    ).toBe("MIZZ");
    expect(
      readableAliasSourceName({
        kind: "alias",
        source: { name: "benshe", code: "benshe" },
        target: { name: "Ben Shelton" },
      }),
    ).toBe("benshe");
  });

  it("uses a human label when the pin is an opaque id", () => {
    expect(
      readableAliasSourceName({
        kind: "alias",
        source: {
          name: "Ben Shelton",
          code: "167522086300",
          alias_kind: "external_id",
        },
        target: { name: "Ben Shelton" },
      }),
    ).toBe("Ben Shelton");
  });

  it("does not use a crypto @ matchup title as the source name", () => {
    expect(
      readableAliasSourceName({
        kind: "alias",
        source: {
          name: "Thomas Faurel @ Dusan Obradovic",
          code: "1098193",
          alias_kind: "external_id",
        },
        target: { name: "Dusan Obradovic" },
      }),
    ).toBe("1098193");
  });

  it("shows a multi-word Kalshi outcome instead of a short code", () => {
    expect(
      readableAliasSourceName({
        kind: "alias",
        source: {
          name: "Daniel Milavsky",
          code: "MIL",
          alias_kind: "code",
        },
        target: { name: "Yanaki Milev" },
      }),
    ).toBe("Daniel Milavsky");
  });

  it("keeps a name-kind pin so Source and Target can be compared", () => {
    expect(
      readableAliasSourceName({
        kind: "alias",
        source: {
          name: "Veldman Klara",
          code: "Klara Veldman",
          alias_kind: "name",
        },
        target: { name: "Veldman Klara" },
      }),
    ).toBe("Klara Veldman");
  });
});

describe("readableAliasSourceSubline", () => {
  it("labels polymarket name and slug separately", () => {
    expect(
      readableAliasSourceSubline({
        kind: "alias",
        source: {
          platform: "Polymarket",
          code: "Barbados Tridents",
          alias_kind: "name",
          slug: "cpl-brb-vs-ttk-2026-09-04",
        },
      }),
    ).toBe("Polymarket · name: Barbados Tridents · slug: cpl-brb-vs-ttk-2026-09-04");
  });

  it("labels crypto.com pins with crypto_id", () => {
    expect(
      readableAliasSourceSubline({
        kind: "alias",
        source: {
          platform: "crypto.com",
          code: "NX.F.OPT.CPL-1-260904",
          alias_kind: "crypto_id",
        },
      }),
    ).toBe("crypto.com · crypto_id: NX.F.OPT.CPL-1-260904");
  });

  it("keeps the Kalshi ticker and event title together", () => {
    expect(
      readableAliasSourceSubline({
        kind: "alias",
        source: {
          platform: "Kalshi",
          name: "MIZZ",
          code: "MIZZ",
          alias_kind: "code",
          description: "Missouri vs Arkansas Pine Bluff",
        },
      }),
    ).toBe("Kalshi · code: MIZZ · Missouri vs Arkansas Pine Bluff");
  });

  it("adds Optic abbr when it differs from the pin", () => {
    expect(
      readableAliasSourceSubline({
        kind: "alias",
        source: {
          platform: "Optic",
          name: "Dane Sweeny",
          code: "4E10DF885122",
          alias_kind: "external_id",
          abbr: "SWE",
        },
      }),
    ).toBe("Optic · external_id: 4E10DF885122 · Dane Sweeny · abbr SWE");
  });
});

describe("readableAliasTargetSubline", () => {
  it("shows code and a distinct Optic abbr", () => {
    expect(
      readableAliasTargetSubline({
        target: { platform: "Optic", code: "DSA5", abbr: "SWE" },
      }),
    ).toBe("Optic · DSA5 · abbr SWE");
  });

  it("does not repeat abbr when it matches the canonical code", () => {
    expect(
      readableAliasTargetSubline({
        target: { platform: "Optic", code: "CHE", abbr: "CHE" },
      }),
    ).toBe("Optic · CHE");
  });
});

describe("optic mapping helpers", () => {
  it("detects Optic-to-Optic alias rows", () => {
    expect(
      isOpticMapping({
        kind: "alias",
        sportsbook: "optic",
        source: { platform: "Optic" },
      }),
    ).toBe(true);
    expect(
      isOpticMapping({
        kind: "alias",
        sportsbook: "kalshi",
        source: { platform: "Kalshi" },
      }),
    ).toBe(false);
  });

  it("drops question/slug evidence from Optic identity refs", () => {
    expect(
      opticIdentityEvidence([
        "optic:competitor:4E10:Dane Sweeny",
        "optic:name:Dane Sweeny",
        "optic:fixture:fx1:Dane Sweeny vs Lorenzo Musetti (2026-09-03)",
        "optic:abbr:SWE",
        "polymarket:question:W15 Haren: Nina Kruijer vs Klara Veldman",
        "polymarket:slug:w15-haren",
      ]),
    ).toEqual([
      "optic:competitor:4E10:Dane Sweeny",
      "optic:name:Dane Sweeny",
      "optic:fixture:fx1:Dane Sweeny vs Lorenzo Musetti (2026-09-03)",
      "optic:abbr:SWE",
    ]);
  });
});
