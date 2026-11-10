import { expect, test } from "@playwright/test";
import { SHOTS, expectNoDocumentOverflow, waitForRouteReady } from "./helpers";

/**
 * RU / RO / EN and light / dark across the analytical routes: no overflow,
 * correct <html lang>, visible translations, themed charts.
 */

const LANGS: { code: "en" | "ru" | "ro"; probe: RegExp }[] = [
  { code: "en", probe: /Distributions|Scored tenders|Overview/ },
  { code: "ru", probe: /Распределения|Процедуры|Обзор/ },
  { code: "ro", probe: /Distribuții|Proceduri|Prezentare/ },
];

const ROUTES = ["/", "/tenders", "/distributions", "/network", "/models"];

for (const lang of LANGS) {
  for (const theme of ["light", "dark"] as const) {
    test(`${lang.code} / ${theme}: routes render translated and themed`, async ({ page }) => {
      await page.addInitScript(
        ([code, mode]) => {
          localStorage.setItem("mtender_lang", code as string);
          localStorage.setItem("mtender-theme", mode as string);
        },
        [lang.code, theme] as const,
      );

      for (const route of ROUTES) {
        await page.goto(route);
        await waitForRouteReady(page);
        await expect(page.locator("html")).toHaveAttribute("lang", lang.code);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.locator("body")).toContainText(lang.probe);
        await expectNoDocumentOverflow(page);
        // Text zoom (200%) must not create a horizontal scrollbar either.
        await page.evaluate(() => {
          document.documentElement.style.fontSize = "200%";
        });
        await page.waitForTimeout(200);
        await expectNoDocumentOverflow(page);
        await page.evaluate(() => {
          document.documentElement.style.fontSize = "";
        });
      }

      if (theme === "dark") {
        await page.goto("/distributions");
        await waitForRouteReady(page);
        await page.screenshot({ path: `${SHOTS}/i18n-${lang.code}-dark.png` });
      }
    });
  }
}
