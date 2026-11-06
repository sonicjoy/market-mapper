import { describe, expect, it } from "vitest";

import { displayEvidenceRef, evidenceLines, groupEvidenceCards } from "./evidenceCards";

const MLB_ALIASES = [
  "+ Map Optic 99DF68AB44BE → Washington Nationals (Mlb)",
  "+ Map Optic DDBDBB162990, Kalshi MIA → Miami Marlins (Mlb)",
  "+ Map Optic F146F7B07E72, Kalshi BAL → Baltimore Orioles (Mlb)",
  "+ Map Optic FE07CF8C473A, Kalshi TB → Tampa Bay Rays (Mlb)",
];

const MLB_EVIDENCE = [
  "optic:competitor:99DF68AB44BE",
  "optic:fixture:20260822EF750048",
  "optic:name:Washington Nationals",
  "optic:competitor:DDBDBB162990",
  "optic:name:Miami Marlins",
  "optic:competitor:FE07CF8C473A",
  "optic:fixture:2026082293B5A4FD",
  "optic:name:Tampa Bay Rays",
  "optic:competitor:F146F7B07E72",
  "optic:name:Baltimore Orioles",
  "note:pipeline gap-fix",
];

describe("groupEvidenceCards", () => {
  it("groups optic clusters onto alias cards and leaves notes shared", () => {
    const cards = groupEvidenceCards(MLB_EVIDENCE, MLB_ALIASES);
    expect(cards.map((card) => card.title)).toEqual([
      "Washington Nationals",
      "Miami Marlins",
      "Baltimore Orioles",
      "Tampa Bay Rays",
      "Notes",
    ]);
    expect(cards[0]?.refs).toEqual([
      "optic:competitor:99DF68AB44BE",
      "optic:fixture:20260822EF750048",
      "optic:name:Washington Nationals",
    ]);
    expect(cards[3]?.refs).toEqual([
      "optic:competitor:FE07CF8C473A",
      "optic:fixture:2026082293B5A4FD",
      "optic:name:Tampa Bay Rays",
    ]);
    expect(cards[4]).toEqual({
      title: "Notes",
      kind: "notes",
      refs: ["note:pipeline gap-fix"],
    });
  });

  it("keeps a single Kalshi pin titled when refs are only gap/title/fixture", () => {
    const cards = groupEvidenceCards(
      ["gap:KXBOXING-26AUG21SERRANMANZUR", "kalshi:title:Serrano vs  vs", "optic:fixture:fx-1"],
      ["Map Kalshi SERRAN → Amanda Serrano (Boxing matches)"],
    );
    expect(cards).toEqual([
      {
        title: "Amanda Serrano",
        kind: "alias",
        refs: [
          "gap:KXBOXING-26AUG21SERRANMANZUR",
          "kalshi:title:Serrano vs  vs",
          "optic:fixture:fx-1",
        ],
      },
    ]);
  });

  it("puts the same Kalshi event on both named sides, not a third pin", () => {
    const cards = groupEvidenceCards(
      [
        "gap:KXMLB-26AUG22MIABAL",
        "kalshi:title:Miami Marlins vs Baltimore Orioles",
        "optic:competitor:DDBDBB162990",
        "optic:name:Miami Marlins",
        "optic:competitor:F146F7B07E72",
        "optic:name:Baltimore Orioles",
      ],
      [
        "Map Optic DDBDBB162990, Kalshi MIA → Miami Marlins (Mlb)",
        "Map Optic F146F7B07E72, Kalshi BAL → Baltimore Orioles (Mlb)",
      ],
    );
    expect(cards.map((card) => [card.title, card.kind])).toEqual([
      ["Miami Marlins", "alias"],
      ["Baltimore Orioles", "alias"],
    ]);
    expect(cards[0]?.refs).toEqual([
      "gap:KXMLB-26AUG22MIABAL",
      "kalshi:title:Miami Marlins vs Baltimore Orioles",
      "optic:competitor:DDBDBB162990",
      "optic:name:Miami Marlins",
    ]);
    expect(cards[1]?.refs).toEqual([
      "gap:KXMLB-26AUG22MIABAL",
      "kalshi:title:Miami Marlins vs Baltimore Orioles",
      "optic:competitor:F146F7B07E72",
      "optic:name:Baltimore Orioles",
    ]);
  });

  it("keeps Kalshi Chile titles off an unrelated Maryland pin", () => {
    const cards = groupEvidenceCards(
      [
        "gap:KXCHLLDPGAME-26AUG31ULCDLS",
        "kalshi:title:Union La Calera vs Deportes La Serena",
        "kalshi:title:Will Union La Calera win the Chile Liga de Primera?",
        "kalshi:title:Will Deportes La Serena win the Chile Liga de Primera?",
        "kalshi:market:KXCHLLDP-26-ULC",
        "kalshi:market:KXCHLLDP-26-DLS",
        "optic:competitor:ULC-OID:Union La Calera",
        "optic:competitor:DLS-OID:Deportes La Serena",
        "optic:competitor:2D589316FED5:Maryland",
        "optic:name:Maryland",
      ],
      [
        "+ Map Optic ULC-OID (Union La Calera), Kalshi ULC → ULC4 Union La Calera (Chile Primera)",
        "+ Map Optic DLS-OID (Deportes La Serena), Kalshi DLS → DLS Deportes La Serena (Chile Primera)",
        "+ Map Optic 2D589316FED5 (Maryland), polymarket_usa mary → MD Maryland (Ncaaf)",
      ],
    );
    const byTitle = Object.fromEntries(cards.map((card) => [card.title, evidenceLines(card)]));
    expect(byTitle["ULC4 Union La Calera"]).toEqual([
      "Gap: KXCHLLDPGAME-26AUG31ULCDLS",
      "Kalshi: Union La Calera vs Deportes La Serena",
      "Kalshi: Will Union La Calera win the Chile Liga de Primera?",
      "Kalshi market: KXCHLLDP-26-ULC",
      "Optic competitor: Union La Calera (ULC-OID)",
    ]);
    expect(byTitle["DLS Deportes La Serena"]).toEqual([
      "Gap: KXCHLLDPGAME-26AUG31ULCDLS",
      "Kalshi: Union La Calera vs Deportes La Serena",
      "Kalshi: Will Deportes La Serena win the Chile Liga de Primera?",
      "Kalshi market: KXCHLLDP-26-DLS",
      "Optic competitor: Deportes La Serena (DLS-OID)",
    ]);
    expect(byTitle["MD Maryland"]).toEqual([
      "Polymarket US code: mary",
      "Polymarket US name: MD Maryland",
      "Optic competitor: Maryland (2D589316FED5)",
    ]);
    expect(byTitle["MD Maryland"]?.some((line) => line.startsWith("Kalshi"))).toBe(false);
    expect(byTitle["MD Maryland"]?.some((line) => line.startsWith("Gap:"))).toBe(false);
  });

  it("does not attach other State-school Kalshi titles", () => {
    const cards = groupEvidenceCards(
      [
        "kalshi:title:Robert Morris vs West Virginia State",
        "kalshi:title:Iowa State vs. Iowa",
        "optic:name:West Virginia State",
        "optic:name:Iowa State",
      ],
      [
        "+ Map Optic WVS4, Kalshi WVSU → West Virginia State (Ncaaf)",
        "+ Map Optic ISU, Kalshi ISU → Iowa State (Ncaaf)",
      ],
    );
    const byTitle = Object.fromEntries(cards.map((card) => [card.title, evidenceLines(card)]));
    expect(byTitle["West Virginia State"]?.some((line) => line.includes("Iowa State"))).toBe(false);
    expect(byTitle["Iowa State"]?.some((line) => line.includes("West Virginia State"))).toBe(false);
    expect(byTitle["West Virginia State"]?.some((line) => line.includes("Robert Morris"))).toBe(true);
    expect(byTitle["Iowa State"]?.some((line) => line.includes("Iowa State vs. Iowa"))).toBe(true);
  });

  it("matches crypto.com pins by id and name", () => {
    const cards = groupEvidenceCards(
      [
        "crypto_id:NX.F.OPT.1",
        "crypto:name:Boston Celtics",
        "crypto:symbol:NX.F.OPT.1:CELTICS",
      ],
      ["Map crypto.com NX.F.OPT.1 → Boston Celtics (Nba)"],
    );
    expect(cards).toEqual([
      {
        title: "Boston Celtics",
        kind: "alias",
        refs: [
          "crypto_id:NX.F.OPT.1",
          "crypto:name:Boston Celtics",
          "crypto:symbol:NX.F.OPT.1:CELTICS",
        ],
      },
    ]);
    expect(evidenceLines(cards[0]!)).toEqual([
      "crypto.com: NX.F.OPT.1",
      "Symbol: CELTICS",
    ]);
  });

  it("keeps each crypto symbol on the pin that probed it", () => {
    const cards = groupEvidenceCards(
      [
        "crypto_id:140005193",
        "crypto:symbol:140005193:NX.F.OPT.UFC-00009-260905-M.O.1.2",
        "crypto_id:140005194",
        "crypto:symbol:140005194:NX.F.OPT.EPL-00001-260904-M.O.1.13",
      ],
      [
        "Map crypto.com 140005193 → Oumar Sy (Ufc)",
        "Map crypto.com 140005194 → Someone Else (Epl)",
      ],
    );
    expect(evidenceLines(cards[0]!)).toEqual([
      "crypto.com: 140005193",
      "Symbol: NX.F.OPT.UFC-00009-260905-M.O.1.2",
    ]);
    expect(evidenceLines(cards[1]!)).toEqual([
      "crypto.com: 140005194",
      "Symbol: NX.F.OPT.EPL-00001-260904-M.O.1.13",
    ]);
  });

  it("uses the single-pin fallback when alias lines are missing", () => {
    const cards = groupEvidenceCards(
      ["gap:KXBOXING-26AUG21SERRANMANZUR", "kalshi:code:SERRAN"],
      [],
      { title: "Amanda Serrano", tokens: ["SERRAN"] },
    );
    expect(cards).toEqual([
      {
        title: "Amanda Serrano",
        kind: "alias",
        refs: ["gap:KXBOXING-26AUG21SERRANMANZUR", "kalshi:code:SERRAN"],
      },
    ]);
  });

  it("keeps a leading canonical key on the card title and matches the name", () => {
    const cards = groupEvidenceCards(
      [
        "optic:competitor:936A32320026A1C0",
        "optic:fixture:202608252F547D65",
        "optic:name:Marko Mesarovic",
      ],
      ["+ Map Optic 936A32320026A1C0 → MES2 Marko Mesarovic (Itf Men)"],
    );
    expect(cards).toEqual([
      {
        title: "MES2 Marko Mesarovic",
        kind: "alias",
        refs: [
          "optic:competitor:936A32320026A1C0",
          "optic:fixture:202608252F547D65",
          "optic:name:Marko Mesarovic",
        ],
      },
    ]);
  });

  it("matches Optic ids when the Map line carries the competitor name", () => {
    const cards = groupEvidenceCards(
      [
        "optic:competitor:245B95767109:Ugo Blanchet",
        "optic:fixture:fx-1:Ugo Blanchet vs Camilo Ugo Carabelli (2026-08-21)",
      ],
      [
        "+ Map crypto.com 814825, Optic 245B95767109 (Ugo Blanchet) → UBG9 Ugo Blanchet (Atp)",
      ],
    );
    expect(cards[0]?.title).toBe("UBG9 Ugo Blanchet");
    expect(cards[0]?.refs).toEqual([
      "optic:competitor:245B95767109:Ugo Blanchet",
      "optic:fixture:fx-1:Ugo Blanchet vs Camilo Ugo Carabelli (2026-08-21)",
    ]);
  });

  it("does not treat a two-letter team prefix as a canonical key", () => {
    const cards = groupEvidenceCards(
      ["optic:competitor:ABC", "optic:name:LA Clippers"],
      ["+ Map Optic ABC → LA Clippers (Nba)"],
    );
    expect(cards[0]?.title).toBe("LA Clippers");
    expect(cards[0]?.refs).toEqual(["optic:competitor:ABC", "optic:name:LA Clippers"]);
  });

  it("returns no cards for empty evidence", () => {
    expect(groupEvidenceCards([], MLB_ALIASES)).toEqual([]);
  });

  it("groups Polymarket name overlays with source sport, league, fixture, and market", () => {
    const cards = groupEvidenceCards(
      [
        "source:sport:soccer",
        "source:league:Germany Bundesliga (germany_bundesliga)",
        "gap:bun-lei-moe-2026-08-29-total-2pt5",
        "polymarket:slug:bun-lei-moe-2026-08-29-total-2pt5",
        "polymarket:question:RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5",
        "polymarket:market:O/U 2.5",
        "optic:competitor:oid-rbl:RasenBallsport Leipzig",
        "optic:fixture:fx-1:RasenBallsport Leipzig vs Borussia VfL Mönchengladbach (2026-08-29)",
        "polymarket:name:RB Leipzig",
        "optic:competitor:oid-bmg:Borussia VfL Mönchengladbach",
        "polymarket:name:Borussia Mönchengladbach",
      ],
      [
        "+ Map Polymarket RB Leipzig, Optic oid-rbl (RasenBallsport Leipzig) → RBL RasenBallsport Leipzig (Germany Bundesliga)",
        "+ Map Polymarket Borussia Mönchengladbach, Optic oid-bmg (Borussia VfL Mönchengladbach) → BMG Borussia VfL Mönchengladbach (Germany Bundesliga)",
      ],
    );
    expect(cards.map((card) => [card.title, card.kind])).toEqual([
      ["RBL RasenBallsport Leipzig", "alias"],
      ["BMG Borussia VfL Mönchengladbach", "alias"],
    ]);
    const shared = [
      "source:sport:soccer",
      "source:league:Germany Bundesliga (germany_bundesliga)",
      "gap:bun-lei-moe-2026-08-29-total-2pt5",
      "polymarket:slug:bun-lei-moe-2026-08-29-total-2pt5",
      "polymarket:question:RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5",
      "polymarket:market:O/U 2.5",
    ];
    const fixture =
      "optic:fixture:fx-1:RasenBallsport Leipzig vs Borussia VfL Mönchengladbach (2026-08-29)";
    expect(cards[0]?.refs).toEqual([
      ...shared,
      "optic:competitor:oid-rbl:RasenBallsport Leipzig",
      fixture,
      "polymarket:name:RB Leipzig",
    ]);
    expect(cards[1]?.refs).toEqual([
      ...shared,
      fixture,
      "optic:competitor:oid-bmg:Borussia VfL Mönchengladbach",
      "polymarket:name:Borussia Mönchengladbach",
    ]);
  });

  it("un-rotates three labeled fixtures that follow the previous competitor", () => {
    const cards = groupEvidenceCards(
      [
        "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
        "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
        "optic:competitor:82ECCB05BBAF9851:Atreides",
        "optic:fixture:cs2-2:Azuolas vs Entropy (2026-08-31)",
        "optic:competitor:C30BA00000000000:Azuolas",
        "optic:fixture:pvl-1:FK Dunav Ruse vs Slavia Sofia (2026-09-07)",
        "note:pipeline-gap-fix",
      ],
      [
        "+ Map Optic 7BFFE59C91FCD0DE (FK Dunav Ruse), polymarket_usa dun → DR FK Dunav Ruse (Bulgaria Parva Liga)",
        "+ Map Optic 82ECCB05BBAF9851 (Atreides), polymarket_usa atr → ATR7 Atreides (Cs2)",
        "+ Map Optic C30BA00000000000 (Azuolas), polymarket_usa azu → AZU8 Azuolas (Cs2)",
      ],
    );
    expect(cards.map((card) => card.title)).toEqual([
      "DR FK Dunav Ruse",
      "ATR7 Atreides",
      "AZU8 Azuolas",
      "Notes",
    ]);
    expect(evidenceLines(cards[0]!)).toContain(
      "Fixture: FK Dunav Ruse vs Slavia Sofia (2026-09-07)",
    );
    expect(evidenceLines(cards[1]!)).toContain("Fixture: Atreides vs Virtus.pro (2026-08-31)");
    expect(evidenceLines(cards[2]!)).toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
    expect(evidenceLines(cards[0]!)).not.toContain("Fixture: Atreides vs Virtus.pro (2026-08-31)");
    expect(evidenceLines(cards[1]!)).not.toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
    expect(evidenceLines(cards[2]!)).not.toContain(
      "Fixture: FK Dunav Ruse vs Slavia Sofia (2026-09-07)",
    );
  });

  it("un-rotates matchup-only fixture refs with no id prefix", () => {
    const cards = groupEvidenceCards(
      [
        "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
        "optic:fixture:Atreides vs Virtus.pro (2026-08-31)",
        "optic:competitor:82ECCB05BBAF9851:Atreides",
        "optic:fixture:Azuolas vs Entropy (2026-08-31)",
        "optic:competitor:C30BA00000000000:Azuolas",
        "optic:fixture:FK Dunav Ruse vs Slavia Sofia (2026-09-07)",
      ],
      [
        "+ Map Optic 7BFFE59C91FCD0DE (FK Dunav Ruse), polymarket_usa dun → DR FK Dunav Ruse (Bulgaria Parva Liga)",
        "+ Map Optic 82ECCB05BBAF9851 (Atreides), polymarket_usa atr → ATR7 Atreides (Cs2)",
        "+ Map Optic C30BA00000000000 (Azuolas), polymarket_usa azu → AZU8 Azuolas (Cs2)",
      ],
    );
    expect(evidenceLines(cards[0]!)).toContain("Fixture: FK Dunav Ruse vs Slavia Sofia (2026-09-07)");
    expect(evidenceLines(cards[1]!)).toContain("Fixture: Atreides vs Virtus.pro (2026-08-31)");
    expect(evidenceLines(cards[2]!)).toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
  });

  it("puts a two-sided fixture on both named aliases, not a third team", () => {
    const cards = groupEvidenceCards(
      [
        "optic:name:BIG Academy",
        "optic:fixture:20260903C7984A91:BIG Academy vs Fortress (2026-09-03)",
        "optic:fixture:20260831F4B11488:Azuolas vs Entropy (2026-08-31)",
        "optic:name:Entropy",
        "optic:name:Azuolas",
        "gap:usa-inner:cs2:ent",
        "optic:competitor:91F77395FC84:Entropy",
        "gap:usa-inner:cs2:azu",
        "optic:competitor:C30BA6997B9DAA39:Azuolas",
        "gap:usa-inner:cs2:biga",
        "optic:competitor:3971145542B7:BIG Academy",
      ],
      [
        "+ Map Optic 3971145542B7 (BIG Academy), polymarket_usa biga → BAI5 BIG Academy (Cs2)",
        "+ Map Optic 91F77395FC84 (Entropy), polymarket_usa ent → ENT2 Entropy (Cs2)",
        "+ Map Optic C30BA6997B9DAA39 (Azuolas), polymarket_usa azu → AZU8 Azuolas (Cs2)",
      ],
    );
    const lines = cards.map((card) => [card.title, evidenceLines(card)]);
    expect(lines[0]?.[0]).toBe("BAI5 BIG Academy");
    expect(lines[0]?.[1]).toContain("Fixture: BIG Academy vs Fortress (2026-09-03)");
    expect(lines[0]?.[1]).not.toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
    expect(lines[1]?.[1]).toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
    expect(lines[2]?.[1]).toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
    expect(lines[0]?.[1]).toContain("Polymarket US name: BIG Academy");
    expect(lines[1]?.[1]).toContain("Polymarket US name: Entropy");
    expect(lines[2]?.[1]).toContain("Polymarket US name: Azuolas");
  });

  it("keeps one fixture when harvest and Optic ids share a matchup", () => {
    const cards = groupEvidenceCards(
      [
        "optic:competitor:4E6E8D0B0EC1:FC Barcelona",
        "optic:fixture:29234-24495-2026-08-31:FC Barcelona vs Rayo Vallecano (2026-08-31)",
        "optic:fixture:2026083179BA180C:FC Barcelona vs Rayo Vallecano (2026-08-31)",
        "optic:name:FC Barcelona",
        "optic:competitor:A477D0C02A28:Chelsea FC",
        "optic:fixture:38415-13094-2026-09-06:Arsenal FC vs Chelsea FC (2026-09-06)",
        "optic:fixture:2026090599C50530:Arsenal FC vs Chelsea FC (2026-09-06)",
        "optic:name:Chelsea FC",
      ],
      [
        "+ Map Optic 4E6E8D0B0EC1 (FC Barcelona) → BAR FC Barcelona (La Liga)",
        "+ Map Optic A477D0C02A28 (Chelsea FC) → CFC Chelsea FC (Epl)",
      ],
    );
    const barca = evidenceLines(cards[0]!);
    const chelsea = evidenceLines(cards[1]!);
    expect(barca.filter((line) => line.startsWith("Fixture:"))).toEqual([
      "Fixture: FC Barcelona vs Rayo Vallecano (2026-08-31)",
    ]);
    expect(chelsea.filter((line) => line.startsWith("Fixture:"))).toEqual([
      "Fixture: Arsenal FC vs Chelsea FC (2026-09-06)",
    ]);
    expect(cards[0]?.refs.some((ref) => ref.includes("2026083179BA180C"))).toBe(true);
    expect(cards[0]?.refs.some((ref) => ref.includes("29234-24495"))).toBe(false);
  });

  it("does not copy a two-sided fixture onto a third pin", () => {
    const cards = groupEvidenceCards(
      [
        "optic:name:BIG Academy",
        "optic:name:Entropy",
        "optic:name:Azuolas",
        "optic:fixture:20260831F4B11488:Azuolas vs Entropy (2026-08-31)",
      ],
      [
        "+ Map Optic 3971145542B7 (BIG Academy), polymarket_usa biga → BAI5 BIG Academy (Cs2)",
        "+ Map Optic 91F77395FC84 (Entropy), polymarket_usa ent → ENT2 Entropy (Cs2)",
        "+ Map Optic C30BA6997B9DAA39 (Azuolas), polymarket_usa azu → AZU8 Azuolas (Cs2)",
      ],
    );
    expect(evidenceLines(cards[0]!)).not.toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
    expect(evidenceLines(cards[1]!)).toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
    expect(evidenceLines(cards[2]!)).toContain("Fixture: Azuolas vs Entropy (2026-08-31)");
  });

  it("places a late leftover fixture on both named pins, not a third club", () => {
    const cards = groupEvidenceCards(
      [
        "optic:name:FC Barcelona",
        "optic:competitor:4E6E8D0B0EC1:FC Barcelona",
        "optic:fixture:2026083179BA180C:FC Barcelona vs Rayo Vallecano (2026-08-31)",
        "optic:name:Manchester United FC",
        "optic:competitor:AF8DDBC0795A:Manchester United FC",
        "optic:name:AFC Bournemouth",
        "optic:competitor:F2CCF38E0A5A:AFC Bournemouth",
        "optic:name:Clube do Remo",
        "optic:name:Coritiba FBC",
        "optic:fixture:2026090574A30340:Newcastle United FC vs AFC Bournemouth (2026-09-05)",
        "optic:fixture:20260831C7DC3E0D:Clube do Remo vs Coritiba FBC (2026-08-31)",
      ],
      [
        "+ Map Optic 4E6E8D0B0EC1 → FC Barcelona (La Liga)",
        "+ Map Optic AF8DDBC0795A → Manchester United FC (Epl)",
        "+ Map Optic F2CCF38E0A5A → AFC Bournemouth (Epl)",
        "+ Map Optic ED5DD8FBB720954A → Clube do Remo (Brazil Serie A)",
        "+ Map Optic 236C75DE875A → Coritiba FBC (Brazil Serie A)",
      ],
    );
    const byTitle = Object.fromEntries(cards.map((card) => [card.title, evidenceLines(card)]));
    expect(byTitle["FC Barcelona"]?.filter((line) => line.startsWith("Fixture:"))).toEqual([
      "Fixture: FC Barcelona vs Rayo Vallecano (2026-08-31)",
    ]);
    expect(byTitle["Manchester United FC"]).not.toContain(
      "Fixture: Newcastle United FC vs AFC Bournemouth (2026-09-05)",
    );
    expect(byTitle["AFC Bournemouth"]).toContain(
      "Fixture: Newcastle United FC vs AFC Bournemouth (2026-09-05)",
    );
    expect(byTitle["Clube do Remo"]).toContain("Fixture: Clube do Remo vs Coritiba FBC (2026-08-31)");
    expect(byTitle["Coritiba FBC"]).toContain("Fixture: Clube do Remo vs Coritiba FBC (2026-08-31)");
    expect(byTitle["FC Barcelona"]).not.toContain("Fixture: Clube do Remo vs Coritiba FBC (2026-08-31)");
  });

  it("keeps Polymarket US source and Optic target on the matching alias card", () => {
    const cards = groupEvidenceCards(
      [
        "gap:usa-inner:cs2:atr",
        "optic:competitor:82ECCB05BBAF9851:Atreides",
        "gap:usa-inner:bulgaria_parva_liga:dun",
        "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
        "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
        "optic:fixture:pvl-1:FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)",
        "note:pipeline-gap-fix",
      ],
      [
        "+ Map Optic 7BFFE59C91FCD0DE (FK Dunav Ruse), polymarket_usa dun → DR FK Dunav Ruse (Bulgaria Parva Liga)",
        "+ Map Optic 82ECCB05BBAF9851 (Atreides), polymarket_usa atr → ATR7 Atreides (Cs2)",
      ],
    );
    expect(cards.map((card) => [card.title, card.kind])).toEqual([
      ["DR FK Dunav Ruse", "alias"],
      ["ATR7 Atreides", "alias"],
      ["Notes", "notes"],
    ]);
    expect(cards[0]?.refs).toEqual([
      "polymarket_usa:code:dun",
      "polymarket_usa:name:DR FK Dunav Ruse",
      "gap:usa-inner:bulgaria_parva_liga:dun",
      "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
      "optic:fixture:pvl-1:FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)",
    ]);
    expect(cards[1]?.refs).toEqual([
      "polymarket_usa:code:atr",
      "polymarket_usa:name:Atreides",
      "gap:usa-inner:cs2:atr",
      "optic:competitor:82ECCB05BBAF9851:Atreides",
      "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
    ]);
    expect(evidenceLines(cards[0]!)).toEqual([
      "Polymarket US code: dun",
      "Polymarket US name: DR FK Dunav Ruse",
      "Polymarket US: dun (bulgaria parva liga)",
      "Optic competitor: FK Dunav Ruse (7BFFE59C91FCD0DE)",
      "Fixture: FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)",
    ]);
    expect(evidenceLines(cards[1]!)).toEqual([
      "Polymarket US code: atr",
      "Polymarket US name: Atreides",
      "Polymarket US: atr (cs2)",
      "Optic competitor: Atreides (82ECCB05BBAF9851)",
      "Fixture: Atreides vs Virtus.pro (2026-08-31)",
    ]);
  });

  it("keeps Polymarket US full name and title on the alias that owns the code", () => {
    const cards = groupEvidenceCards(
      [
        "polymarket_usa:code:dun",
        "polymarket_usa:name:FC Dunav Ruse",
        "polymarket_usa:title:FC Dunav Ruse vs. FC Lokomotiv 1929 Sofia",
        "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
        "optic:fixture:pvl-1:FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)",
        "polymarket_usa:code:atr",
        "polymarket_usa:name:Atreides",
        "polymarket_usa:title:Atreides vs. Virtus.pro",
        "optic:competitor:82ECCB05BBAF9851:Atreides",
        "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
      ],
      [
        "+ Map Optic 7BFFE59C91FCD0DE (FK Dunav Ruse), polymarket_usa dun → DR FK Dunav Ruse (Bulgaria Parva Liga)",
        "+ Map Optic 82ECCB05BBAF9851 (Atreides), polymarket_usa atr → ATR7 Atreides (Cs2)",
      ],
    );
    expect(evidenceLines(cards[0]!)).toEqual([
      "Polymarket US code: dun",
      "Polymarket US name: FC Dunav Ruse",
      "Polymarket US title: FC Dunav Ruse vs. FC Lokomotiv 1929 Sofia",
      "Optic competitor: FK Dunav Ruse (7BFFE59C91FCD0DE)",
      "Fixture: FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)",
    ]);
    expect(evidenceLines(cards[1]!)).toEqual([
      "Polymarket US code: atr",
      "Polymarket US name: Atreides",
      "Polymarket US title: Atreides vs. Virtus.pro",
      "Optic competitor: Atreides (82ECCB05BBAF9851)",
      "Fixture: Atreides vs Virtus.pro (2026-08-31)",
    ]);
  });

  it("sticks Polymarket US ticker and match to the alias that owns the code", () => {
    const cards = groupEvidenceCards(
      [
        "polymarket_usa:code:dun",
        "polymarket_usa:ticker:pvl-dun-lok-2026-08-31",
        "polymarket_usa:match:dun vs lok (2026-08-31)",
        "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
        "optic:fixture:pvl-1:FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)",
        "polymarket_usa:code:atr",
        "polymarket_usa:ticker:cs2-atr-vp-2026-08-31",
        "polymarket_usa:match:atr vs vp (2026-08-31)",
        "optic:competitor:82ECCB05BBAF9851:Atreides",
        "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
      ],
      [
        "+ Map Optic 7BFFE59C91FCD0DE (FK Dunav Ruse), polymarket_usa dun → DR FK Dunav Ruse (Bulgaria Parva Liga)",
        "+ Map Optic 82ECCB05BBAF9851 (Atreides), polymarket_usa atr → ATR7 Atreides (Cs2)",
      ],
    );
    expect(cards[0]?.refs).toEqual([
      "polymarket_usa:name:DR FK Dunav Ruse",
      "polymarket_usa:code:dun",
      "polymarket_usa:ticker:pvl-dun-lok-2026-08-31",
      "polymarket_usa:match:dun vs lok (2026-08-31)",
      "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
      "optic:fixture:pvl-1:FK Dunav Ruse vs Lokomotiv Sofia (2026-08-31)",
    ]);
    expect(cards[1]?.refs).toEqual([
      "polymarket_usa:name:Atreides",
      "polymarket_usa:code:atr",
      "polymarket_usa:ticker:cs2-atr-vp-2026-08-31",
      "polymarket_usa:match:atr vs vp (2026-08-31)",
      "optic:competitor:82ECCB05BBAF9851:Atreides",
      "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
    ]);
  });

  it("groups league pin refs onto book cards", () => {
    const cards = groupEvidenceCards(
      [
        "optic:id:saudi_arabia_-_saudi_league",
        "optic:fixtures:12",
        "kalshi:id:KXSPL",
        "kalshi:parser:kalshi_generic_v1",
        "skip:px:No live tournament",
        "note:From Rules: update saudi_pro_league",
      ],
      [],
    );
    expect(cards.map((card) => [card.title, card.kind])).toEqual([
      ["Optic", "book"],
      ["Kalshi", "book"],
      ["ProphetX", "book"],
      ["Notes", "notes"],
    ]);
    expect(cards[0]?.refs).toEqual([
      "optic:id:saudi_arabia_-_saudi_league",
      "optic:fixtures:12",
    ]);
  });
});

describe("evidenceLines", () => {
  it("shows fixture matchup and date instead of the raw id", () => {
    expect(
      displayEvidenceRef("optic:fixture:20260829B04FA062:Song Yadong vs Andre Lima (2026-08-29)"),
    ).toBe("Fixture: Song Yadong vs Andre Lima (2026-08-29)");
  });

  it("labels a legacy fixture id when no matchup is stored", () => {
    expect(displayEvidenceRef("optic:fixture:20260829B04FA062")).toBe(
      "Fixture: 20260829B04FA062",
    );
  });

  it("hides optic name when it repeats the card title", () => {
    const lines = evidenceLines({
      title: "SYO9 Song Yadong",
      kind: "alias",
      refs: [
        "optic:competitor:3B6604D2ABF4",
        "optic:fixture:fx-1:Song Yadong vs Andre Lima (2026-08-29)",
        "optic:name:Song Yadong",
      ],
    });
    expect(lines).toEqual([
      "Optic competitor: 3B6604D2ABF4",
      "Fixture: Song Yadong vs Andre Lima (2026-08-29)",
    ]);
  });

  it("shows the Optic competitor name next to the hex id", () => {
    expect(displayEvidenceRef("optic:competitor:245B95767109:Ugo Blanchet")).toBe(
      "Optic competitor: Ugo Blanchet (245B95767109)",
    );
  });

  it("pretty-prints book and note refs", () => {
    expect(displayEvidenceRef("optic:id:saudi_arabia_-_saudi_league")).toBe(
      "Optic league: saudi_arabia_-_saudi_league",
    );
    expect(displayEvidenceRef("skip:px:No live tournament")).toBe("No live tournament");
    expect(displayEvidenceRef("note:pipeline gap-fix")).toBe("Note: pipeline gap-fix");
    expect(displayEvidenceRef("crypto_id:140000440")).toBe("crypto.com: 140000440");
    expect(displayEvidenceRef("crypto:title:Thomas Faurel @ Dusan Obradovic")).toBe(
      "Title: Thomas Faurel @ Dusan Obradovic",
    );
    expect(displayEvidenceRef("crypto:symbol:140005193:NX.F.OPT.UFC-00009")).toBe(
      "Symbol: NX.F.OPT.UFC-00009",
    );
    expect(displayEvidenceRef("crypto:symbol:NX.F.OPT.UFC-00009")).toBe(
      "Symbol: NX.F.OPT.UFC-00009",
    );
    expect(displayEvidenceRef("source:sport:soccer")).toBe("Sport: soccer");
    expect(displayEvidenceRef("source:league:Germany Bundesliga (germany_bundesliga)")).toBe(
      "League: Germany Bundesliga (germany_bundesliga)",
    );
    expect(displayEvidenceRef("polymarket:question:RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5")).toBe(
      "Question: RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5",
    );
    expect(displayEvidenceRef("polymarket:market:O/U 2.5")).toBe("Market: O/U 2.5");
    expect(displayEvidenceRef("polymarket:name:RB Leipzig")).toBe("Name: RB Leipzig");
    expect(displayEvidenceRef("polymarket:description:Over/Under 2.5 total goals")).toBe(
      "Description: Over/Under 2.5 total goals",
    );
    expect(displayEvidenceRef("source:date:2026-08-29")).toBe("Date: 2026-08-29");
    expect(displayEvidenceRef("kalshi:market_title:Detroit wins")).toBe(
      "Market title: Detroit wins",
    );
    expect(displayEvidenceRef("kalshi:yes_sub_title:Detroit")).toBe("yes_sub_title: Detroit");
    expect(
      displayEvidenceRef(
        "kalshi:rules_primary:If Detroit wins the DET Lions vs CAR Panthers Pro Football game.",
      ),
    ).toBe(
      "rules_primary: If Detroit wins the DET Lions vs CAR Panthers Pro Football game.",
    );
    expect(displayEvidenceRef("polymarket:outcome:Over")).toBe("Outcome: Over");
    expect(displayEvidenceRef("polymarket_usa:code:dun")).toBe("Polymarket US code: dun");
    expect(displayEvidenceRef("polymarket_usa:name:FC Dunav Ruse")).toBe(
      "Polymarket US name: FC Dunav Ruse",
    );
    expect(
      displayEvidenceRef("polymarket_usa:title:FC Dunav Ruse vs. FC Lokomotiv 1929 Sofia"),
    ).toBe("Polymarket US title: FC Dunav Ruse vs. FC Lokomotiv 1929 Sofia");
    expect(displayEvidenceRef("polymarket_usa:ticker:pvl-dun-lok-2026-08-31")).toBe(
      "Polymarket US ticker: pvl-dun-lok-2026-08-31",
    );
    expect(displayEvidenceRef("polymarket_usa:match:dun vs lok (2026-08-31)")).toBe(
      "Polymarket US: dun vs lok (2026-08-31)",
    );
    expect(displayEvidenceRef("gap:usa-inner:bulgaria_parva_liga:dun")).toBe(
      "Polymarket US: dun (bulgaria parva liga)",
    );
  });
});

describe("TxODDS evidence lines", () => {
  it("reads the three txodds ref shapes", async () => {
    const { displayEvidenceRef } = await import("./evidenceCards");
    expect(displayEvidenceRef("txodds:team:2476:LA Clippers")).toBe("TxODDS team: LA Clippers (2476)");
    expect(displayEvidenceRef("txodds:unverified:Forbidden")).toBe(
      "TxODDS team list not readable here (Forbidden): pin not checked",
    );
    expect(displayEvidenceRef("txodds:name-unchecked")).toBe("TxODDS name not checked: this canonical has no name");
  });
});
