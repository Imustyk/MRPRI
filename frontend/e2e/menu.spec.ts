import { expect, test } from "@playwright/test";
import { SHOTS, expectNoDocumentOverflow, waitForRouteReady } from "./helpers";

test.describe("mobile menu", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("Tab/Shift+Tab stay inside the drawer, Escape closes and returns focus", async ({
    page,
  }) => {
    await page.goto("/");
    await waitForRouteReady(page);
    await expectNoDocumentOverflow(page);

    const toggle = page.locator("button.menu-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const sidebar = page.locator("#app-sidebar");
    await expect(sidebar).toHaveAttribute("role", "dialog");
    // Focus lands inside the drawer (close button).
    await expect(page.locator("button.drawer-close")).toBeFocused();
    await page.screenshot({ path: `${SHOTS}/mobile-menu-open-375.png` });

    // Tab from the last focusable wraps back to the first (focus trap).
    const focusables = sidebar.locator('a[href], button:not([disabled]), [tabindex="0"]');
    const count = await focusables.count();
    expect(count).toBeGreaterThan(2);
    await focusables.last().focus();
    await page.keyboard.press("Tab");
    await expect(focusables.first()).toBeFocused();
    // Shift+Tab from the first wraps to the last.
    await page.keyboard.press("Shift+Tab");
    await expect(focusables.last()).toBeFocused();

    // Escape closes the drawer and returns focus to the toggle.
    await page.keyboard.press("Escape");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toBeFocused();

    // Reopen and follow a link: menu closes and focus moves to the main region.
    await toggle.click();
    await sidebar.getByRole("link", { name: "Procedures" }).click();
    await page.waitForURL(/\/tenders/);
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await page.waitForFunction(() => document.activeElement?.id === "main", undefined, {
      timeout: 5_000,
    });
  });
});
