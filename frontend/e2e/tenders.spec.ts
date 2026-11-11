import {fixtureApi, id as fixtureId} from "./completion-fixtures";
import { expect, test } from "@playwright/test";
import { SHOTS, waitForRouteReady } from "./helpers";

test.beforeEach(async ({page})=>fixtureApi(page));

/**
 * The URL is the state of /tenders: search + filters + page survive opening a
 * tender and coming Back, plus reload, shared links, Back/Forward and invalid
 * parameter normalisation.
 */

async function firstTenderId(_request: import("@playwright/test").APIRequestContext) { return fixtureId; }

test("MOCKED | filters and page survive open → back, and a reload keeps them too", async ({
  page,
  request,
}) => {
  const id = await firstTenderId(request);
  await page.goto("/tenders");
  await waitForRouteReady(page);

  // Search (debounced), band filter, minimum percentile, then next page.
  await page.locator("#f-q").fill("a");
  await page.locator("#f-level").selectOption("high");
  await page.getByText("More filters", { exact: true }).click();
  await page.locator("#f-risk").fill("30");
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: "Next" }).click();
  await page.waitForURL(/offset=40/);

  const before = new URL(page.url());
  expect(before.searchParams.get("q")).toBe("a");
  expect(before.searchParams.get("level")).toBe("high");
  expect(before.searchParams.get("min")).toBe("30");
  expect(before.searchParams.get("offset")).toBe("40");

  // Open the first procedure from the table.
  await page.locator("table tbody tr a").first().click();
  await page.waitForURL(/\/tenders\//);
  await waitForRouteReady(page);
  await expect(page.locator("h1")).toBeVisible();

  // Back: same search, band, percentile and page — no context lost.
  await page.goBack();
  await waitForRouteReady(page);
  const after = new URL(page.url());
  expect(after.searchParams.get("q")).toBe("a");
  expect(after.searchParams.get("level")).toBe("high");
  expect(after.searchParams.get("min")).toBe("30");
  expect(after.searchParams.get("offset")).toBe("40");
  await expect(page.locator("#f-q")).toHaveValue("a");
  await expect(page.locator("#f-level")).toHaveValue("high");
  await expect(page.locator("#f-risk")).toHaveValue("30");
  await page.waitForSelector("table tbody tr");

  // Reload restores exactly the same view (shared-link scenario).
  await page.reload();
  await waitForRouteReady(page);
  const reloaded = new URL(page.url());
  expect(reloaded.searchParams.get("q")).toBe("a");
  expect(reloaded.searchParams.get("level")).toBe("high");
  expect(reloaded.searchParams.get("offset")).toBe("40");
  await expect(page.locator("#f-q")).toHaveValue("a");
  await page.screenshot({ path: `${SHOTS}/tenders-filters-restored.png` });

  // The detail route with a known id also resolves directly.
  await page.goto(`/tenders/${encodeURIComponent(id)}`);
  await waitForRouteReady(page);
  await expect(page.locator("h1")).toBeVisible();
});

test("MOCKED | Back steps a page push; a filter edit resets the page", async ({ page }) => {
  await page.goto("/tenders");
  await waitForRouteReady(page);
  await page.waitForSelector("table tbody tr");

  await page.locator("#f-level").selectOption("medium");
  await page.waitForURL(/level=medium/);
  await page.getByRole("button", { name: "Next" }).click();
  await page.waitForURL(/offset=40/);

  // Back returns to the entry without the pushed page, keeping the filter.
  await page.goBack();
  await page.waitForFunction(() => !new URL(location.href).searchParams.has("offset"));
  expect(new URL(page.url()).searchParams.get("level")).toBe("medium");

  // Forward restores the page.
  await page.goForward();
  await page.waitForFunction(() => new URL(location.href).searchParams.has("offset"));
  expect(new URL(page.url()).searchParams.get("level")).toBe("medium");

  // Changing a filter clears the offset (page reset on filter change).
  await page.locator("#f-level").selectOption("high");
  await page.waitForFunction(() => {
    const p = new URL(location.href).searchParams;
    return p.get("level") === "high" && !p.has("offset");
  });
});

test("MOCKED | invalid URL parameters are normalised without a history stop", async ({ page }) => {
  await page.goto("/tenders?level=xyz&min=abc&offset=12");
  await page.waitForFunction(() => {
    const s = location.search;
    return !s.includes("level=xyz") && !s.includes("min=abc") && !s.includes("offset=12");
  });
  // Everything was invalid → the URL is clean and no error is shown.
  expect(new URL(page.url()).search).toBe("");
  await page.waitForSelector("table tbody tr");
  await expect(page.locator(".error-note, [role=alert]")).toHaveCount(0);
});
