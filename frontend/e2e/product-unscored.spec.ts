import { expect, test } from "@playwright/test";
import { analysis, fixtureApi, id, tender } from "./completion-fixtures";

test("MOCKED | an unscored procedure reports unavailable model scores", async ({ page }) => {
  await fixtureApi(page);
  await page.route(`**/api/tenders/${id}`, route => route.fulfill({ json: {
    ...tender, risk_score: null, risk_level: "unscored", n_models_flagging: null,
    model_flags: {}, consensus_flag: null,
  } }));
  await page.route(`**/api/tenders/${id}/model-analysis`, route => route.fulfill({ json: {
    ...analysis, summary_matches_run: false, n_reference: 0, agreement: [],
    consensus: { n_models_flagging: null, flag: null, band: "unscored", percentile: null },
    detectors: analysis.detectors.map(item => ({
      ...item, verdict: "unavailable", score: null, n_reference: 0, score_percentile: null, bins: [], threshold: null,
    })),
  } }));
  await page.goto(`/tenders/${id}`);
  await expect(page.getByText("Model scores are unavailable for this procurement.")).toBeVisible();
  await expect(page.locator(".model-vote-table tbody tr")).toHaveCount(4);
  await expect(page.locator(".model-vote-table tbody tr").first().locator("td").first()).toHaveText("—");
});
