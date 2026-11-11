import { expect, test } from "@playwright/test";
import { SHOTS, expectChartsHaveSize, expectNoDocumentOverflow, waitForRouteReady } from "./helpers";

/**
 * Histogram states verified against the isolated dev fixture (the served
 * dataset carries no score_provenance.run_id, so the live API never fills the
 * reference — see the report's limitations). The route exists only in a
 * development build.
 */

test("histogram: score marker, hatched threshold marker, same-interval coincidence", async ({
  page,
}) => {
  await page.goto("/__fixture/model-card");
  await waitForRouteReady(page);
  await expectNoDocumentOverflow(page);
  await expectChartsHaveSize(page);

  const card = page.locator('.model-explanation[data-model="statistical_mad_zscore"]');
  await expect(card).toBeVisible();

  // Exact score, percentile and threshold are adjacent to the chart.
  const metrics = (await card.locator(".model-metrics").innerText()).replace(/\s+/g, " ");
  expect(metrics).toMatch(/11\.2/); // raw score, not a normalised stand-in
  expect(metrics).toMatch(/99\.1/); // percentile
  const boundary = (await card.locator(".model-boundary").innerText()).replace(/\s+/g, " ");
  expect(boundary).toMatch(/>\s*11/);

  // Same interval: one bar carries both the selected and threshold classes,
  // and the legend explains the coincidence.
  const shared = card.locator(".hist-bar.hist-bar-selected.hist-bar-threshold");
  await expect(shared).toHaveCount(1);
  const legend = (await card.locator(".legend").innerText()).replace(/\s+/g, " ");
  expect(legend).toMatch(/Selected procedure — score 11\.2/);
  expect(legend).toMatch(/Stored boundary — > 11/);
  expect(legend).toMatch(/same interval/);
  // Markers identify intervals, not exact coordinates.
  expect(legend).toMatch(/log10\(1 \+ count\)|procedure count/);

  // Tooltip: raw counts, not log values.
  const bar = shared.locator("path").first();
  await bar.hover({ force: true });
  const tooltip = page.locator(".recharts-tooltip-wrapper").first();
  await expect(tooltip).toBeVisible({ timeout: 5_000 });
  const tipText = (await tooltip.innerText()).replace(/\s+/g, " ");
  expect(tipText).toMatch(/420/); // raw n for the shared bin
  expect(tipText).not.toMatch(/2\.62/); // log10(1+420) ≈ 2.62 must not leak

  await page.screenshot({ path: `${SHOTS}/histogram-same-interval.png`, fullPage: true });
});

test("histogram: all-zero counts and a missing score stay honest", async ({ page }) => {
  await page.goto("/__fixture/model-card");
  await waitForRouteReady(page);

  // The workbench shows one detector at a time; switch with the model tabs.
  await page.getByRole("tab", { name: "Isolation Forest" }).click();
  const allZero = page.locator('.model-explanation[data-model="isolation_forest"]');
  await expect(allZero).toBeVisible();
  await expect(allZero.locator(".score-histogram")).toHaveCount(0);
  await expect(allZero.locator(".hist-bar")).toHaveCount(0);
  await expect(allZero.locator(".hist-bar-selected")).toHaveCount(0);
  await expect(allZero.locator(".hist-bar-threshold")).toHaveCount(0);

  await page.getByRole("tab", { name: "LOF" }).click();
  const missing = page.locator('.model-explanation[data-model="local_outlier_factor"]');
  await expect(missing).toBeVisible();
  await expect(missing.locator(".model-metrics")).not.toContainText("Raw model score");
  await expect(missing.locator(".hist-bar-selected")).toHaveCount(0);
  await expect(missing.locator(".hist-bar-threshold")).toHaveCount(1);

  await page.screenshot({ path: `${SHOTS}/histogram-zero-and-missing.png`, fullPage: true });
});
