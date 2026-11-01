import { test, expect } from "@playwright/test";

test("移动视口：主流程完成且无横向溢出", async ({ page }, testInfo) => {
  // 横向溢出断言只对移动视口有意义（桌面布局存在设计上允许的滚动条差异）。
  // 条件跳转必须在 test 体内写：文件级 test.skip(callback) 的 callback 只收到
  // fixtures，拿不到 testInfo，原先的 ({ }, testInfo) => ... 会直接抛 TypeError。
  test.skip(
    testInfo.project.name !== "chromium-mobile",
    "溢出断言仅在移动视口项目执行",
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Plan My Trip" }).click();
  await expect(page.locator("#budgetSection")).toBeVisible({ timeout: 60_000 });

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
