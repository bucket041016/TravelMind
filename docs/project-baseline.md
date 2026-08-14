# TravelMind 项目认知基线

> 整理自根目录 `PROJECT_BASELINE.md`，2026-08-04 合并；代码根目录为 `my-langgraph-agent-main/`。
> 原文件更新时间：2026-07-31。

## 1. 一句话定位

TravelMind 是一个基于 Python、FastAPI、LangGraph、FastMCP、高德 Web 服务和 DeepSeek 的结构化旅行规划工作台。产品把用户的出行条件转换为天气、跨城交通、目的地内交通、POI、酒店、预算、每日行程、地图和 Markdown 结果，并在页面中支持追问与行程编辑。

当前用户端主链路是结构化表单 + `/api/plan`；自然语言追问继续走 `/api/multi-agent-chat`。

当前阶段：Phase 0 和 Phase 1 已完成，Phase 2 正在推进事实 Contract、候选归一化与排序基础。

## 2. 当前仓库状态

- 分支：`main`
- HEAD：`2cf8ec8 Initial commit`（原勘察时记录；以实际 `git status` 为准）
- 认知与执行文档现位于 `docs/`（2026-08-04 整理后），根目录同名文件为历史留档。
- 工作区包含 Phase 1/Phase 2 业务改动、离线评测和执行文档。

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
6. 旧文本事实归一化、真实地点/坐标/重复/排除项过滤和可解释候选排序；结果以可选 `candidate_contracts` 输出。
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
| `sync/mcp_tools_adapter.py` | FastMCP Client 与 LangChain 工具包装 | 连接层 |
| `sync/multi_agent/structured_planner.py` | 结构化规划编排器（约 660 行），业务逻辑已拆分到同目录 20 个模块 | 当前核心业务模块 |
| `sync/multi_agent/contracts.py` | 地点、酒店、路线、天气和来源元数据 Contract | Phase 2 事实边界 |
| `sync/multi_agent/fact_normalizer.py` | 将旧文本解析结果归一化为 JSON-safe 事实 | Phase 2 兼容层 |
| `sync/multi_agent/candidate_ranker.py` | 候选硬过滤、评分、排序和入选/落选理由 | Phase 2 纯逻辑层 |
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

主要响应字段：`plan_id`、`preferences`、`intercity_transport`、`local_transport`、`hotels`、`weather`、`weather_advice`、`pois`、`map`、`budget`、`itinerary_days`、`quality_review`、`markdown`、`trace`、`planning_mode`、`llm_status`。Phase 1 新增的可选结果包括 `preferences.freeText`、`preferences.hardConstraints`、`preferences.softPreferences`、`preferences.constraintSummary` 和 `quality_review.constraints`；Phase 2 新增可选 `candidate_contracts`，旧 `pois`/`hotels` 字段继续保留。

`constraintSummary` 按 `hard`、`soft`、`unknown` 分组；每项保留 `id`、`kind`、`text`、`source`。质量评审逐项给出 `satisfied`、`violated` 或 `unknown`，并附 `evidence`。

`candidate_contracts` 当前版本为 `travelmind-candidate-v1`，来源模式为 `legacy_text_compatible`；包含 POI/酒店入选候选、评分理由、来源元数据和过滤落选原因。MCP Server 的供应商返回仍是旧文本。

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

配置注意：MCP Server 和 Web 代码的默认 MCP 地址仍含 `8083`，仓库演示约定使用 `8098`；运行 Web 时显式设置 `MCP_SERVER_URL` 是当前稳定启动条件。

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

执行日期：2026-07-31

```text
Python 全量 py_compile（sync/async/tests）：通过
node --check web/app.js：通过，Node v24.18.0
Phase 1 专项测试：5/5 通过
Phase 2 Contract/集成测试：7/7 通过
Phase E 约束链路测试：22/22 通过
Phase 0 评测：4/4 通过；Phase 1/Phase 2 评测均为 10 个场景，Phase 2 硬约束满足率 0.7500
python -m unittest discover -s tests -v：60 个通过（2026-08 复测）
合计测试：60/60 通过
git diff --check：通过
```

当时探测到 8010 和 8098 均没有监听进程，未进行真实 MCP/高德/DeepSeek 请求或浏览器端到端截图验证（验证结果以 `docs/implementation-plan.md` 的最新记录为准）。

## 10. 后续开发的优先关注点

1. Phase 2：补充高德成功、Key 缺失、fallback 和混合来源的 Contract/排序回归，并分析 fallback 率上升。
2. 保持返程交通与目的地住宿隔离、真实地点来源标记和旧 API 字段兼容。
3. 再评估是否让 MCP Server 返回结构化对象；在此之前继续使用兼容解析器。
4. 后续再处理预算反馈循环、全局质量门、结构化追问和真实任务事件；不要在 Phase 2 混入这些范围。
5. 长期维护项仍包括 MCP 端口统一、真实服务接口回归、Playwright 桌面/移动端检查，以及拆分 `structured_planner.py` 职责。

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
