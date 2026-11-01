import { test, expect } from "@playwright/test";

test("追问触发结构化 refine 并显示版本徽标", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Plan My Trip" }).click();
  await expect(page.locator("#budgetSection")).toBeVisible({ timeout: 60_000 });

  const panel = page.locator(".followup-panel");
  const isOpen = await panel.evaluate((el) => (el as HTMLDetailsElement).open);
  if (!isOpen) {
    await panel.locator("summary").click();
  }

  // E2EBrain 固定把追问解析为 adjust_budget 操作（确定性 refine 路径）。
  await page.locator("#followupInput").fill("预算改为 2000 元");
  await page.locator("#followupForm button.send-button").click();

  await expect(page.locator(".bubble", { hasText: "计划已更新到 v" })).toBeVisible({
    timeout: 60_000,
  });
});
