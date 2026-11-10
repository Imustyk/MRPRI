import { expect, test } from "@playwright/test";
import {
  ROUTES,
  SHOTS,
  WIDTHS,
  expectChartsHaveSize,
  expectNoDocumentOverflow,
  expectTablesScrollInPlace,
  waitForRouteReady,
} from "./helpers";

/**
 * Route × width sweep: no document-level horizontal overflow at any of the
 * required widths, wide tables scroll inside their containers, charts keep a
 * non-zero size after resize. Screenshots of the key routes are kept as
 * evidence in docs/frontend-verification/.
 */
for (const route of ROUTES) {
  test(`no overflow at required widths — ${route}`, async ({ page }) => {
    await page.goto(route);
    await waitForRouteReady(page);

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width < 768 ? 812 : 1000 });
      await page.waitForTimeout(250);
      await expectNoDocumentOverflow(page);
      await expectTablesScrollInPlace(page);
      await expectChartsHaveSize(page);
    }

    // Evidence screenshots at the extremes.
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${SHOTS}/route${route.replace(/\W+/g, "-") || "-overview"}-375.png` });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${SHOTS}/route${route.replace(/\W+/g, "-") || "-overview"}-1440.png` });
    await expectNoDocumentOverflow(page);
  });
}
