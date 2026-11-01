import { test, expect } from "@playwright/test";

test("编辑行程删除条目并导出 Markdown", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Plan My Trip" }).click();
  await expect(page.locator("#daysSection")).toBeVisible({ timeout: 60_000 });

  // 进入编辑模式，删除第一个条目，卡片数减一。
  await page.locator("#editPlanButton").click();
  const cards = page.locator(".activity-card");
  const before = await cards.count();
  expect(before).toBeGreaterThan(0);
  await cards.first().locator('[data-action="delete"]').click();
  await expect(page.locator(".activity-card")).toHaveCount(before - 1);

  // 导出是两级菜单：#exportButton 只切换 #exportMenu 的 hidden，
  // 真正触发 Blob 下载的是菜单内 [data-export="markdown"]（app.js exportMenu 委托）。
  await page.locator("#exportButton").click();
  await expect(page.locator("#exportMenu")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.locator('#exportMenu [data-export="markdown"]').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.md$/);
});
