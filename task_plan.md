# TravelMind 优化任务看板

详细执行合同见 [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)。本文件只记录当前阶段、边界、已完成动作和错误，避免执行过程中偏离计划。

## 当前目标

先建立离线智能度评测基线，再按 Phase 1-5 逐阶段优化。Phase 0 和 Phase 1 已完成，当前推进 Phase 2 的 Contract/归一化基础；先完成纯逻辑测试，再接入主规划链路。

## 阶段状态

- [completed] 基线勘察与 GitHub 同类项目对比
- [completed] Phase 0：离线评测基线和护栏
- [completed] Phase 1：约束完整进入 `/api/plan`
- [in_progress] Phase 2：事实 Contract、候选评分与选择
- [pending] Phase 3：预算反馈循环与全局质量门
- [pending] Phase 4：结构化追问、计划版本与 Diff
- [pending] Phase 5：持久化、真实进度与产品化质量门

## Phase 1 当前步骤

- [completed] 盘点 `PlanRequest`、`buildPlanPayload`、`buildTripPrompt` 和 `_normalize_preferences`
- [completed] 补请求兼容、自由文本传递和偏好归一化测试
- [completed] 扩展请求与偏好状态，保留旧字段和旧入口
- [completed] 将约束摘要接入规划输入、规则路径和质量审计
- [completed] 运行 Phase 0、业务回归、语法检查和 diff 检查
- [completed] 更新 `findings.md`、`progress.md`，完成 Phase 1 后暂停

## Phase 2 当前步骤

- [completed] 盘点现有 MCP 文本返回、规划器正则解析和离线 fixture 字段
- [completed] 定义 `PlaceCandidate`、`HotelCandidate`、`RouteFact`、`WeatherFact` 和来源元数据 Contract
- [completed] 为 Contract 增加事实归一化、硬过滤和可解释排序纯函数测试
- [completed] 接入规划器，同时保留旧文本字段和兼容解析器
- [in_progress] 覆盖高德成功、限流/Key 缺失、本地 fallback 和混合来源，并比较 Phase 2 指标
- [pending] 运行全量评测并判断是否进入 Phase 3

## Phase 2 当前结果

- 新增 `contracts.py`、`fact_normalizer.py`、`candidate_ranker.py` 和 `tests/test_phase2_contracts.py`。
- 旧文本字段仍由规划器消费；新增 `candidate_contracts` 可选结果，规划脑优先使用有效坐标、真实地点和去重后的排序候选。
- Contract 覆盖地点、酒店、路线、天气和来源元数据；本阶段当前只将地点/酒店候选接入主规划器，MCP 供应商结构化返回仍待后续小步。
- Phase 2 评测：真实地点绑定率 `0.5940`、重复率 `0.0000`、硬约束满足率 `0.7500`、路线超容忍率 `0.0500`、预算偏差 `0.6191`、返程住宿串台率 `0.0000`、fallback 率 `0.1000`。
- 与 Phase 1 对比：路线超容忍率和预算偏差略有改善；fallback 率上升 `0.0167`，需继续分析混合来源和严格候选过滤后的降级行为。

## Phase 1 结果

- `PlanRequest` 新增可选 `freeText`、`hardConstraints`、`softPreferences`。
- 规划器保留 `preferences.freeText`，并生成 `preferences.constraintSummary`，按 `hard`、`soft`、`unknown` 分类并附带来源和证据标识。
- 规划脑、规则规划器和 `quality_review.constraints` 共用约束摘要；评审逐项输出 `satisfied`、`violated`、`unknown`、`evidence`。
- 前端新增补充要求输入和约束检查渲染；`/api/multi-agent-chat` 及旧字段保持兼容。
- Phase 1 离线评测 10 个场景，硬约束满足率 `0.7500`，自由文本硬约束场景为 `1.0000`。
- 专项测试 5/5、Phase 0 评测 3/3、业务回归 22/22，共 30/30 通过。

## Phase 0 结果

- 10 个固定场景，Fake MCP/Fake DeepSeek 离线运行。
- 平均指标：真实地点绑定率 `0.5940`、重复地点率 `0.0000`、硬约束满足率 `0.6000`、路线超容忍率 `0.0750`、预算偏差 `0.6217`、返程住宿串台率 `0.0000`、fallback 率 `0.0833`。
- 141 次 fixture 调用，工具 fixture 故障 4 次；依赖降级场景可观测。
- 全量测试 `25/25` 通过，其中原有回归 `22/22`、新增评测 `3/3`。
- 报告文件：`tests/evals/baseline_report.json`、`tests/evals/baseline_report.md`。
- 当前状态：Phase 2 已启动，当前只实现 Contract/归一化基础；预算反馈和结构化追问仍不进入本阶段。

## 工作边界

- 当前阶段文件范围限定为 `sync/multi_agent/contracts.py`、`sync/multi_agent/fact_normalizer.py`、`sync/multi_agent/candidate_ranker.py`、必要的 `structured_planner.py` 和 `tests/`；供应商协议先不改。
- `async/`、旧单 Agent 示例、v2 静态资源和供应商接入保持排除。
- `.env` 内容保持私密；核心测试走离线 fixture，真实服务只作为手动验证路径。
- 维持现有响应契约；后续新增字段必须可选并保留旧入口。

## 验收命令

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests\evals -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check web\app.js
git diff --check
```

## 错误记录

| 错误 | 尝试 | 处理 |
|---|---:|---|
| `rg.exe` 启动时被 Windows 拒绝访问 | 1 | 改用 PowerShell 原生文件枚举，继续勘察 |
| 首次合并计划补丁时 `task_plan.md` 原文匹配失败 | 1 | 拆分为独立新增计划文件和独立重建看板，继续执行 |
| 第一次同步 `task_plan.md` 的补丁包含不存在的尾部上下文 | 1 | 缩小补丁匹配范围后成功更新，不影响文件内容 |
| 路线 Contract 测试未识别无“距离”前缀的 `3.2 km` | 1 | 对照现有 fixture 和旧解析器后，将距离前缀改为可选，并补回归测试 |
| Phase 2 场景诊断输出遇到 Windows GBK 无法编码 `¥` | 1 | 设置 `PYTHONIOENCODING=utf-8` 重复诊断，业务结果未受影响 |
| Phase 2 报告初版被渲染为 Phase 0 标题 | 1 | 扩展评测 renderer 的 suite 识别并重新生成独立 Phase 2 报告 |

## 已有交付物

- `PROJECT_BASELINE.md`：项目认知基线
- `OPEN_SOURCE_COMPARISON.md`：GitHub 同类项目对比与优化建议
- `findings.md`：勘察发现与证据
- `progress.md`：过程、命令和验证结果
- `IMPLEMENTATION_PLAN.md`：本轮详细执行计划
- `CONTINUATION_SUMMARY.md`：继续工作摘要、保留规则和排除材料
