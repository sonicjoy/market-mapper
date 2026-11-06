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
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto(BASE, { waitUntil: "networkidle" });

const composer = page.getByPlaceholder(/message the mapping agent/i);
await composer.waitFor({ timeout: 15000 });
for (const msg of ["which platforms we mapped mlb", "suggest aliases for mlb"]) {
  await composer.fill(msg);
  await composer.press("Enter");
  await page.waitForTimeout(9000);
}

const transcript = page.locator("div.overflow-auto.px-3.py-2.text-sm").last();
const handle = page.getByRole("separator", { name: /resize chat/i });
const measure = () => transcript.evaluate((el) => Math.round(el.getBoundingClientRect().height));

const before = await measure();
await page.screenshot({ path: `${OUT}/07-chat-default.png` });

// Drag the handle upward to grow the transcript to an arbitrary height.
const box = await handle.boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
await page.mouse.down();
await page.mouse.move(box.x + box.width / 2, box.y - 260, { steps: 12 });
await page.mouse.up();
await page.waitForTimeout(400);
const afterDragUp = await measure();
await page.screenshot({ path: `${OUT}/08-chat-dragged.png` });

// Persisted across reload?
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(1200);
const afterReload = await measure();

// Drag back down, then double-click to reset.
const box2 = await handle.boundingBox();
await page.mouse.move(box2.x + box2.width / 2, box2.y + box2.height / 2);
await page.mouse.down();
await page.mouse.move(box2.x + box2.width / 2, box2.y + 120, { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(300);
const afterDragDown = await measure();

await handle.dblclick();
await page.waitForTimeout(300);
const afterReset = await measure();

console.log(
  JSON.stringify({ before, afterDragUp, afterReload, afterDragDown, afterReset }, null, 2),
);
await browser.close();
