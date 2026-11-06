import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.SMOKE_BASE_URL ?? "http://127.0.0.1:5173";
const OUT = "console/.smoke";
mkdirSync(OUT, { recursive: true });

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
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });

await page.goto(`${BASE}/rules?kind=leagues&q=mlb`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/05-leagues-mlb.png` });

await page.goto(`${BASE}/rules?kind=leagues&q=kalshi`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/06-leagues-kalshi.png` });
const kalshiRows = await page.locator("tbody tr").count();

console.log(JSON.stringify({ kalshiRows }, null, 2));
await browser.close();
