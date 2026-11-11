import {fixtureApi, graph} from "./completion-fixtures";
import { expect, test } from "@playwright/test";
import { SHOTS, expectNoDocumentOverflow, waitForRouteReady } from "./helpers";

// Isolated mocked API: these tests verify UI interactions, not live scoring correctness.
test.beforeEach(async ({page})=>{
 await fixtureApi(page);
 const links=Array.from({length:5},(_,i)=>({source:"b1",target:`s${i+1}`,weight:4+i,value:100+i,max_risk:80-i*10}));
 const nodes=[{...graph.nodes[0],awards:30,n_partners:5,degree:5,value:510},...links.map((link,i)=>({...graph.nodes[1],id:link.target,name:`Test supplier ${i+1}`,awards:link.weight,value:link.value,max_risk:link.max_risk}))];
 await page.route("**/api/graph?**",route=>route.fulfill({json:{...graph,nodes,links,stats:{...graph.stats,pairs_all:5,pairs_repeated:5,pairs_qualifying:5,pairs_shown:5,nodes_qualifying:6,nodes_shown:6,awards_qualifying:30,awards_shown:30,value_qualifying:510,value_shown:510}}}));
});

/**
 * Network accessibility: mouse, keyboard and touch share one selection path.
 * The sortable table (focusable rows) and the drill-down list are the
 * non-canvas routes; the canvas is never required to operate the view.
 */

test("MOCKED | keyboard reaches the same selection as the mouse via the accessible table", async ({
  page,
}) => {
  await page.goto("/network");
  await waitForRouteReady(page);
  await expectNoDocumentOverflow(page);

  const rows = page.locator("table.sortable tbody tr");
  await expect(rows.first()).toBeVisible();
  const rowCount = await rows.count();
  // A bounded number of tab stops — not one per node of the graph.
  expect(rowCount).toBeLessThanOrEqual(100);

  // Mouse path: click a row selects it.
  await rows.nth(1).click();
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");

  // Keyboard path: focus another row, press Enter → identical selection.
  await rows.nth(2).focus();
  await page.keyboard.press("Enter");
  await expect(rows.nth(2)).toHaveAttribute("aria-current", "true");
  await expect(rows.nth(1)).not.toHaveAttribute("aria-current", "true");

  // Space works the same way.
  await rows.nth(3).focus();
  await page.keyboard.press(" ");
  await expect(rows.nth(3)).toHaveAttribute("aria-current", "true");

  // The drill-down list is an accessible, non-canvas route to the details:
  // the matrix axis labels are focusable buttons (mouse click ≡ Enter/Space).
  const axisCell = page.locator('.net-axis[role="button"]').first();
  await axisCell.focus();
  await page.keyboard.press("Enter");
  const drill = page.locator("details.net-drill-list");
  await expect(drill).toBeVisible({ timeout: 15_000 });
  await drill.locator("summary").click();
  await expect(drill.locator("ul li").first()).toBeVisible();

  // Sorting is reachable by keyboard from the table header.
  const sortButton = page.locator("table.sortable thead button").first();
  await sortButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("table.sortable thead th").first()).toHaveAttribute(
    "aria-sort",
    /ascending|descending/,
  );

  await page.screenshot({ path: `${SHOTS}/network-keyboard-selection.png` });
});

test("MOCKED | touch-equivalent path: tapping a row selects it too", async ({ page }) => {
  await page.goto("/network");
  await waitForRouteReady(page);
  const rows = page.locator("table.sortable tbody tr");
  await rows.nth(1).tap();
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
});
