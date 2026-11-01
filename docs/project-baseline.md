# TravelMind 项目认知基线

> 整理自根目录 `PROJECT_BASELINE.md`，2026-08-04 合并；代码根目录为 `my-langgraph-agent-main/`。
> 原文件更新时间：2026-07-31；当前工作树复核时间：2026-08-24。

## 1. 一句话定位

TravelMind 是一个基于 Python、FastAPI、LangGraph、FastMCP、高德 Web 服务和 DeepSeek 的结构化旅行规划工作台。产品把用户的出行条件转换为天气、跨城交通、目的地内交通、POI、酒店、预算、每日行程、地图和 Markdown 结果，并在页面中支持追问与行程编辑。

当前用户端主链路是结构化表单 + `/api/plan-async`（SSE 真实进度，2026-09-05 起；无 EventSource 或任务未启动时回退同步 `/api/plan`）；追问优先走 `/api/refine-plan`（结构化增量修改），失败或无计划时回退 `/api/multi-agent-chat` 文本链路。

当前阶段：Phase 0-5 已完成（Phase 2 于 2026-09-05 通过真实验收关闭；Phase 5 的 5.1 SQLite 持久化、5.2 幂等/超时/脱敏、5.3 SSE 真实进度、5.4 结构化 trace 落库、5.5 Playwright E2E 与 5.6 发布质量门均已落地，5.5/5.6 于 2026-11-01 收尾，提交 `9e5353c`）。Phase 2.5 保持可选实验支线（唯一硬前置为 D1 连接复用）。

## 2. 当前仓库状态

- 分支：`main`（本地 feat/docs 提交成对推进；远端同步状态以 `git status` 为准，2026-09-05 已推送至 `64c33f9`）
- 近期关键提交（均 2026-09-05）：`f464e7c`（SSE 真实进度）、`67aa8c9`（SQLite 持久化）、`360c611`（Phase 4 结构化追问）、`1414e06`（Phase 3 预算循环）、`05def10`（D11）、`029ef20`（D2）、`dfb5a5b`（D12）
- 认知与执行文档现位于 `docs/`（2026-08-04 整理后），根目录同名文件为历史留档。
- 工作区仅剩 `.dsh/` 本地技能资产未跟踪（保持在产品提交之外）。V3 已于 2026-08-24 按废案删除；结构化 MCP 原型已按 D12 完成并提交（2026-09-05）。

## 3. 架构总览

```mermaid
flowchart LR
    U[用户表单] --> W[FastAPI Web]
    W --> P[StructuredTravelPlanner]
    P --> M[MCPToolAdapter]
    M --> S[FastMCP Server]
    S --> A[高德天气/地理编码/路线/POI]
    S --> F[备用天气源与本地知识库]
    P --> D[DeepSeek 规划/评审/价格常识]
    P --> R[规则归一化与降级]
    P --> O[结构化计划 JSON]
    O --> V[Web 结果页/地图/编辑/导出]
    Q[右侧追问] --> C[/api/multi-agent-chat]
    C --> MA[确定性多 Agent 编排]
    MA --> M
```

### 主规划链路

`/api/plan` 在一次请求内依次处理：

1. 偏好归一化：城市、日期、天数、人数、预算、交通模式、住宿档位、偏好画像以及自由文本约束摘要。
2. 天气与穿衣、防晒、雨天、风力建议。
3. 跨城交通：高铁/城际、自驾，按距离策略补充飞机候选。
4. 景点、美食、特色店铺和酒店 POI。
5. POI/酒店片区聚类与住宿匹配理由。
6. 旧文本事实归一化、真实地点/坐标/重复/排除项过滤和可解释候选排序；`candidate_contracts` 已在 `run()` 接线产出（2026-09-05，D2 完成）。
7. 目的地内推荐模式和相邻真实地点之间的路线段。
8. DeepSeek 结构化行程；服务不可用或输出不合规时采用规则行程。
9. 行程质量体检：路线、节奏、片区、返程和预算；需要时最多返工一次。
10. 市内路线段补齐、地点替换和不可行路线标记。
11. 地图点位、预算拆分和 Markdown 方案生成。

## 4. 目录职责

| 路径 | 职责 | 当前定位 |
|---|---|---|
| `sync/travel_web_app.py` | FastAPI 应用、三条 API、静态地图代理、单 Agent 初始化 | 当前 Web 入口 |
| `sync/fastmcp_server_streamhttp.py` | FastMCP HTTP Server、高德调用、缓存限速、备用数据、文件输出 | 当前 MCP 入口 |
| `sync/mcp_tools_adapter.py` | FastMCP Client、`MCPToolResult` 稳定封装、`call_mcp_tool`/`call_mcp_tool_result` 双 API 与 LangChain 工具包装；构造参数接受 FastMCP 实例支持内存直连 | 连接层，D12 已闭环（2026-09-05） |
| `sync/multi_agent/structured_planner.py` | 结构化规划编排器（约 660 行），业务逻辑已拆分到同目录 20 个模块 | 当前核心业务模块 |
| `sync/multi_agent/contracts.py` | 地点、酒店、路线、天气和来源元数据 Contract，含 `stable_place_id` 稳定 id | Phase 2 事实边界 |
| `sync/multi_agent/fact_normalizer.py` | 将旧文本解析结果归一化为 JSON-safe 事实 | Phase 2 兼容层 |
| `sync/multi_agent/candidate_ranker.py` | 候选硬过滤、评分、排序和入选/落选理由 | Phase 2 纯逻辑层 |
| `sync/multi_agent/deepseek_contracts.py` | DeepSeek 四类输出的 Pydantic 契约与类型归一化 | Phase 2.5 强 schema 校验基础 |
| `sync/multi_agent/structured_result.py` | POI/酒店 Pydantic 响应模型、坏元素过滤解析（`parse_poi_response`/`parse_hotel_response`）与 `validation_error` 回填 | Phase 2.2/D12 已完成（2026-09-05） |
| `sync/multi_agent/*.py` | 状态模型、偏好 Agent、事实 Agent、Writer 和旧多 Agent 编排 | 追问/兼容链路 |
| `web/index.html` | 工作台骨架（v2 版）、表单、结果区、追问区 | 唯一页面入口 |
| `web/app.js` | 请求、状态恢复、结果渲染、编辑、预算重算、导出 | 当前前端逻辑 |
| `web/styles.css` | 页面布局、结果模块、响应式和打印样式 | 当前视觉样式 |
| `tests/test_travelmind_regression.py` | 规划器和前端契约回归 | 当前测试入口 |
| `tests/evals/` | 离线评测场景、fixture、指标和报告；`release_gate.py` 发布质量门 | 效果护栏 |
| `tests/e2e/` | Playwright 端到端：`fixture_server.py` 离线 fixture 服务 + 桌面/移动两个 project 的 spec | 用户流程护栏 |
| `async/` | 独立异步 ReAct/MCP/用户 API 示例 | 遗留实验区 |
| `docs/` | 合并后的文档体系与历史归档 | 认知入口 |

## 5. 后端接口契约

### `POST /api/plan`

请求字段来自页面表单：

```json
{
  "originCity": "广州",
  "destinationCity": "深圳",
  "startDate": "2026-08-01",
  "days": 2,
  "travelers": 1,
  "budget": 800,
  "intercityModes": ["高铁/动车/城际", "自驾"],
  "localModes": ["公共交通", "打车", "步行"],
  "hotelLevel": "舒适",
  "interests": ["经典景点", "美食", "地方特色"],
  "freeText": "不要安排夜间活动，优先室内场所",
  "hardConstraints": [],
  "softPreferences": ["旅行节奏：标准", "住宿策略：近地铁枢纽"],
  "preferenceProfile": {
    "pace": "标准",
    "maxTransferMinutes": 45,
    "hotelStrategy": "近地铁枢纽",
    "learnedHints": []
  }
}
```

主要响应字段：`plan_id`、`preferences`、`intercity_transport`、`local_transport`、`hotels`、`weather`、`weather_advice`、`pois`、`candidate_contracts`、`map`、`budget`、`budget_adjustments`、`itinerary_days`、`quality_review`、`markdown`、`trace`、`planning_mode`、`llm_status`。Phase 1 新增的可选结果包括 `preferences.freeText`、`preferences.hardConstraints`、`preferences.softPreferences`、`preferences.constraintSummary` 和 `quality_review.constraints`；Phase 2 新增可选 `candidate_contracts`（2026-09-05 已在 `run()` 接线，见工程债务 D2），旧 `pois`/`hotels` 字段继续保留；Phase 3 新增可选 `budget_adjustments`（同步写 `budget.adjustments`）与 `quality_review.gate_violations`（2026-09-05）。

`constraintSummary` 按 `hard`、`soft`、`unknown` 分组；每项保留 `id`、`kind`、`text`、`source`。质量评审逐项给出 `satisfied`、`violated` 或 `unknown`，并附 `evidence`。

`llm_status` 为结果语义（`used`/`unavailable`/`schema_failed`/`call_failed`，成功含重试后成功恒为 `used`）；降级细节（`error_kind`/`attempt_count`/`fallback_reason`）与五态 trace（`used/retry_success/schema_failed/call_failed/rule_fallback`）随 `trace` 字段返回（2026-09-05，D11）。

`candidate_contracts` 计划版本为 `travelmind-candidate-v1`，来源模式为 `legacy_text_compatible`；包含 POI/酒店入选候选及其 `selection.score/reasons` 评分理由、`source_meta` 来源元数据和 `cluster` 片区标注（2026-09-05 已在 `run()` 接线产出）；过滤落选原因暂不输出，D3 做前端来源/落选展示时再定结构。MCP Server 的供应商返回仍是旧文本。

每日 item 重点字段：`title`、`location`、`address`、`category`、`is_real_place`、`place_source`、`location_point`、`map_included`、`cost_estimate`、`cost_source`、`arrival_transport_segment`。

### `POST /api/multi-agent-chat`

请求为 `{ "message": "..." }`。流程是 `PreferenceAgent` 解析 -> 线程池并行调用天气/路线/POI/预算 Agent -> `WriterAgent` 生成 Markdown。响应包含 `answer`、`trace` 和 `agent_steps`。

### `POST /api/chat`

旧 LangGraph ReAct 单 Agent 入口。模型先决定是否调用工具，工具结果返回后继续图循环，最终维护会话历史并返回 Markdown/文本答案。

### 其他接口

- `GET /api/tools`：读取当前单 Agent 的工具清单，依赖 DeepSeek 和 MCP 初始化。
- `GET /api/map-static`：用高德静态地图生成 PNG；Key 缺失、请求失败或限流时返回 SVG 示意图。
- `POST /api/plan-async`：异步规划入口（Phase 5），立即返回 `task_id`；`clientRequestId` 幂等（running/done 重放已有任务，不重复外部调用）；`TRAVELMIND_PERSISTENCE=off` 时 503。
- `GET /api/plan-events/{task_id}`：SSE 事件流（step_start/step_end/done/error），以 `task_events` 表为唯一事实源，断线按 Last-Event-ID 重放续传。
- `GET /api/task/{task_id}`：任务状态查询（断线可查）；done 时携带计划快照。
- `POST /api/refine-plan`：结构化追问（Phase 4），携带完整计划 + 追问文本；失败原样返回不覆盖计划；`TRAVELMIND_REFINE=off` 时 503。
- `POST /api/reset`：清空旧单 Agent 的会话历史。

## 6. MCP 工具与事实来源

同步 MCP Server 当前暴露：

- `get_current_time`
- `get_weather`
- `amap_geocode`
- `amap_plan_routes`
- `plan_route`
- `search_poi`
- `search_hotels`
- `estimate_budget`
- `write_itinerary_file`

高德调用集中经过缓存、最小请求间隔、QPS 错误识别和退避重试。天气优先高德，随后使用 `wttr.in`；POI 与酒店优先高德，随后使用本地知识或规则。

适配器把每次工具调用收敛为 `MCPToolResult` 稳定封装（`text` 恒可用、结构化 `data`、`source` 与 `validation_error`）；工具箱提供 `call_text()`（恒字符串）/`call_structured()`（显式取数据）双访问。当前 MCP 工具仍返回文本，结构化消费路径由 `tests/test_mcp_protocol.py` 的内存 FastMCP 协议级测试保障。

铁路、航班、酒店库存当前是供应商占位适配器：页面展示策略候选和参考区间，实时车次、航班号、库存和可预订价需要后续接入正式供应商。

## 7. 运行方式

环境：Windows + PowerShell + `.venv`。核心配置为 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`AMAP_MAPS_API_KEY` 和 `MCP_SERVER_URL`。

```powershell
$env:MCP_PORT='8098'
.\.venv\Scripts\python.exe sync\fastmcp_server_streamhttp.py

$env:MCP_SERVER_URL='http://127.0.0.1:8098/my-custom-path'
.\.venv\Scripts\python.exe -m uvicorn sync.travel_web_app:app --host 127.0.0.1 --port 8010
```

访问：`http://127.0.0.1:8010/`

配置注意：当前产品 Web 和同步 FastMCP Server 的默认端口已统一为 `8098`，路径为 `/my-custom-path`。`8083` 只残留在遗留 `sync/agent_chatbot_LCEL.py` 和适配器命令行示例；运行时仍建议显式设置 `MCP_SERVER_URL`，避免遗留入口或外部环境覆盖造成漂移。

## 8. 前端行为

- 初始状态显示结构化表单、快捷演示、MCP 工具清单和追问区。
- 点击规划后调用 `/api/plan`，显示 8 个阶段的前端进度。
- 结果页将每日行程放在主体位置，路线、精选 POI、地图、住宿、预算和天气作为支持模块。
- 表单包含"补充要求"输入；生成结果后质量体检区域显示逐条约束状态和证据。
- `localStorage` 保存当前计划、追问、活动标签和轻量偏好；旧快照缺字段时进行归一化和提示。
- 编辑模式支持每日活动上移、下移和删除，之后在浏览器端重建相邻地点路线、预算和 Markdown。
- 导出是两级菜单：`#exportButton` 只切换 `#exportMenu` 的显隐，Markdown 下载与打印/保存 PDF 由菜单内按钮触发。
- 追问可继续修改偏好，但其响应仍来自旧的 `/api/multi-agent-chat` 文本链路。
- 760px 以下进入纵向布局；桌面结果生成后左侧输入区收缩为行程目录。

## 9. 已验证结果

最近复核：2026-11-01

```text
Python 全量 py_compile（sync/async/tests）：通过
node --check web/app.js：通过
python -m unittest discover -s tests -q：220 个通过
发布质量门（tests.evals.release_gate，参照 phase3_report.json）：通过，关键指标无回退
Playwright E2E（npx playwright test）：11 通过 / 1 跳过，3.1 分钟
pip check：通过
git diff --check：通过
```

E2E 覆盖桌面（1280x720）与移动（iPhone 14 视口）两个 project：规划主流程（真实 SSE 进度驱动 + 控制台 0 错误）、编辑行程删除条目并导出 Markdown、SSE error 事件错误态、无 EventSource 时回退同步端点、结构化追问与版本徽标、移动视口无横向溢出。桌面会跳过移动专属的溢出断言，因此 12 个运行中 1 个为 skipped。全部走 `tests/e2e/fixture_server.py`（生产 app + 离线 fixture planner），零 API Key、零网络、零日期依赖。

2026-09-05 复核（历史记录）：离线受控路径 209/209、评测 5/5（139 次调用/4 次 fixture 失败）、真实验收见 findings.md（高德成功场景 24 个真实 POI + 契约输出正确 quality 72；Key 缺失降级场景真实地点护栏守住 quality 65；DeepSeek 五态真实基线 used=2/其余 0；桌面浏览器主流程完整渲染且控制台 0 错误）。

本次探测到 8010 和 8098 均没有监听进程，未进行真实 MCP/高德/DeepSeek 请求或浏览器端到端截图验证。当前 `220/220` 与 E2E 全绿证明离线受控路径、内存 FastMCP 协议级往返与浏览器端到端（离线 fixture）稳定，不代表真实供应商调用已验证。

2026-09-05 真实验收补充（详见 findings.md 验收记录）：真实高德成功场景 24 个真实 POI + 契约输出正确（quality 72）；Key 缺失降级场景真实地点护栏守住、`candidate_contracts` 不放行不可定位项（quality 65）；DeepSeek 五态真实基线 used=2/其余 0（3 次真实规划）；桌面浏览器主流程完整渲染且控制台 0 错误。移动端视口遗留 Phase 5。

2026-09-05 Phase 3 补充：预算反馈循环与硬质量门默认开启（`TRAVELMIND_BUDGET_LOOP=off` 可回滚）；评测重定基线 139 次调用，**预算偏差 0.6230 → 0.4897**，low_budget 927 元（原 ~1451）、return_transfer_isolation 转预算内；`budget_adjustments`/`gate_violations` 字段与前端/Markdown 展示详见 findings.md。

2026-09-05 Phase 4 补充：新增 `POST /api/refine-plan`（携带完整计划 + 追问，无状态）；追问解析为 7 类增量操作（铁律：模型只引用 item_id/候选 candidate_id，后端逐条校验）；计划新增 `version/parent_version/refine_history/constraint_snapshot` 字段，响应含结构化 diff 与 explanation；失败追问原样返回不覆盖计划；旧 `/api/multi-agent-chat` 保留为回退链路（前端自动回退并标注）；`TRAVELMIND_REFINE=off` 为服务端回滚开关。详见 findings.md Phase 4 小节。

2026-09-05 Phase 5 补充（部分）：SQLite 持久化（计划快照/偏好/任务事件/评测摘要，入库脱敏，`TRAVELMIND_PERSISTENCE=off` 回滚）；SSE 真实进度（`/api/plan-async` + `/api/plan-events/{task_id}` + `/api/task/{task_id}`，DB 单一事实源，Last-Event-ID 续传，刷新可恢复，clientRequestId 幂等）；前端进度条由真实 step_start/step_end 事件驱动（15 后端步骤映射 8 阶段），回退矩阵保证任务启动后绝不重复外部调用。详见 findings.md Phase 5 小节。5.5 Playwright E2E 与 5.6 发布质量门进行中。

## 10. 后续开发的优先关注点

1. [已完成 2026-09-05] Phase 2 收尾：D12（`dfb5a5b`）、D2（`029ef20`）、D11（`05def10`）+ 真实验收（高德成功/降级、DeepSeek 五态基线、桌面浏览器主流程 0 控制台错误）；移动端视口遗留 Phase 5。
2. [已完成 2026-09-05] Phase 3：确定性预算反馈循环（三杠杆、轮上限 2、可解释调整记录）+ 硬质量门（独立 gate_violations 字段）；预算偏差 0.6230 → 0.4897；评测基线重定为 139 次调用。
3. [已完成 2026-11-01] Phase 5：5.1 持久化（`67aa8c9`）、5.2 幂等/超时/脱敏、5.3 SSE 真实进度（`f464e7c`）、5.4 结构化 trace 落库、5.5 Playwright E2E 与 5.6 发布质量门（`9e5353c`）全部落地，产品主线 Phase 0-5 无未关闭阶段。Phase 2.5 保持可选实验（前置 D1 连接复用）。长期维护项包括前端请求超时（同步路径已修，其余 fetch 待补）、遗留端口示例清理和 `structured_planner.py` 兼容桥接收敛；观察项见 findings.md（降级 POI source 标签、DeepSeek 路径约束评审、示例酒店进契约、low_budget/family_budget 需供应商接入才能完全达标）。

## 11. 维护入口速查

- 改 API 或静态地图：`sync/travel_web_app.py`
- 改高德/备用工具：`sync/fastmcp_server_streamhttp.py`
- 改结构化规划和规则：`sync/multi_agent/structured_planner.py`
- 改追问多 Agent：`sync/multi_agent/orchestrator.py` 及同目录 Agent
- 改页面骨架：`web/index.html`
- 改前端状态和结果：`web/app.js`
- 改视觉与响应式：`web/styles.css`
- 改回归契约：`tests/test_travelmind_regression.py`
- 改离线评测：`tests/evals/`
