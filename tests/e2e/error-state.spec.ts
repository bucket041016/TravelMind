import { test, expect } from "@playwright/test";

test("规划失败显示错误态（SSE error 事件路径）", async ({ page }) => {
  await page.goto("/");
  // 错误气泡由 sendPlan 的 catch 写进右侧追问日志，而追问面板默认折叠，
  // 不展开的话 .bubble 只是 attached 而非 visible（与 refine-followup 同一处理）。
  const panel = page.locator(".followup-panel");
  const isOpen = await panel.evaluate((el) => (el as HTMLDetailsElement).open);
  if (!isOpen) {
    await panel.locator("summary").click();
  }

  // freeText 位于折叠的 details 内，先展开再填写。
  await page.locator("#freeText").evaluate((el) => {
    const details = el.closest("details");
    if (details) details.open = true;
  });
  // fixture_server：freeText 命中注入标记时 planner.run 抛错。
  await page.locator("#freeText").fill("__e2e_force_error__");
  await page.getByRole("button", { name: "Plan My Trip" }).click();

  await expect(page.locator(".bubble", { hasText: "请求失败" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.locator("#progressLabel")).toHaveText("规划失败");
});

test("无 EventSource 时回退同步端点并完成规划", async ({ page }) => {
  // 模拟旧浏览器：删除 EventSource 后 sendPlan 必须直接走同步 /api/plan。
  await page.addInitScript(() => {
    delete (window as unknown as { EventSource?: unknown }).EventSource;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Plan My Trip" }).click();
  await expect(page.locator("#budgetSection")).toBeVisible({ timeout: 60_000 });
});
