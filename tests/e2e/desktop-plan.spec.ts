import { test, expect } from "@playwright/test";

// favicon 404 等浏览器噪音不计入控制台错误断言。
const IGNORED_CONSOLE_PATTERNS = [/favicon/i];

test("规划主流程：真实进度事件驱动并完成渲染", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !IGNORED_CONSOLE_PATTERNS.some((p) => p.test(msg.text()))) {
      consoleErrors.push(msg.text());
    }
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await page.goto("/");
  // 默认表单已填广州→深圳 2 天；直接提交。
  await page.getByRole("button", { name: "Plan My Trip" }).click();

  // 进度区出现（SSE 真实事件驱动，fixture 后端毫秒级完成）。
  await expect(page.locator("#planningProgress")).toBeVisible();

  // 结果渲染：预算大盘 + 每日行程 + 标题。
  await expect(page.locator("#budgetSection")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("#daysSection")).toBeVisible();
  await expect(page.getByRole("heading", { name: "深圳旅行计划" })).toBeVisible();

  expect(consoleErrors).toEqual([]);
});
