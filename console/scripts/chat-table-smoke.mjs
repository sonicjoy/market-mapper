import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.SMOKE_BASE_URL ?? "http://127.0.0.1:5173";
const OUT = "console/.smoke";
mkdirSync(OUT, { recursive: true });

const TABLE_MD = [
  "**Exchange Source League Identifiers**",
  "",
  "| Sportsbook/Exchange | Enabled | Source League ID |",
  "| --- | --- | --- |",
  "| kalshi | yes | `KXUEFACHAMPSLEAGUE` |",
  "| polymarket | yes | `uefa-champions-league` |",
  "| crypto.com | no | — |",
  "",
  "- bold, code and lists should still render",
].join("\n");

async function launch() {
  for (const channel of [undefined, "msedge", "chrome"]) {
    try {
      return await chromium.launch({ channel, headless: true });
    } catch (err) {
      if (channel === "chrome") throw err;
    }
  }
  throw new Error("no browser");
}

const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

await page.goto(BASE, { waitUntil: "networkidle" });

// Seed a thread whose assistant reply contains a GFM pipe table.
await page.evaluate((md) => {
  const now = new Date().toISOString();
  const thread = {
    id: "conv_tablesmoke01",
    title: "table smoke",
    updated_at: now,
    messages: [
      { id: "msg_u1", role: "user", content: "show exchange source league ids", created_at: now },
      { id: "msg_a1", role: "assistant", content: md, created_at: now },
    ],
  };
  localStorage.setItem("mapping-console-chat:threads", JSON.stringify([thread]));
  localStorage.setItem("mapping-console-chat:active", thread.id);
  localStorage.setItem("mapping-console-chat:height", "420");
}, TABLE_MD);

await page.reload({ waitUntil: "networkidle" });

const table = page.locator("table").first();
await table.waitFor({ timeout: 15000 });

const dom = await page.evaluate(() => {
  const t = document.querySelector("table");
  if (!t) return null;
  return {
    tag: t.tagName,
    headers: [...t.querySelectorAll("th")].map((e) => e.textContent?.trim()),
    rows: [...t.querySelectorAll("tbody tr")].map((r) =>
      [...r.querySelectorAll("td")].map((c) => c.textContent?.trim()),
    ),
    cellCount: t.querySelectorAll("td").length,
    codeInCell: !!t.querySelector("td code"),
    strongAboveTable: !!document.querySelector("strong"),
    listAfterTable: document.querySelectorAll("ul li").length,
    rawPipesInText: (document.body.innerText.match(/\| --- \|/g) ?? []).length,
  };
});

await page.screenshot({ path: `${OUT}/chat-gfm-table.png`, fullPage: false });

console.log(JSON.stringify({ dom, errors }, null, 2));
await browser.close();

if (!dom || dom.cellCount === 0) {
  console.error("FAIL: no table cells rendered");
  process.exit(1);
}
console.log("PASS: real <table> with", dom.cellCount, "cells");
