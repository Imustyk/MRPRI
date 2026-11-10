import { expect, test } from "@playwright/test";
import { SHOTS, expectNoDocumentOverflow, waitForRouteReady } from "./helpers";

/**
 * Distributions: the spread chart shows the real p25 → p75 interval with a
 * separate median marker, rows are keyboard-focusable with raw-quartile
 * tooltips, and the raw table is available underneath.
 */

test("spread chart: interval geometry, focusable rows, raw quartile table", async ({
  page,
}) => {
  await page.goto("/distributions");
  await waitForRouteReady(page);

  // Relationships tab holds the scatter and the spread chart.
  await page.getByRole("tab", { name: "Relationships" }).click();
  const chart = page.locator(".quartile-chart");
  await expect(chart).toBeVisible({ timeout: 30_000 });
  await expectNoDocumentOverflow(page);

  const rows = chart.locator("g.quartile-row");
  const count = await rows.count();
  expect(count).toBeGreaterThan(0);

  // Every row is reachable by keyboard and describes its raw quartiles + n.
  await rows.first().focus();
  const label = await rows.first().getAttribute("aria-label");
  expect(label).toBeTruthy();
  expect(label!).toMatch(/p25/);
  expect(label!).toMatch(/n=/);

  // The reserved tooltip below the chart shows the raw values, not sums.
  const tip = page.locator(".quartile-tip");
  await expect(tip).toBeVisible();
  const tipText = (await tip.innerText()).replace(/\s+/g, " ");
  expect(tipText).toMatch(/p25/i);
  expect(tipText).toMatch(/median|Median|Медиана|Mediană/i);
  expect(tipText).toMatch(/p75/i);

  // Interval + median geometry: each valid row draws one interval rect and at
  // most one median marker — no stacked segments.
  const geometry = await chart.evaluate((svg) => {
    return [...svg.querySelectorAll("g.quartile-row")].map((row) => ({
      intervals: row.querySelectorAll(".quartile-interval").length,
      medians: row.querySelectorAll(".quartile-median").length,
      placeholders: row.querySelectorAll(".quartile-placeholder").length,
    }));
  });
  for (const g of geometry) {
    expect(g.intervals).toBeLessThanOrEqual(1);
    expect(g.medians).toBeLessThanOrEqual(1);
    if (g.intervals === 1) expect(g.placeholders).toBe(0);
  }

  // Raw values table is present under the chart.
  await page.locator("details summary", { hasText: /Raw quartile values/i }).click();
  const table = page.locator(".quartile-chart-wrap").locator("xpath=following::table[1]");
  await expect(table).toBeVisible();
  const headers = await table.locator("thead th").allInnerTexts();
  expect(headers.join(" ")).toMatch(/p25/);
  expect(headers.join(" ")).toMatch(/p75/);

  await page.screenshot({ path: `${SHOTS}/distributions-spread-quartiles.png`, fullPage: true });
});

test("request states: tabs announce loading and settle to a result or an explicit empty", async ({
  page,
}) => {
  await page.goto("/distributions");
  await waitForRouteReady(page);

  // Each tab keeps a live region with the parameter description and reaches a
  // terminal state (no infinite skeleton).
  for (const tab of ["Correlations", "Distributions", "Relationships", "Composition"]) {
    await page.getByRole("tab", { name: tab }).click();
    const panel = page.locator("#distribution-panel");
    // Terminal state: either content, an explicit empty, or an error note.
    await expect(panel).toBeVisible();
    await page.waitForFunction(
      () => {
        const el = document.querySelector("#distribution-panel")!;
        const busy = el.querySelectorAll(".skeleton").length;
        const done =
          el.querySelector(".empty, .error-note, table, svg, .corr-grid") !== null;
        return busy === 0 && done;
      },
      undefined,
      { timeout: 30_000 },
    );
    const status = await page.locator('#distribution-panel [role="status"]').count();
    expect(status, `${tab}: persistent live region`).toBeGreaterThan(0);
  }
  await page.screenshot({ path: `${SHOTS}/distributions-composition-tab.png` });
});
