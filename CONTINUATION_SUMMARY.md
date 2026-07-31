# TravelMind 继续工作摘要

更新时间：2026-07-31  
当前阶段：Phase 2 进行中，先完成事实 Contract/归一化基础  
工作目录：`D:\Codexwork\my-langgraph-agent-main`  
分支：`main`

## 1. 当前必须保留的规则

### 执行规则

- 一次只推进一个 Phase；Phase 1 已验收，当前只推进 Phase 2 的 Contract/归一化基础，不把 Phase 3-5 混入本轮。
- 每个阶段先补离线 fixture/测试，再做最小实现；完成验收后同步 `task_plan.md`、`progress.md`、`findings.md` 和本摘要。
- 保持 Python、FastAPI、LangGraph/LangChain、FastMCP、高德和 DeepSeek 技术栈，不迁移到新框架。
- 手工编辑使用 `apply_patch`；保留用户已有改动和未跟踪文件，不使用破坏性 Git 回退。
- 不读取或输出 `.env` 内容；核心测试使用 Fake MCP/Fake DeepSeek，真实服务只作为后续手动验证路径。
- Windows + PowerShell 环境；Web 约定端口 `8010`，MCP 约定端口 `8098/my-custom-path`。

### 产品与数据规则

- `/api/plan` 是当前结构化规划主入口，旧 `/api/chat` 和 `/api/multi-agent-chat` 保持兼容。
- 新请求字段必须可选，旧请求、旧响应字段和旧前端行为不能因新增约束链路而失效。
- 用户要求分为原始自由文本、硬约束、软偏好和未知项；未知内容保留并标记待核实，不能当成确定事实。
- 真实地点必须有候选绑定、有效坐标和来源标记；泛化建议显式标记 `is_suggestion`，不进入地图。
- 高德参考消费、AI 常识区间和规则估算都保留来源与核实提示；铁路、航班、酒店库存仍是供应商占位能力。
- 返程交通 item 只表达目的地车站/机场到出发城市的移动，不把目的地住宿或酒店区域混入返程 item。
- 外部调用必须有降级、来源状态、调用边界和可观测 trace；测试不能依赖实时网络。

## 2. 当前必须保留的文件

### 认知、执行与交接文件

- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)：Phase 0-5 的执行合同、文件范围、验收、暂停条件和回滚点。
- [`task_plan.md`](task_plan.md)：当前看板；Phase 0、Phase 1 已完成，Phase 2 正在推进纯逻辑基础。
- [`PROJECT_BASELINE.md`](PROJECT_BASELINE.md)：架构、接口、运行方式和当前不变量。
- [`OPEN_SOURCE_COMPARISON.md`](OPEN_SOURCE_COMPARISON.md)：GitHub 同类项目比较和借鉴结论。
- [`findings.md`](findings.md)：事实发现、风险依据和阶段结果。
- [`progress.md`](progress.md)：命令、阶段动作和验证结果。
- [`CONTINUATION_SUMMARY.md`](CONTINUATION_SUMMARY.md)：本次继续工作的压缩上下文。

### 当前业务主链路

- `sync/travel_web_app.py`：FastAPI、`PlanRequest`、`/api/plan` 和旧追问入口；已接入 `freeText`、`hardConstraints`、`softPreferences`。
- `sync/multi_agent/structured_planner.py`：偏好归一化、事实编排、DeepSeek 规划、规则降级、质量体检、预算和输出；已接入 `constraintSummary` 与逐项约束评审。
- `sync/multi_agent/base_agent.py`：`MCPToolbox` 统一调用边界，后续离线替身继续从这里注入。
- `sync/fastmcp_server_streamhttp.py`：高德天气、路线、POI、酒店和 fallback 工具；本小步先不修改供应商返回协议。
- `sync/mcp_tools_adapter.py`：FastMCP 客户端适配；本小步通过兼容解析保留旧文本。
- `sync/multi_agent/contracts.py`、`fact_normalizer.py`、`candidate_ranker.py`：Phase 2 新增的 Contract、事实归一化和候选排序基础模块。
- `web/app.js`：`buildPlanPayload`、`buildTripPrompt`、约束检查显示、追问和结果渲染。
- `web/index.html`、`web/styles.css`：补充要求输入及其现有样式。
- `tests/test_travelmind_regression.py`：22 个业务回归测试。
- `tests/test_phase1_constraints.py`：5 个 Phase 1 请求、归一化、规划输入、评审和前端契约测试。
- `tests/evals/`：10 个离线场景、Fake MCP/Fake DeepSeek、7 类指标、Phase 0/Phase 1/Phase 2 报告和评测测试。
- 工作区已有未跟踪 `AGENTS.md`，保持原样，不纳入本轮优化。

## 3. 最近决定与当前状态

- 首轮优化顺序已经确定为：离线基线 -> 约束进入结构化规划 -> 候选 JSON Contract/排序 -> 预算反馈与全局质量门 -> 结构化追问版本 -> 持久化与真实任务事件。
- Phase 0 已建立 10 个固定场景、141 次 fixture 调用、4 次工具 fixture 故障和 7 类指标；基线平均真实地点绑定率 `0.5940`、重复地点率 `0.0000`、硬约束满足率 `0.6000`、路线超容忍率 `0.0750`、预算偏差 `0.6217`、返程住宿串台率 `0.0000`、fallback 率 `0.0833`。
- Phase 1 已完成：请求模型和前端 payload 传递自由文本/硬约束/软偏好；归一化生成 `constraintSummary`；规划脑、规则路径和质量评审共用摘要；`quality_review.constraints` 提供状态和证据；前端展示逐条约束检查。
- Phase 2 当前小步已完成 Contract/归一化/排序基础并接入 DeepSeek 候选输入；新增可选 `candidate_contracts`，旧 POI/酒店字段和文本 MCP 协议保持不变。
- 当前评测仍暴露未解决问题：平均硬约束满足率 `0.7500`，低预算/多人预算没有反馈重规划，紧换乘场景仍需要全局路线门槛；Phase 2 的候选排序已接入但 fallback 率略有上升。
- Phase 2 评测相对 Phase 1：路线超容忍率 `0.0750 -> 0.0500`，预算偏差 `0.6217 -> 0.6191`，fallback 率 `0.0833 -> 0.1000`；真实地点绑定率、重复率和返程住宿串台率保持不变。
- 已验证：Phase 1 专项测试 `5/5`、Phase 2 专项/集成测试 `7/7`、Phase 0 评测 `3/3`、报告渲染回归 `1/1`、业务回归 `22/22`，合计 `38/38`；Python 全量编译、`node --check web/app.js`、`git diff --check` 通过。
- 当前动作边界：继续停在 Phase 2；先补混合来源/严格过滤降级测试，确认 fallback 率后再评估 MCP 结构化返回，不进入预算反馈或 Phase 3。

## 4. 较早内容的压缩摘要

TravelMind 是一个以 `/api/plan` 为主入口的结构化旅行规划工作台，使用 FastAPI、LangGraph/LangChain、FastMCP、高德和 DeepSeek；事实工具通过 `MCPToolbox` 调用，规划器集中在 `sync/multi_agent/structured_planner.py`，前端请求和结果在 `web/app.js`。GitHub 调研确认继续保留现有技术栈，吸收 typed state、事实层与 AI 层分离、结构化输出、Review、预算反馈、Memory 和任务观测等机制。Phase 0 用离线替身建立了 10 个场景和 7 类指标，证明真实地点绑定率、约束满足率、预算反馈、紧换乘可行性和结构化事实是主要缺口，同时验证返程住宿隔离规则有效；Phase 1 已把自由文本和约束接入请求、偏好、规划和质量审计链路，旧接口保持兼容；当前 Phase 2 先将现有文本事实归一化为可校验 Contract，再用确定性过滤和排序改善候选输入。

## 5. 建议排除出日常上下文的材料

以下材料继续保留在仓库，定位问题时再读取，不作为每次决策的默认输入：

- GitHub 各仓库的逐目录原始调研细节；日常以 `OPEN_SOURCE_COMPARISON.md` 的结论矩阵和已确认机制为准。
- `findings.md`、`progress.md` 中 Phase 0 之前的逐条勘察命令；日常以本摘要和 `PROJECT_BASELINE.md` 的当前事实为准。
- `tests/evals/baseline_report.json`、`tests/evals/phase1_report.json`、`tests/evals/phase2_report.json` 的完整逐场景明细；日常使用对应 Markdown 聚合报告，出现指标回归时再读取 JSON。
- `async/`、早期单 Agent 示例、`web/index_v2.html`、`web/styles_v2.css`；它们是遗留或未接入当前入口的材料，除非当前 Phase 明确触及。
- `HANDOFF.md` 等较早设计叙述；如与源码、现有测试或本摘要冲突，以源码和最近验证结果为准。
- 早期“等待用户确认方案”的对话状态；当前以已完成的 Phase 1 和本文件记录的 Phase 2 当前小步状态为准。

## 6. 下一次继续入口

1. 先读取本文件、`IMPLEMENTATION_PLAN.md` 的 Phase 2、`PROJECT_BASELINE.md` 和 Phase 2 报告摘要。
2. 补充高德成功、Key 缺失、本地 fallback 和混合来源的 Contract/排序测试，特别记录严格坐标过滤导致的降级。
3. 根据指标决定保留严格过滤、增加可解释的 partial 候选层，或继续冻结 MCP 供应商协议；不凭感觉放宽真实地点护栏。
4. 重新运行 Phase 0/1/2 评测、业务回归、Python/Node/diff 检查，再决定是否完成 Phase 2。
