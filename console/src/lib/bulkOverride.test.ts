import { describe, expect, it } from "vitest";

import { confirmedPair, selectionKey, selectionLabel, type DraftPair, type OpticSelection } from "../bulkOverrideApi";
import { defaultChoice, pairKey, rowOptions } from "../components/BulkPairTable";

function sel(selection: string, extra: Partial<OpticSelection> = {}): OpticSelection {
  return {
    game_id: "g1",
    market_id: "moneyline",
    market: "Moneyline",
    selection,
    selection_line: "",
    points: 0,
    selection_points: 0,
    grouping_key: "default",
    ...extra,
  };
}

function pair(status: DraftPair["status"], target: OpticSelection | null, alternatives: OpticSelection[] = []): DraftPair {
  return {
    source_market_id: "KXNHLGAME-26SEP26ANALA-LA",
    source_selection_id: "yes",
    leg_name: "LA",
    status,
    reason: "",
    target,
    alternatives,
  };
}

describe("bulk override helpers", () => {
  it("pre-ticks only confident pairs", () => {
    expect(defaultChoice(pair("confident", sel("Los Angeles Kings"))).include).toBe(true);
    expect(defaultChoice(pair("review", sel("Los Angeles Kings"))).include).toBe(false);
    expect(defaultChoice(pair("ambiguous", null))).toEqual({ include: false, targetKey: "" });
  });

  it("lists the draft target first, then alternatives, then the rest of the market, deduped", () => {
    const kings = sel("Los Angeles Kings");
    const ducks = sel("Anaheim Ducks");
    const options = rowOptions(pair("review", kings, [ducks]), [ducks, kings]);
    expect(options.map((o) => o.selection)).toEqual(["Los Angeles Kings", "Anaheim Ducks"]);
  });

  it("builds the publish row from the chosen Optic selection", () => {
    const total = sel("", { market_id: "total_goals", selection_line: "over", points: 5.5 });
    expect(confirmedPair(pair("confident", total), total)).toEqual({
      source_market_id: "KXNHLGAME-26SEP26ANALA-LA",
      source_selection_id: "yes",
      game_id: "g1",
      market_id: "total_goals",
      selection: "",
      selection_line: "over",
      points: 5.5,
      selection_points: 0,
      grouping_key: "default",
    });
    expect(selectionLabel(total)).toBe("over +5.5");
    expect(selectionKey(total)).toBe("total_goals||over|5.5|default");
    expect(pairKey(pair("confident", total))).toBe("KXNHLGAME-26SEP26ANALA-LA|yes");
  });
});
