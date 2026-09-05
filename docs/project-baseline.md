# TravelMind 项目认知基线

> 整理自根目录 `PROJECT_BASELINE.md`，2026-08-04 合并；代码根目录为 `my-langgraph-agent-main/`。
> 原文件更新时间：2026-07-31；当前工作树复核时间：2026-08-24。

## 1. 一句话定位

TravelMind 是一个基于 Python、FastAPI、LangGraph、FastMCP、高德 Web 服务和 DeepSeek 的结构化旅行规划工作台。产品把用户的出行条件转换为天气、跨城交通、目的地内交通、POI、酒店、预算、每日行程、地图和 Markdown 结果，并在页面中支持追问与行程编辑。

当前用户端主链路是结构化表单 + `/api/plan`；自然语言追问继续走 `/api/multi-agent-chat`。

当前阶段：Phase 0 和 Phase 1 已完成；Phase 2（事实 Contract、候选归一化与排序）进行中，2026-08-14 起新增 Phase 2.5（可选工具增强规划脑，agentic 补查）进入路线图。

## 2. 当前仓库状态

- 分支：`main`，相对 `origin/main` 领先 8 个本地提交
- HEAD：docs 同步提交；其前三个为 `05def10`（`feat: classify DeepSeek degradation and trace states`，2026-09-05 D11）、`029ef20`（`feat: wire candidate_contracts into plan response`，2026-09-05 D2）和 `dfb5a5b`（`feat: support structured MCP results with text fallback`，2026-09-05 D12）
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
| `tests/evals/` | 离线评测场景、fixture、指标和报告 | 效果护栏 |
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

主要响应字段：`plan_id`、`preferences`、`intercity_transport`、`local_transport`、`hotels`、`weather`、`weather_advice`、`pois`、`candidate_contracts`、`map`、`budget`、`itinerary_days`、`quality_review`、`markdown`、`trace`、`planning_mode`、`llm_status`。Phase 1 新增的可选结果包括 `preferences.freeText`、`preferences.hardConstraints`、`preferences.softPreferences`、`preferences.constraintSummary` 和 `quality_review.constraints`；Phase 2 新增可选 `candidate_contracts`（2026-09-05 已在 `run()` 接线，见工程债务 D2），旧 `pois`/`hotels` 字段继续保留。

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
- 导出支持 Markdown 下载和浏览器打印保存 PDF。
- 追问可继续修改偏好，但其响应仍来自旧的 `/api/multi-agent-chat` 文本链路。
- 760px 以下进入纵向布局；桌面结果生成后左侧输入区收缩为行程目录。

## 9. 已验证结果

最近复核：2026-09-05

```text
Python 全量 py_compile（sync/async/tests）：通过
node --check web/app.js：通过，Node v24.18.0
Phase 1 专项测试：5/5 通过
Phase 2 Contract/集成测试：7/7 通过
Phase E 约束链路测试：22/22 通过
D12 协议级测试（tests/test_mcp_protocol.py）：11/11 通过
D2/D11 规划器契约与 trace 测试（tests/test_phase2_contracts.py）：13/13 通过
D11 DeepSeek 契约测试（tests/test_deepseek_contracts.py）：16/16 通过
Phase 0 评测：4/4 通过；Phase 1/Phase 2 评测均为 10 个场景，Phase 2 硬约束满足率 0.7500
评测确定性断言：141 次调用/4 次 fixture 失败（已固化进 test_baseline_eval）
python -m unittest discover -s tests -q：124 个通过，62.956 秒（当前工作树）
合计测试：124/124 通过
pip check：通过
git diff --check：通过
```

本次探测到 8010 和 8098 均没有监听进程，未进行真实 MCP/高德/DeepSeek 请求或浏览器端到端截图验证。当前 `124/124` 证明离线受控路径与内存 FastMCP 协议级往返（含三入口兼容）稳定；真实 HTTP MCP、高德、DeepSeek 与浏览器端到端仍未验证。

## 10. 后续开发的优先关注点

1. [已完成 2026-09-05] 范围隔离与 D12 已按闸门提交（`dfb5a5b feat: support structured MCP results with text fallback`）；`.dsh/` 继续留在产品提交之外。
2. [已完成 2026-09-05] D12：稳定 MCP 结果封装、`call_text`/`call_structured` 双访问、Pydantic 坏元素过滤、内存协议级测试与三入口兼容。
3. [已完成 2026-09-05] D2：`/api/plan` 已输出可选、版本化 `candidate_contracts`（提交 `029ef20`），旧 `pois`/`hotels` 保留；D3 前端来源/落选展示在此之后进行。
4. [代码已完成 2026-09-05] D11 错误分类和降级观测已落地（提交 `05def10`）；剩余为高德成功、Key 缺失、fallback、混合来源测试和固定 DeepSeek 真实场景基线（随 Phase 2 真实验收步执行），离线与真实证据都通过后关闭 Phase 2。
5. 产品主线随后进入 Phase 3 的预算反馈与全局质量门；Phase 2.5 保持可选实验。长期维护项包括 Playwright 桌面/移动验收、前端请求超时、遗留端口示例清理和 `structured_planner.py` 兼容桥接收敛。

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
