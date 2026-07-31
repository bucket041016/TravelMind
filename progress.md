# 勘察进度

## 2026-07-31

- 已读取规划工作流要求。
- 已完成根目录和递归文件盘点。
- 已确认 Git 工作区干净，当前分支为 `main`。
- 已记录 `rg.exe` 启动失败及 PowerShell 替代方案。
- 已读取 `README.md`、`TRAVELMIND_README.md`、`HANDOFF.md`、`requirements.txt`、`.env.example`。
- 已确认文档定位、端口约定、外部服务、核心 API、关键业务不变量和历史验证结果。
- 已建立 Python 多智能体包、FastAPI、MCP 适配器和结构化规划器的符号索引。
- 已核对三条 API 路径、结构化规划器的职责范围、MCP 适配方式及 DeepSeek/高德降级定位。
- 已核对 MCP 工具清单、外部数据降级链、前端三栏布局、结果渲染、编辑/导出/追问和移动端规则。
- 已识别同步 MCP 默认端口 `8083` 与项目演示约定 `8098` 的配置差异，并区分了 `async/` 与当前主链路。
- 已完成全量 Python `py_compile`、`node --check web/app.js`、`unittest` 和 `git diff --check`。
- 回归结果：22/22 测试通过；Node `v24.18.0`；8010/8098 当前无监听进程。
- 已创建 `PROJECT_BASELINE.md`，汇总产品定位、架构、接口、目录、运行方式、前端行为、验证结果和后续关注点。
- 追加完成 GitHub 同类项目调研：检索并比较多 Agent、LangGraph 模板、CrewAI/RAG、Agno/MCP/Memory、高德 StateGraph、TripSage、PlanetPath 等项目。
- 已创建 `OPEN_SOURCE_COMPARISON.md`，包含项目矩阵、代码级问题诊断、目标架构、Phase 0-5 方案和首个 MVP 范围。
- 勘察阶段当时等待用户确认方案，未启动业务实现；后续续接工作已进入 Phase 0/1。

## Phase 0：离线评测基线（2026-07-31）

- 已按 `IMPLEMENTATION_PLAN.md` 盘点出 `StructuredTravelPlanner.toolbox` 和 `deepseek_brain` 两个可注入点，未修改 `sync/` 或 `web/`。
- 已新增 `tests/evals/__init__.py`、`fixtures.py`、`metrics.py`、`run_baseline.py` 和 `test_baseline_eval.py`。
- 已建立 10 个固定场景：标准周末、多人预算、雨天室内偏好、低预算、慢节奏、紧换乘容忍度、返程隔离、重复候选、依赖降级和自由文本硬约束。
- Fake MCP 覆盖天气、POI、酒店和路线；Fake DeepSeek 覆盖行程、酒店价格、路线评审和行程体检，并记录调用次数。
- 已实现 7 类基线指标：真实地点绑定率、重复地点率、硬约束满足率、路线超容忍率、预算偏差、返程住宿串台率、fallback 率。
- 已生成 `tests/evals/baseline_report.json` 和 `tests/evals/baseline_report.md`。
- 基线摘要：10 个场景、141 次调用、工具 fixture 故障 4 次；平均绑定率 `0.5940`、约束满足率 `0.6000`、路线超容忍率 `0.0750`、预算偏差 `0.6217`、串台率 `0.0000`、fallback 率 `0.0833`。
- 新增评测 `3/3` 通过；全量测试 `25/25` 通过；Python 全量编译、`node --check web/app.js`、`git diff --check` 均通过。
- 评测过程中曾修正一次指标误报：返程交通的安全说明包含“目的地住宿”否定语句，指标现已识别否定语义，不再误判为串台。
- Phase 0 已完成，按计划暂停，尚未开始 Phase 1 业务改造。

## Phase 1：约束完整进入 `/api/plan`（2026-07-31）

- 已读取 `CONTINUATION_SUMMARY.md`，确认必须保留的 API 兼容、真实地点来源、返程住宿隔离、离线 fixture 和技术栈规则。
- 已扩展 `PlanRequest`，增加可选 `freeText`、`hardConstraints`、`softPreferences`；旧请求默认值保持为空。
- 已在 `web/index.html` 增加“补充要求”输入，在 `web/app.js` 的 `buildPlanPayload`/`buildTripPrompt` 中传递约束内容。
- 已在 `structured_planner.py` 的偏好归一化阶段生成 `constraintSummary`，保留原始文本并区分硬约束、软偏好和未知项。
- 已将约束摘要接入 DeepSeek 规划 payload、规则规划路径和 `quality_review.constraints`；评审项包含状态和证据，前端和 Markdown 可显示。
- 已新增 `tests/test_phase1_constraints.py` 的 5 个专项测试，并扩展离线评测对自由文本约束的检查。
- 已生成 `tests/evals/phase1_report.json` 和 `tests/evals/phase1_report.md`；10 个场景平均硬约束满足率 `0.7500`，自由文本硬约束场景检查为 `1.0000`。
- 已完成验证：Phase 1 专项 `5/5`、Phase 0 评测 `3/3`、业务回归 `22/22`，合计 `30/30`；Python 编译、Node 检查和 `git diff --check` 通过。
- 该阶段结论：Phase 1 完成；当时候选 Contract/排序、预算反馈和结构化追问仍未实现，后续已进入 Phase 2。

## 文档同步与复核（2026-07-31）

- 已同步 `IMPLEMENTATION_PLAN.md`、`task_plan.md`、`PROJECT_BASELINE.md`、`findings.md` 和 `CONTINUATION_SUMMARY.md`，统一记录 Phase 1 完成和 Phase 2 前暂停状态。
- 已在交接摘要中列出必须保留的规则/文件/近期决定、单段历史摘要和建议排除材料；排除项仅减少日常上下文，不删除仓库文件。
- 复核命令结果：全量测试 `30/30` 通过；Python 全量编译通过；`node --check web/app.js` 通过；`git diff --check` 通过。
- 文档同步完成时工作区仍未进入 Phase 2；随后已按本摘要进入 Phase 2 Contract/排序基础，供应商协议尚未改动。

## Phase 2：事实 Contract 与候选排序基础（2026-07-31）

- 已盘点现有 MCP 返回：天气、POI、酒店和路线仍是文本；规划器通过正则提取名称、地址、坐标、评分和价格的部分字段。
- 已新增 `sync/multi_agent/contracts.py`，定义 `PlaceCandidate`、`HotelCandidate`、`RouteFact`、`WeatherFact`、位置/价格/来源元数据及运行时校验辅助函数。
- 已新增 `sync/multi_agent/fact_normalizer.py`，将旧文本解析结果归一化为 JSON-safe 候选、路线和天气事实；缺坐标/地址的 fallback 项标记为 partial/suggestion。
- 已新增 `sync/multi_agent/candidate_ranker.py`，提供真实地点、坐标、城市、重复、排除词和价格过滤，以及偏好、评分、距离、天气和来源完整度的可解释排序。
- 已在 `structured_planner.py` 接入兼容路径：旧 `pois`/`hotels` 列表保持不变，新增 `candidate_contracts`；DeepSeek payload 优先使用筛选后的候选。
- 新增 `tests/test_phase2_contracts.py`，专项/集成测试 `7/7` 通过；全量测试 `38/38` 通过，Python 编译、Node 语法和 `git diff --check` 通过。
- 已生成 `tests/evals/phase2_report.json` 和 `tests/evals/phase2_report.md`。当前指标为绑定率 `0.5940`、重复率 `0.0000`、硬约束满足率 `0.7500`、路线超容忍率 `0.0500`、预算偏差 `0.6191`、串台率 `0.0000`、fallback 率 `0.1000`。
- 当前结论：Contract/过滤/排序基础已接入，但 fallback 率略升；下一步先补混合来源和严格过滤降级场景，再决定是否改 MCP 返回协议。
