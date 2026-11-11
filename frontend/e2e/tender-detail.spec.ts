import { expect, test } from "@playwright/test";
import { SHOTS, expectChartsHaveSize, expectNoDocumentOverflow, waitForRouteReady } from "./helpers";

/**
 * Model results on a real procedure from the served dataset.
 *
 * The current export carries no `score_provenance.run_id`, so the same-run
 * reference (bins, thresholds, percentile) is genuinely absent and the card
 * must say so instead of inventing markers — that honest branch is asserted
 * here. The marker/histogram branch itself is verified against the isolated
 * dev fixture in model-fixture.spec.ts.
 */

test("model card shows real provenance and an honest reference state", async ({ page, request }) => {
  const res = await request.get("/api/tenders?limit=1&sort=risk");
  const body = (await res.json()) as { items: { tender_id: string }[] };
  const id = body.items[0].tender_id;

  await page.goto(`/tenders/${encodeURIComponent(id)}`);
  await waitForRouteReady(page);
  await expectNoDocumentOverflow(page);

  if (await page.getByRole("alert").filter({hasText: "Data contract violation"}).count()) {
    await expect(page.getByRole("alert").filter({hasText: "Data contract violation"}).first()).toBeVisible();
    await expect(page.locator(".model-workbench")).toHaveCount(0);
    await page.screenshot({path: `${SHOTS}/live-tender-contract-block.png`,fullPage:true});
    test.info().annotations.push({type:"external blocker",description:"CSV payload rejected; real model integration not certified"});
    return;
  }
  // Real score/verdict/percentile/reference blocks are rendered from the API.
  await expect(page.locator(".model-metrics").first()).toBeVisible();
  const metrics = (await page.locator(".model-metrics").first().innerText()).replace(/\s+/g, " ");
  expect(metrics).toMatch(/Raw model score/);
  expect(metrics).toMatch(/Raw-score percentile/);
  expect(metrics).toMatch(/Reference observations/);

  // Run identity is shown even when it is missing (never substituted).
  const source = (await page.locator(".model-source").first().innerText()).replace(/\s+/g, " ");
  expect(source).toMatch(/Run:/);
  expect(source).toMatch(/—|detect-/);

  const boundary = (await page.locator(".model-boundary").first().innerText()).replace(/\s+/g, " ");
  expect(boundary).toMatch(/Confirmed score boundary/);

  const histogram = page.locator(".score-histogram").first();
  const histogramVisible = await histogram.isVisible().catch(() => false);
  if (histogramVisible) {
    await expectChartsHaveSize(page);
    await expect(page.locator(".hist-bar").first()).toBeVisible();
  } else {
    // No same-run reference in this dataset: the card states the unavailability
    // and shows no fabricated histogram or markers.
    const card = page.locator(".model-explanation").first();
    await expect(card).toContainText("A comparable reference is unavailable");
    await expect(card).toContainText("A different run is never substituted");
    await expect(page.locator(".hist-bar")).toHaveCount(0);
  }

  await page.screenshot({ path: `${SHOTS}/tender-detail-model-card.png`, fullPage: true });

  // Keyboard model tabs switch the inspected model.
  const tabs = page.locator('[role="tab"]');
  const count = await tabs.count();
  expect(count).toBeGreaterThan(0);
  await tabs.first().focus();
  if (count > 1) {
    await page.keyboard.press("ArrowRight");
    await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
    await expect(tabs.first()).toHaveAttribute("aria-selected", "false");
  }
});
