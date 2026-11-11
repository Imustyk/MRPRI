import { expect, test } from "@playwright/test";

test("LIVE | first-time walkthrough on MTender data and SQLite", async ({ page, request }) => {
  test.skip(process.env.MTENDER_E2E_ISOLATED_WORKSPACE !== "1", "Run against an isolated SQLite workspace.");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    if (!localStorage.getItem("mtender_lang")) localStorage.setItem("mtender_lang", "ru");
  });
  const statsResponse = await request.get("/api/stats");
  expect(statsResponse.ok()).toBe(true);
  const stats = await statsResponse.json();
  expect(stats.n_tenders).toBeGreaterThan(0);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Анализ государственных закупок Молдовы" })).toBeVisible();
  await expect(page.locator(".recharts-wrapper").first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Посмотреть закупки" }).click();
  const first = await request.get("/api/tenders?level=critical&limit=1");
  expect(first.ok()).toBe(true);
  const { items: [tender] } = await first.json();
  expect(tender.ocid).toBeTruthy();

  await page.locator("#f-q").fill(tender.ocid);
  await page.locator("#f-level").selectOption("critical");
  await page.locator("#f-scored").selectOption("true");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody")).toContainText(tender.ocid);
  await page.getByText("Дополнительные фильтры", { exact: true }).click();
  if (tender.published_at) await page.locator("#date_from").fill(tender.published_at.slice(0, 10));
  if (tender.cpv_code) await page.locator("#cpv").fill(tender.cpv_code.slice(0, 2));
  if (tender.award_total_mdl != null) await page.locator("#max_value").fill(String(tender.award_total_mdl));
  const filtered = page.waitForResponse(response => response.url().includes("/api/tenders?") && response.url().includes("date_from"));
  await page.getByRole("button", { name: "Применить фильтры" }).click();
  expect((await filtered).ok()).toBe(true);
  await expect(page.locator("tbody")).toContainText(tender.ocid);
  await page.getByRole("link", { name: /^Подробнее:/ }).click();
  await expect(page.getByRole("heading", { name: "Результат анализа" })).toBeVisible();
  await expect(page.locator(".model-vote-table tbody tr")).toHaveCount(4, { timeout: 60_000 });
  for (const tab of await page.locator(".model-tabs [role=tab]").all()) {
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#case-models [role=tabpanel]")).toBeVisible();
  }
  await expect(page.locator("#case-indicators article").first()).toBeVisible();
  await expect(page.locator("#case-actions a[href^='https://']")).toHaveCount(1);
  if (tender.buyer_id) {
    await page.getByRole("link", { name: "Другие закупки заказчика" }).click();
    await expect(page).toHaveURL(/buyer=/);
    await page.goBack();
  }
  const label = `Проверка Playwright ${Date.now()}`;
  const note = "Сверить дату и условия в первичном извещении.";
  const saved = page.waitForResponse(response => response.url().endsWith("/api/workspace/cases") && response.request().method() === "POST");
  const form = page.locator("#case-actions details").first();
  await form.locator("summary").click();
  await form.getByLabel("Название дела").fill(label);
  await form.getByRole("button", { name: "Сохранить", exact: true }).click();
  const created = await saved;
  expect(created.ok()).toBe(true);
  const savedCase = await created.json();
  let directNoteId: number | undefined;
  try {
    const directNote = "Добавлено из карточки закупки.";
    const noteForm = page.locator("#case-actions details").last();
    await noteForm.locator("summary").click();
    await noteForm.getByLabel("Текст заметки").fill(directNote);
    const direct = page.waitForResponse(result => result.url().endsWith("/api/workspace/annotations") && result.request().method() === "POST");
    await noteForm.getByRole("button", { name: "Сохранить", exact: true }).click();
    const directResponse = await direct;
    expect(directResponse.ok()).toBe(true);
    directNoteId = (await directResponse.json()).id;
    await expect(noteForm.getByRole("status")).toContainText("Заметка сохранена");

    await page.getByRole("link", { name: "Открыть рабочее дело" }).click();
    await expect(page.getByText(directNote, { exact: false })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`case=${savedCase.id}`));
    await expect(page.getByRole("link", { name: tender.ocid, exact: true })).toBeVisible();
    const response = page.waitForResponse(result => result.url().endsWith("/api/workspace/annotations") && result.request().method() === "POST");
    await page.locator("textarea").last().fill(note);
    await page.getByRole("button", { name: "Добавить заметку", exact: true }).click();
    const stored = await response;
    expect(stored.ok()).toBe(true);
    const annotation = await stored.json();
    try {
      await page.reload();
      await expect(page.getByText(note, { exact: false })).toBeVisible();
      await page.getByRole("link", { name: tender.ocid, exact: true }).click();
      await expect(page.getByRole("heading", { name: "Результат анализа" })).toBeVisible();
    } finally {
      expect((await request.delete(`/api/workspace/annotations/${annotation.id}`)).ok()).toBe(true);
    }
  } finally {
    if (directNoteId !== undefined) expect((await request.delete(`/api/workspace/annotations/${directNoteId}`)).ok()).toBe(true);
    expect((await request.delete(`/api/workspace/cases/${savedCase.id}`)).ok()).toBe(true);
  }
  expect(errors).toEqual([]);
});
