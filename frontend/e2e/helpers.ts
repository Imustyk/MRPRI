import { expect, type Page, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

export const SHOTS = resolve(process.cwd(), "../docs/frontend-verification");
mkdirSync(SHOTS, { recursive: true });

export const ROUTES = [
  "/",
  "/tenders",
  "/models",
  "/indicators",
  "/distributions",
  "/network",
  "/workspace",
  "/method",
  "/kpis",
  "/raci",
];

export const WIDTHS = [375, 768, 1024, 1280, 1440, 1920];

export async function expectNoDocumentOverflow(page: Page) {
  const box = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(box.scroll, `document overflows horizontally: ${JSON.stringify(box)}`).toBeLessThanOrEqual(
    box.client + 1,
  );
}

/** Every rendered chart must have a non-zero size after load/resize. */
export async function expectChartsHaveSize(page: Page) {
  const bad = await page.evaluate(() => {
    const nodes = [
      ...document.querySelectorAll(".recharts-wrapper"),
      ...document.querySelectorAll(".quartile-chart"),
      ...document.querySelectorAll(".net-svg"),
    ];
    return nodes
      .map((n) => {
        const r = n.getBoundingClientRect();
        return { cls: n.getAttribute("class") ?? "", w: Math.round(r.width), h: Math.round(r.height) };
      })
      .filter((b) => b.w < 10 || b.h < 10);
  });
  expect(bad, "zero-sized charts").toEqual([]);
}

/** Wide tables must scroll inside their own container, not widen the page. */
export async function expectTablesScrollInPlace(page: Page) {
  const result = await page.evaluate(() => {
    const doc = document.documentElement;
    return [...document.querySelectorAll(".table-wrap")].map((wrap) => ({
      overflowsSelf: wrap.scrollWidth > wrap.clientWidth + 1,
      expandsDocument: doc.scrollWidth > doc.clientWidth + 1,
    }));
  });
  for (const r of result) {
    if (r.overflowsSelf) expect(r.expandsDocument).toBe(false);
  }
}

export async function waitForRouteReady(page: Page) {
  await page.waitForSelector("h1", { timeout: 30_000 });
  // Let lazy chunks, API calls and chart measurement settle.
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(300);
}
