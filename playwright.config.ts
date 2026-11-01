import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT || 8020);
const BASE_URL = `http://127.0.0.1:${PORT}`;

/**
 * E2E 走 tests/e2e/fixture_server.py（生产 app + 离线 fixture planner），
 * 单进程 webServer、零真实 Key/网络依赖。MCP Server 的 streamable-http
 * 端点对普通 GET 返回 406，无法作为 webServer 就绪探测目标——因此不采用
 * 双 webServer 方案（详见 docs/findings.md Phase 5 小节）。
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium-desktop",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium-mobile",
      // iPhone 14 视口 390x844——覆盖 Phase 2 真实验收遗留的移动端缺口。
      // 注意：devices["iPhone 14"] 默认 defaultBrowserType=webkit，
      // 本项目只装 chromium，必须显式覆盖为 chromium 移动仿真。
      use: { ...devices["iPhone 14"], defaultBrowserType: "chromium" },
    },
  ],
  webServer: {
    // Windows cmd.exe 不认正斜杠的命令路径（会把 /Scripts 当开关解析），必须用反斜杠。
    command: ".venv\\Scripts\\python.exe tests\\e2e\\fixture_server.py",
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
