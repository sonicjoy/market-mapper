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
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

await page.goto(BASE, { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}/01-home.png`, fullPage: false });

const dock = page.getByPlaceholder(/ask|mapping|message/i).first();
await dock.waitFor({ timeout: 15000 });
await dock.fill("add league ucl soccer");
await dock.press("Enter");

await page.getByRole("button", { name: /yes, add to cart/i }).waitFor({ timeout: 60000 });
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/02-league-proposed.png` });
const url1 = page.url();
const prefilled = await page
  .locator("main input, form input")
  .evaluateAll((els) => els.map((e) => e.value).filter(Boolean));

await page.getByRole("button", { name: /yes, add to cart/i }).click();
await page.getByRole("button", { name: /suggest market rules next/i }).waitFor({ timeout: 60000 });
await page.screenshot({ path: `${OUT}/03-cart-added.png` });

await page.getByRole("button", { name: /suggest market rules next/i }).click();
await page.waitForTimeout(20000);
await page.screenshot({ path: `${OUT}/04-markets.png` });

console.log(
  JSON.stringify({ urlAfterLeague: url1, prefilled, urlNow: page.url(), errors }, null, 2),
);
await browser.close();
