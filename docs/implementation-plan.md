# TravelMind 智能规划优化执行计划

> 合并自根目录 `IMPLEMENTATION_PLAN.md`（执行合同）、`task_plan.md`（任务看板）和 `progress.md`（过程记录），2026-08-04 去重整理；代码根目录为 `my-langgraph-agent-main/`。
> 阶段结果只保留一份（以执行合同为准），任务看板与错误记录并入本文；后续每个 Phase/小步都更新本文。

## 1. 总目标

在保留现有 Python + FastAPI + LangGraph/LangChain + FastMCP + 高德 + DeepSeek 技术栈和既有响应字段兼容性的前提下，提升 TravelMind 的规划智能度、事实可靠性、约束满足率和可解释性。

目标架构与理想流程见 [docs/target-architecture.md](target-architecture.md)，白话讲解见 [docs/how-it-works.md](how-it-works.md)；本文只回答"分哪几个阶段、每阶段做什么、怎么验收"。

"智能"在本计划中不只指生成文案，更具体地定义为：

- 能理解并执行用户的硬约束、软偏好和自由文本要求。
- 优先使用真实、可定位、与目的地匹配的地点，而不是泛化或重复推荐。
- 将天气、营业时间、片区距离、交通方式、返程和旅行节奏联合考虑。
- 发现预算或可行性问题后能自动调整并再次评估。
- 追问可以直接修改当前结构化计划，并展示修改前后的差异。
- 每个关键选择都有事实来源、评分因素和降级原因。
- 质量可以通过固定场景和可重复指标持续比较，而不是只靠主观体验。

## 2. 非目标与边界

本轮不做以下工作：

- 不迁移到 CrewAI、Agno、Java、Next.js 或其他新主框架。
- 不一次性重写 `structured_planner.py`，不改变无关页面视觉和旧 API 行为。
- 不把实时车次、航班、酒店库存伪装成已经接入的事实；供应商接入另立任务。
- 不在没有评测基线的情况下调整提示词、评分权重或模型参数。
- 不在首轮引入分布式数据库、向量数据库、队列集群或复杂部署设施。
- 不依赖真实高德/DeepSeek 请求作为唯一测试手段；所有核心逻辑必须有离线 fixture。

## 3. 当前已知问题与对应策略

| 问题 | 直接表现 | 计划中的处理 |
|---|---|---|
| 自由文本未进入结构化规划 | 表单之外的要求丢失 | Phase 1 扩展请求模型、前端 payload 和偏好归一化 |
| 候选没有统一排序 | 地点选择像随机拼接 | Phase 2 建立候选 JSON Contract、过滤、评分和理由 |
| 工具主要返回文本 | 规划器依赖正则解析 | Phase 2 保留文本兼容层并增加结构化解析 |
| 预算只在末端提示 | 超支后仍输出原方案 | Phase 3 增加有限预算反馈循环和调整差异 |
| 路线评审局部化 | 单段合理但全天不可行 | Phase 3 增加时间、片区、天气、疲劳和返程硬门槛 |
| 追问走旧文本链路 | 对话不能稳定改当前计划 | Phase 4 增加结构化 refine、版本和 Diff |
| 只有浏览器轻量 hint | 偏好不能稳定复用 | Phase 5 再评估 SQLite Memory，不阻塞首轮 MVP |
| 前端进度是定时器 | 展示状态与后端脱节 | Phase 5 再接真实任务事件/SSE，先保持接口兼容 |
| 没有固定效果评测 | 优化结果无法客观比较 | Phase 0 建立离线场景、指标和质量门 |

## 4. 执行原则

1. 每次只推进一个 Phase，完成验收后再进入下一 Phase。
2. 每个 Phase 先读 `docs/project-baseline.md` 和本文，再编辑限定范围内的文件。
3. 先添加测试/fixture，再改业务逻辑；先保证可观察，再提高复杂度。
4. 维持现有响应字段；新增字段使用可选字段，不破坏旧前端。
5. 外部服务调用都必须有超时、降级和可记录的来源状态。
6. 每轮改动都运行最小相关测试，再运行全量回归。
7. 每个 Phase 结束时更新本文（看板/结果）和 `docs/findings.md`。
8. 发现与计划不符的架构事实时，先记录事实和影响，暂停当前 Phase 的扩散性改动。

## 5. 阶段总览

| 阶段 | 目标 | 主要产物 | 状态 |
|---|---|---|---|
| Phase 0 | 建立离线评测基线和护栏 | `tests/evals/`、场景 fixture、指标报告 | 已完成 |
| Phase 1 | 让用户约束完整进入规划链路 | 请求/状态/前端契约、约束解析测试 | 已完成 |
| Phase 2 | 事实结构化、候选评分和可解释选择 | 稳定 id 事实层、排序器、工具适配和测试 | 进行中 |
| Phase 2.5 | 可选工具增强规划脑（agentic 补查） | 只读白名单、id 回填、三步灰度、新增评测指标 | 待开始 |
| Phase 3 | 预算反馈和全局质量门 | 调整循环、全局评审、差异字段 | 待开始 |
| Phase 4 | 结构化追问与计划版本 | refine API、版本 Diff、前端交互 | 待开始 |
| Phase 5 | 持久化、真实进度和产品化质量门 | Memory、事件流、观测、E2E | 待开始 |

---

## Phase 0：离线评测基线和护栏

### 目标

在不修改规划业务行为的情况下，建立一套可重复运行的输入、工具结果、模型结果和评分指标，先准确回答"当前效果哪里不够智能"。

### 文件范围

- 新增：`tests/evals/`
- 允许新增：`tests/fixtures/`（若评测 fixture 需要与单元测试共享）
- 允许修改：`tests/test_travelmind_regression.py`（只补充稳定契约）
- 更新：`docs/implementation-plan.md`、`docs/findings.md`
- 不修改：`sync/`、`web/` 业务实现

### 具体步骤（已完成）

- [completed] 0.1 盘点现有规划器可注入点，确定 Fake MCP、Fake LLM 和调用计数器的最小接口。
- [completed] 0.2 建立 8-12 个固定场景，覆盖周末短途、多人预算、雨天、低预算、慢节奏、返程、自由文本硬约束和工具降级。
- [completed] 0.3 为场景准备稳定的 POI、酒店、路线、天气和模型输出 fixture，禁止测试依赖网络、Key 或当前日期。
- [completed] 0.4 实现评测 runner，记录场景输入、规划输出摘要、失败原因、调用次数和耗时。
- [completed] 0.5 实现第一版指标：真实地点绑定率、重复地点率、硬约束满足率、路线超容忍率、预算偏差、返程住宿串台率、fallback 率。
- [completed] 0.6 为指标设置"当前基线记录"，不把未经业务讨论的阈值当作最终质量门。
- [completed] 0.7 运行评测和现有全量回归，确认新增工具不会改变现有业务结果。

### 验收标准

- 所有场景可离线重复运行，运行结果不依赖 `.env` 或外部服务。
- 每个场景有明确的输入、预期硬约束和可定位失败信息。
- runner 能输出机器可读 JSON 或 CSV，以及人可读 Markdown 摘要。
- 至少记录上述 7 类指标，并能按场景查看。
- 原有 22 个回归测试继续通过，Python 编译和前端语法检查继续通过。

### 暂停条件

- 无法在不改业务代码的前提下替换外部 MCP/LLM：先只建立纯函数指标和静态响应 fixture，暂停真实 runner 接入。
- 现有测试依赖隐式全局状态且新增 fixture 会污染它：先隔离 fixture 生命周期，不扩展业务改造。
- 指标定义与响应字段不一致：记录缺口，暂停阈值设计，先完成字段映射。

### 回滚点

删除或回滚 `tests/evals/` 和本阶段新增的测试辅助文件即可；不应需要回滚 `sync/` 或 `web/`。

### 实际结果

- 场景：10 个固定离线场景；Fake MCP/Fake DeepSeek 总调用 141 次，工具 fixture 故障场景记录 4 次失败。
- 平均真实地点绑定率：0.5940。
- 平均重复地点率：0.0000。
- 平均硬约束满足率：0.6000。
- 平均路线超容忍率：0.0750。
- 平均预算偏差：0.6217。
- 平均返程住宿串台率：0.0000。
- 平均 fallback 率：0.0833。
- 关键缺口已复现：自由文本没有进入 `preferences`，低预算/多人预算没有反馈调整，紧换乘容忍度仍会产生超时路线。
- 验证：新增评测 3/3 通过；全量测试 25/25 通过；Python 编译、Node 语法和 `git diff --check` 通过。
- 报告：`tests/evals/baseline_report.json`、`tests/evals/baseline_report.md`。

---

## Phase 1：约束完整进入 `/api/plan`

### 目标

让自然语言补充、不可妥协条件、软偏好、节奏、换乘容忍度和返程要求进入同一份结构化偏好状态，并在规划、评审和输出中可追踪。

### 文件范围

- `sync/travel_web_app.py`
- `sync/multi_agent/structured_planner.py`
- `sync/multi_agent/state.py` 或实际状态模型文件
- `web/app.js`
- `web/index.html`（只在需要补充输入控件时修改）
- `web/styles.css`（只补充新增输入控件的现有样式）
- `tests/` 中请求契约、归一化和前端静态契约测试

### 具体步骤（已完成）

- [x] 1.1 扩展 `PlanRequest`，增加 `freeText`、`hardConstraints`、`softPreferences` 或等价字段，并保留旧字段默认值。
- [x] 1.2 在 `buildPlanPayload` 和 `buildTripPrompt` 中传递自由文本与硬约束，避免只存在于浏览器状态。
- [x] 1.3 在偏好归一化阶段拆分硬约束、软偏好、推断偏好和未知信息，保留原始文本用于审计。
- [x] 1.4 给规划 prompt 和规则规划器提供同一份约束摘要，禁止模型只读取自然语言而规则层遗漏。
- [x] 1.5 在 `quality_review` 增加约束逐项结果：`satisfied`、`violated`、`unknown`、`evidence`。
- [x] 1.6 增加请求兼容、自由文本传递、空值和异常输入测试。

### 验收标准

- 用户输入的硬约束能在响应中找到对应的解析结果和证据。
- 硬约束失败会进入质量评审并明确标记，不被普通推荐理由掩盖。
- 旧版请求不带新增字段时行为和响应字段保持兼容。
- Phase 0 中"自由文本硬约束"场景的传递率达到 100%。

### 暂停条件

- 请求字段语义与前端现有输入无法兼容：先保留兼容字段并补充迁移说明。
- 解析结果存在高比例歧义：输出澄清项，不把猜测当硬约束。

### 回滚点

按字段粒度回退请求扩展和前端传参；保留 Phase 0 评测代码。

### 实际结果

- `PlanRequest`、前端 `buildPlanPayload` 和 `buildTripPrompt` 已支持 `freeText`、`hardConstraints`、`softPreferences`，旧字段仍使用默认值。
- `_normalize_preferences` 保留原始文本，并生成带 `id`、`kind`、`source`、`text` 的 `constraintSummary`，区分 `hard`、`soft` 和 `unknown`。
- 规划脑 payload、规则规划路径和 `quality_review` 共用同一份约束摘要；逐项评审输出 `satisfied`、`violated`、`unknown` 与 `evidence`。
- 前端新增"补充要求"输入和约束检查展示；旧 `/api/multi-agent-chat` 入口未改动。
- 新增 `tests/test_phase1_constraints.py`，覆盖请求兼容、归一化、规划输入、规则评审和前端静态契约。
- Phase 1 离线评测：10 个场景；硬约束满足率 `0.7500`；自由文本硬约束场景传递和行为检查均为 `1.0000`。
- Phase 1 仍未解决候选统一排序、预算超支反馈和全局路线门槛，这些保持在 Phase 2-3。
- 验证结果：Phase 1 专项 5/5、Phase 0 评测 3/3、业务回归 22/22；合计 30/30；Python 编译、Node 语法和 `git diff --check` 通过。

### 暂停说明

Phase 1 已完成验收，进入 Phase 2 前先确认候选 Contract 的字段边界和兼容策略；不提前新增排序器或改动 MCP 返回协议。

---

## Phase 2：事实 Contract、候选评分与选择

### 目标

把 POI、酒店、天气和路线的关键结果统一成可校验 JSON，使用确定性过滤和可解释评分产生候选，再让模型负责组合和表达。

### 文件范围

- `sync/fastmcp_server_streamhttp.py`
- `sync/mcp_tools_adapter.py`
- `sync/multi_agent/structured_planner.py`
- 允许新增：`sync/multi_agent/contracts.py`、`candidate_ranker.py`、`fact_normalizer.py`
- `tests/` 中 Contract、降级、排序和来源测试

### 具体步骤

- [in_progress] 2.1 定义 `PlaceCandidate`、`HotelCandidate`、`RouteFact`、`WeatherFact` 和来源元数据。
- [ ] 2.2 建立稳定 id 事实层：让 MCP 工具返回结构化对象（含稳定 `candidate_id`），或由后端归一化从名字/坐标回溯生成 id；同时保留旧文本字段或兼容解析器。**铁律：模型永不生成 id，只能引用后端给出的 id。**
- [ ] 2.3 统一真实地点判定、城市匹配、坐标有效性、类别、价格区间和来源置信度。
- [ ] 2.4 实现候选硬过滤：目的地、重复、坐标、营业/时间窗、预算上限、用户排除项。
- [ ] 2.5 实现可解释排序：偏好匹配、距离、评分、价格、事实完整度、天气适配、重复惩罚。
- [ ] 2.6 将排序分数、入选理由、落选原因写入可选响应字段，不破坏原字段。
- [ ] 2.7 增加高德成功、限流、Key 缺失、本地 fallback 和混合来源测试。
- [ ] 2.8 低成本增强（由 2026-08-14 验证实证）：精修 `search_poi` 等工具 description（写明一次返回全部类别，避免重复调用与重复 token）；DeepSeek 输出加 `response_format={"type":"json_object"}` 约束，复用现有 `_parse_json_object` 兜底。

### 验收标准

- 规划器不再依赖单一自由文本正则才能获得核心地点字段。
- 每个入选 POI/酒店都可定位到来源、坐标、评分理由和**稳定 id**；缺失信息明确标记。
- 重复地点和目的地串台在进入模型前被过滤或显式警告。
- 任何 LLM 路径产出的真实地点都能回溯到后端生成的 id；模型生成的 id 一律视为非法。
- Phase 0 的真实地点绑定率、重复地点率和 fallback 指标可量化比较。

### 暂停条件

- 高德字段在不同接口中不稳定：先在适配器层归一化，不把供应商字段直接泄漏到规划器。
- 结构化和文本返回同时维护导致契约不明确：冻结新字段命名，先补测试再继续。

### 回滚点

保留旧工具返回路径，通过 feature flag 或兼容解析器切回；候选排序可单独关闭，回到原候选顺序。

### 当前小步结果

- 已新增 `sync/multi_agent/contracts.py`、`fact_normalizer.py`、`candidate_ranker.py`，并以 `tests/test_phase2_contracts.py` 覆盖地点、酒店、路线、天气、来源、过滤和排序。
- 规划器保留旧 `pois`/`hotels` 字段，DeepSeek 候选输入优先使用有效坐标、真实地点、去重和排序结果；`candidate_contracts` 的构建与消费代码已就绪，但 `run()` 尚未接线产出（见工程债务 D2）。
- MCP Server 仍返回旧文本，当前通过兼容归一化层接入，没有修改供应商协议或 `MCPToolbox` 字符串边界。
- Phase 2 专项/集成测试 `7/7`，全量回归 `38/38`，Python 编译、Node 检查和 `git diff --check` 通过。
- 独立报告：`tests/evals/phase2_report.json`、`tests/evals/phase2_report.md`。与 Phase 1 相比，路线超容忍率由 `0.0750` 降至 `0.0500`，预算偏差由 `0.6217` 降至 `0.6191`，fallback 率由 `0.0833` 升至 `0.1000`。
- 当前未宣告 Phase 2 完成；下一小步是补充混合来源/降级测试，评估是否需要降低严格过滤造成的 fallback，再考虑 MCP 结构化返回。

### 2026-08-14 agentic 预验证证据（决定 Phase 2.5 形态）

两轮受控实验（脚本 `output/verify_agentic_plan.py` 本地假工具版、`output/verify_agentic_plan_mcp.py` 真实 MCP 版，均未改动业务代码）：

- 第一轮（假工具 + 真实 DeepSeek）：2 次 LLM 调用完成并行查 3 工具 + 输出 JSON，零编造；但 prompt 只列 3 个字段时模型只输出 3 个字段——**字段漂移实证**。
- 第二轮（真实 MCP + 真实高德 + 真实 DeepSeek）：6 次调用/27.6s，出现自主补查 `search_hotels(near=福田)` 的**真实 agentic 行为**，12 个 item 地点零编造；但 MCP 文本没有稳定 id，模型**自行编造 candidate_id**（如 `poi_shenzhen_museum`、`el_yunzhongtian`）。
- 附带发现：`search_poi` 因 description 未写明"一次返回全部类别"被重复调用两次（约 9KB 重复内容进上下文）；模型输出带英文前言和 ```json fence（`_parse_json_object` 可兜底）。

结论：agentic 补查可行且有真实价值，但必须以"后端回填 id + 强 schema 校验 + 只读白名单"为前提；该前提正是 Phase 2.2 的稳定 id 事实层。两个验证脚本目前在 `output/`（未跟踪），Phase 2.5 第一步先迁移到仓库内可复现位置。

---

## Phase 2.5：工具增强规划脑（可选 agentic 补查）

### 目标

在保持确定性事实层与规则降级骨架不变的前提下，把 DeepSeek 从"纯决策者"升级为"可自主补查的决策者"：当模型判断候选不足时，允许它通过**只读白名单工具**补查事实，用数据验证该增强是否提升规划质量。

### 背景与验证证据

见 Phase 2 的"2026-08-14 agentic 预验证证据"。核心结论：简单场景下 2 次 LLM 调用即可完成补查+输出、零地点编造；真实 MCP 下出现自主补查行为（价值成立）；但模型会**编造 candidate_id**，字段会**漂移**，工具 description 不当会造成重复调用。

### 铁律（由验证得出，违反即回退）

1. `candidate_id` 绝不允许模型生成：模型输出只填 `title`（或引用工具返回的编号），后端用名字/坐标回溯匹配 `normalize_place_candidates` 生成的候选并回填真 id；匹配不上的降级 `is_suggestion=true` 或丢弃。
2. 输出 schema 显式列出前端全部字段；`response_format={"type":"json_object"}` + 现有 `_parse_json_object` 兜底；失败重试一次，再失败走 `rule_fallback`。
3. 补查返回的新候选必须回传后端重新 normalize 生成 id，再并入候选池，绝不直接采信模型转述。
4. 工具只读白名单：`get_weather`、`search_poi`、`search_hotels`、`amap_plan_routes`、`amap_geocode`；排除 `write_itinerary_file` 等副作用工具。

### 文件范围

- 允许新增：`sync/multi_agent/tool_augmented_brain.py`（或并入 `deepseek_brain.py`）
- `sync/multi_agent/deepseek_brain.py`、`sync/multi_agent/structured_planner.py`（可选路径接入，不替换 `plan()`）
- `sync/fastmcp_server_streamhttp.py`（仅工具 description 精修）
- `tests/` 中 `plan_with_tools` 离线 fixture、id 回填与回溯校验测试
- 迁移验证脚本：`output/verify_agentic_plan*.py` → `tools/verify/` 或 `tests/evals/`（当前未跟踪，不迁移会随清理丢失）

### 具体步骤

- [ ] 2.5.1 迁移并整理两个验证脚本为可重复运行的对照实验，真实 MCP 版本通过环境变量开关控制。
- [ ] 2.5.2 先完成 MCPToolAdapter 连接复用（性能前提，否则 agentic 循环放大每次新建 Client 的开销）。
- [ ] 2.5.3 新增 `plan_with_tools`，第一步只挂 `get_weather`，验证"补查→闭环"链路；feature flag `ENABLE_TOOL_AGENTIC_PLAN=false` 默认关闭，`planning_mode` 新增 `deepseek_agentic`。
- [ ] 2.5.4 加 `search_poi`/`search_hotels`，验证补查候选回传 normalize、id 回填与回溯校验。
- [ ] 2.5.5 加 `amap_plan_routes`，验证交通补查；补查轮次设硬上限（如最多 2 轮）。
- [ ] 2.5.6 离线评测适配：`FixtureDeepSeekBrain` 增加确定性的 `plan_with_tools`；新增指标：工具调用次数/成功率、输出字段完整率、`candidate_id` 回溯命中率。
- [ ] 2.5.7 压力场景对照：预算超支、天气突变、返程住宿串台（与 Phase 3 场景共用 fixture，实验缺口由此补齐）。

### 验收标准

- 每步在离线评测与真实场景各跑一遍，对比 `rule_fallback` 率、字段完整率、幻觉率、端到端延迟。
- `candidate_id` 回溯命中率 100%，或未命中项全部降级为 `suggestion`；响应中不得出现模型生成的 id。
- 默认关闭不影响现有路径；开启后旧字段与降级路径不变。
- 离线评测的 141 次调用断言继续成立（fixture 确定性）。

### 暂停条件

- 补查候选回溯失败率高：先完成 Phase 2.2 的稳定 id 事实层再继续。
- 端到端延迟或 token 成本超出预算：收紧白名单、减少补查轮次，或降级为"仅首轮补查"。

### 回滚点

关闭 `ENABLE_TOOL_AGENTIC_PLAN` 即回到现状；新增文件与迁移脚本可独立删除，不影响主链路。

---

## Phase 3：预算反馈循环与全局质量门

### 目标

把预算、路线、时间、天气、片区和疲劳约束放进有限反馈循环；超预算或不可行时自动调整有限范围，并输出调整前后差异。

**与 Phase 2.5 的关系**：本轮以确定性规则调整为主（保证可测性与硬约束安全）；Phase 2.5 的工具增强脑（若已启用）只能作为"替换候选的提议者"，所有提议必须经过确定性质量门。Phase 2.5 的预验证实验没有覆盖预算/天气/返程压力场景，该缺口由本阶段评测场景补齐。

### 文件范围

- `sync/multi_agent/structured_planner.py`
- 允许新增：`sync/multi_agent/quality_gate.py`、`budget_optimizer.py`、`itinerary_validator.py`
- `sync/travel_web_app.py`（仅补充响应字段）
- `web/app.js`（展示调整记录）
- `tests/` 中循环、上限、回滚和全局质量测试

### 具体步骤

- [ ] 3.1 将质量检查拆为硬门槛和软评分，先验证硬门槛。
- [ ] 3.2 计算全天时间线、移动耗时、开放时间、用餐间隔、休息间隔、天气适配和返程安全余量。
- [ ] 3.3 定义预算调整优先级：先替换同片区高价活动，再调整酒店档位/住宿策略，最后调整交通或非硬性活动。
- [ ] 3.4 增加最多 2-3 轮的预算/可行性反馈，保留每轮输入摘要、调整动作和结果。
- [ ] 3.5 超出循环上限仍不满足时，输出最接近方案和明确缺口，不无限重试。
- [ ] 3.6 增加返回目的地、跨城日期和最后一晚住宿一致性检查。
- [ ] 3.7 增加预算偏差、路线超容忍率和不可行行程测试。

### 验收标准

- 预算超支场景能产生真实替换或降级，而不是只给文字建议。
- 反馈轮次有硬上限，调用次数可测，失败时保留最佳已知方案。
- 任何硬约束违规都能阻止方案直接通过质量门。
- 调整记录能解释"改了什么、为什么改、代价是什么"。

### 暂停条件

- 调整会破坏用户硬约束：停止该动作并选择下一个可行策略。
- 模型输出在循环中不稳定：先采用确定性规则调整，减少模型自由度。

### 回滚点

通过配置关闭预算循环和新质量门，保留原一次性规划路径；不删除评测场景。

---

## Phase 4：结构化追问、计划版本与 Diff

### 目标

让右侧追问基于当前结构化计划进行增量修改，而不是返回一份与当前计划脱节的 Markdown 文本。

### 文件范围

- `sync/travel_web_app.py`
- `sync/multi_agent/structured_planner.py`
- 允许新增：`sync/multi_agent/plan_version.py`、`refine_parser.py`
- `web/app.js`、`web/index.html`、`web/styles.css`
- `tests/` 中 refine API、版本和前端交互测试

### 具体步骤

- [ ] 4.1 定义 `plan_id`、`version`、`parent_version` 和输入约束快照。
- [ ] 4.2 增加结构化 refine 请求，包含当前计划、用户追问和可选修改范围。
- [ ] 4.3 将追问解析为增量操作：替换地点、调整预算、改变节奏、增加/删除活动、修改住宿策略。
- [ ] 4.4 对增量操作重新执行受影响的候选、路线、预算和质量检查。若 Phase 2.5 已启用，受影响部分的候选补查可复用工具增强脑；本轮不依赖它。
- [ ] 4.5 返回结构化 Diff、解释和最新 Markdown；失败时保留旧版本。
- [ ] 4.6 前端追问改为调用 refine 接口，展示版本和修改摘要。

### 验收标准

- "把第二天改成室内、预算不变"能只影响相关日期和预算，不丢失其他天。
- 失败的追问不会覆盖当前可用计划。
- Diff 可定位到日期、活动、预算和约束变化。
- 旧 `/api/multi-agent-chat` 仍可作为兼容入口。

### 暂停条件

- 增量语义无法确定：返回需要确认的结构化操作，不直接改计划。
- 当前计划缺少必要事实：回到 Phase 2 补齐事实，不在前端猜测。

### 回滚点

前端保留旧追问入口开关；服务端保留旧文本响应，不删除既有接口。

---

## Phase 5：持久化、真实进度与产品化质量门

### 目标

在 MVP 稳定后增加可恢复的用户偏好、计划历史、真实任务事件、观测和端到端检查。

### 文件范围

- `sync/` 新增轻量持久化和任务状态模块
- `sync/travel_web_app.py`
- `web/app.js`、`web/index.html`
- `tests/evals/`、`tests/e2e/` 或 Playwright 配置
- 部署和运行文档

### 具体步骤

- [ ] 5.1 用 SQLite 保存明确偏好、计划版本、评测摘要和任务状态。
- [ ] 5.2 增加缓存、幂等键、超时、重试预算和敏感信息脱敏日志。
- [ ] 5.3 产生真实阶段事件，前端用 SSE 或 WebSocket 消费；断线可查询当前状态。
- [ ] 5.4 接入结构化 trace 和可选 Langfuse/OpenTelemetry，不让观测依赖主流程成功。
- [ ] 5.5 使用 Playwright 覆盖桌面、移动端、规划、追问、编辑、导出和错误状态。
- [ ] 5.6 建立质量阈值、回归报告和发布前检查清单。

### 验收标准

- 页面进度来自真实任务状态，刷新或重连后能恢复。
- 同一幂等请求不会重复产生不可控的外部调用。
- 评测报告能比较版本，并在关键指标回退时阻止发布。
- 核心用户流程有至少一条桌面和移动端 E2E 路径。

### 暂停条件

- 单机 SQLite 无法满足并发要求：先保持接口抽象，不提前引入外部基础设施。
- 实时通道增加复杂度却没有用户价值：先保留轮询状态接口。

### 回滚点

关闭持久化/事件流 feature flag，回到同步请求和浏览器本地快照；保留数据迁移脚本。

---

## 工程债务台账（与 Phase 并行，不占阶段名额）

> 债务不阻塞主线 Phase，但部分债务是后续 Phase 的前置条件（已标注）。每项用 `D` 编号跟踪，状态同步在"当前任务看板"。

| 编号 | 债务 | 问题与证据 | 处理方案 | 优先级 | 关联 | 状态 |
|---|---|---|---|---|---|---|
| D1 | MCPToolAdapter 每次调用新建连接 | `call_mcp_tool` 每次 `asyncio.run` + 新建 `Client`（2 次 HTTP 握手）；单次规划数十次调用；agentic 实验 6 调用 27.6s | 复用 Client 连接，或把 `/api/plan` 改异步端点统一事件循环 | 高 | Phase 2.5 前序条件 | 未开始（调试 print、空 content 防护已清理） |
| D2 | `candidate_contracts` 生产未接线 | `_build_candidate_contracts` 已定义但 `run()` 未调用；消费端 `itinerary_builder` 已就绪；文档声称"新增可选字段"与实际不符（2026-08-14 核对） | 在 `run()` 接入输出可选字段并补断言测试，或修正文档声明 | 高 | Phase 2 收尾；D3 前提 | 未开始 |
| D3 | 前端不展示来源/排序理由 | `source_meta`/`validation`/`selection` 后端已生成（D2 接线后才有产出），页面未展示 | 结果页展示来源置信度、入选/落选理由 | 中 | 依赖 D2 | 未开始 |
| D4 | 死代码退役 | `async/` 4 文件、`sync/agent_chatbot_*.py`、`sync/user_api.py`、legacy `*_agent.py`+`orchestrator.py`（仅 `/api/multi-agent-chat` 可达、零测试） | 先给旧入口补冒烟测试再决定退役；保留 API 兼容或明确下线 | 中 | — | 未开始 |
| D5 | 重复函数收敛 | haversine ×4（1 份无 clamp）、`_poi_key`×2、`_parse_price_range`×2（全角～处理不一致）、`_default_hotel_area`×3 | 收敛到 `contracts.py`/`text_parser.py` 单一实现 | 中 | — | 未开始 |
| D6 | app.js 单文件约 2300 行 | 双页面历史遗留，维护困难 | 按渲染/请求/编辑/导出拆 ES modules | 中 | 建议 Phase 4 动前端前完成 | 未开始 |
| D7 | 前端 fetch 无超时、错误透传 | 请求可能永久挂起；错误直接显示后端 detail | AbortController 超时 + 结构化错误提示 | 中 | — | 未开始 |
| D8 | staticmethod 兼容层 | `structured_planner.py` 约 150 行桥接（Phase E 遗留） | 测试全部改纯函数调用后移除桥接 | 低 | — | 未开始 |
| D9 | 仅测试使用的函数 | `normalize_route_fact`、`validate_place_candidate` 生产链路未使用 | 明确接入或移除，避免误导读者 | 低 | — | 未开始 |
| D10 | 小项合集 | CORS `allow_origins=*`+`allow_credentials=True` 无效组合；`max_tokens=3500` 多日行程截断风险；`write_itinerary_file` 文件名边界；Windows 日志 GBK 编码 | 逐项顺手修 | 低 | — | 未开始 |

建议穿插顺序：D1 → D2 → D3 与 Phase 2 收尾并行；D4/D5 作为低风险清理穿插；D6 在 Phase 4 之前完成；D7/D8/D9/D10 随时顺手。

---

## 当前任务看板

### 阶段状态

- [completed] 基线勘察与 GitHub 同类项目对比
- [completed] Phase 0：离线评测基线和护栏
- [completed] Phase 1：约束完整进入 `/api/plan`
- [in_progress] Phase 2：事实 Contract、候选评分与选择
- [pending] Phase 2.5：可选工具增强规划脑（agentic 补查）
- [pending] Phase 3：预算反馈循环与全局质量门
- [pending] Phase 4：结构化追问、计划版本与 Diff
- [pending] Phase 5：持久化、真实进度与产品化质量门
- [pending] 工程债务 D1-D10（见"工程债务台账"；D1/D2 为高优先级前置）

### Phase 2 当前步骤

- [completed] 盘点现有 MCP 文本返回、规划器正则解析和离线 fixture 字段
- [completed] 定义 `PlaceCandidate`、`HotelCandidate`、`RouteFact`、`WeatherFact` 和来源元数据 Contract
- [completed] 为 Contract 增加事实归一化、硬过滤和可解释排序纯函数测试
- [completed] 接入规划器，同时保留旧文本字段和兼容解析器
- [completed] 定位 fallback 率上升来源：`tight_transfer_tolerance` 场景本地路线段在候选排序接入后转为非 amap 来源（+1/6 组件），与酒店过滤无关
- [completed] 修复酒店候选全部超预算时被静默清空的问题：回退"仅因价格超限"被拒候选并标记 `selection.status="over_budget"`，避免酒店组件整体降级
- [completed] 修复 `fact_normalizer._status` 把 `rule_fallback` 误标为 `amap_fallback`，并统一 MCP 默认端口与文档约定
- [completed] 两轮 agentic 预验证实验（2026-08-14，脚本在 `output/` 待迁移）：证明补查可行、零地点编造；实证模型编造 candidate_id 与字段漂移
- [in_progress] 覆盖高德成功、限流/Key 缺失、本地 fallback 和混合来源，并比较 Phase 2 指标
- [pending] 2.8 工具 description 精修与 `response_format=json_object`（低成本增强）
- [pending] 运行全量评测并判断是否进入 Phase 3

### Phase 2 当前指标对比

| 指标 | Phase 0 | Phase 1 | Phase 2 | 变化 |
|---|---:|---:|---:|---|
| 真实地点绑定率 | 0.5940 | 0.5940 | 0.5940 | 不变 |
| 重复地点率 | 0.0000 | 0.0000 | 0.0000 | 不变 |
| 硬约束满足率 | 0.6000 | 0.7500 | 0.7500 | Phase 1 提升 |
| 路线超容忍率 | 0.0750 | 0.0750 | 0.0500 | Phase 2 下降 |
| 预算偏差 | 0.6217 | 0.6217 | 0.6230 | 略升：超预算酒店现在被如实保留而非静默删除，超支被显式呈现 |
| 返程住宿串台率 | 0.0000 | 0.0000 | 0.0000 | 不变 |
| fallback 率 | 0.0833 | 0.0833 | 0.1000 | 上升来源已定位为紧换乘场景路线段转非 amap 来源，非酒店过滤 |

紧换乘场景候选排序会把可用真实地点送入规划脑，但远距离 fixture 仍触发规则路线切换；这验证了候选排序不能替代 Phase 3 的全局路线质量门。酒店超预算候选现在保留并带 `over_budget` 标记，预算偏差的小幅上升是如实呈现超支的结果，后续由 Phase 3 的预算反馈循环负责替换或降级。当前需继续验证混合来源和严格坐标过滤的 fallback 行为；在此证据完成前，不切换 MCP 供应商返回协议，也不放宽真实地点/坐标护栏。

### Phase 2.5 当前步骤

- [pending] 前序条件 1：Phase 2.2 稳定 id 事实层（2.5 的所有铁律都依赖它）
- [pending] 前序条件 2：MCPToolAdapter 连接复用（agentic 循环会放大每次新建 Client 的开销）
- [pending] 2.5.1 迁移 `output/verify_agentic_plan*.py` 到 `tools/verify/` 或 `tests/evals/`
- [pending] 2.5.3-2.5.5 三步灰度：挂 `get_weather` → 加 POI/酒店 → 加路线，每步离线评测 + 真实对照
- [pending] 2.5.6-2.5.7 评测适配与压力场景（预算/天气/返程，与 Phase 3 共用 fixture）

### 工作边界

- 当前阶段文件范围限定为 `sync/multi_agent/contracts.py`、`sync/multi_agent/fact_normalizer.py`、`sync/multi_agent/candidate_ranker.py`、必要的 `structured_planner.py` 和 `tests/`；供应商协议先不改。
- `async/`、旧单 Agent 示例、v2 静态资源和供应商接入保持排除。
- `.env` 内容保持私密；核心测试走离线 fixture，真实服务只作为手动验证路径。
- 维持现有响应契约；后续新增字段必须可选并保留旧入口。

## 统一验证命令

在项目根目录（`my-langgraph-agent-main/`）执行：

```powershell
# Python 语法
Get-ChildItem sync,async,tests -Recurse -Filter *.py | ForEach-Object {
    .\.venv\Scripts\python.exe -m py_compile $_.FullName
}

# 前端语法
node --check web\app.js

# 全量回归
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 离线评测
.\.venv\Scripts\python.exe -m unittest discover -s tests\evals -v

# 补丁空白检查
git diff --check
```

若后续引入 Playwright，再增加项目已有的浏览器检查命令，并记录桌面/移动端截图和控制台错误。

## 错误记录

| 错误 | 尝试 | 处理 |
|---|---:|---|
| `rg.exe` 启动时被 Windows 拒绝访问 | 1 | 改用 PowerShell 原生文件枚举，继续勘察 |
| 首次合并计划补丁时 `task_plan.md` 原文匹配失败 | 1 | 拆分为独立新增计划文件和独立重建看板，继续执行 |
| 第一次同步 `task_plan.md` 的补丁包含不存在的尾部上下文 | 1 | 缩小补丁匹配范围后成功更新，不影响文件内容 |
| 路线 Contract 测试未识别无"距离"前缀的 `3.2 km` | 1 | 对照现有 fixture 和旧解析器后，将距离前缀改为可选，并补回归测试 |
| Phase 2 场景诊断输出遇到 Windows GBK 无法编码 `¥` | 1 | 设置 `PYTHONIOENCODING=utf-8` 重复诊断，业务结果未受影响 |
| Phase 2 报告初版被渲染为 Phase 0 标题 | 1 | 扩展评测 renderer 的 suite 识别并重新生成独立 Phase 2 报告 |
| 8098 端口探测被沙箱误报为无监听（实际已有 MCP server 在跑） | 1 | 复用已运行 server 完成真实 MCP 验证；端口探测结果不再作为唯一依据 |

## 回滚总原则

- 每个 Phase 尽量保持单一职责提交，阶段之间不混合视觉重构和后端协议重构。
- 新字段可选、旧字段保留；新流程通过配置或明确入口接入。
- 发生回归时优先关闭本阶段 feature flag 或恢复适配器兼容路径，不回退用户已有的文档和评测资产。
- 不使用破坏性 Git 命令覆盖用户未提交的工作。

## 当前暂停点与下一轮计划

已建立认知基线并完成朋友 `Ay` 分支的深度评估。`origin/Ay` 分支已率先完成 Phase A-E 架构重构与约束链路集成，且 44 个单元与集成测试全部通过；当前工作区（bucket1）已包含合并后的 Phase A-E 代码，全量回归 61/61 通过。

2026-08 收尾修复已完成并推送到 main：v2 页面替代 v1 成为唯一入口、酒店超预算候选回退标记、`_status` 来源误标修复、DeepSeek 超时配置健壮化、MCP 默认端口统一为 8098、静态资源与样式文件统一、清理调试输出与过时文档。Phase 2 报告已用修复后代码重新生成。

2026-08-14 完成两轮 agentic 预验证实验（本地假工具 + 真实 MCP），结论：DeepSeek 自主补查可行且有真实价值，但必须"后端回填 id + 强 schema 校验 + 只读白名单"为前提；据此新增 Phase 2.5，并强化 Phase 2.2 为"稳定 id 事实层"。

下一轮建议（调整后顺序）：
1. Phase 2 收尾：混合来源/降级测试 + 2.8（工具 description 精修、`response_format=json_object`）→ 宣告 Phase 2 完成。
2. Phase 2.2 稳定 id 事实层：MCP 结构化返回或后端回溯映射生成 id（Phase 2.5 的前置条件）。
3. Phase 2.5 工具增强规划脑：迁移验证脚本 → MCPToolAdapter 连接复用 → 三步灰度（天气 → POI/酒店 → 路线），每步离线评测 + 真实对照。
4. 前端交互增强（可与 2/3 并行）：展示 `source_meta` 来源置信度、`validation` 契约校验及 `selection` 候选排序得分与理由（`candidate_contracts` 已具备数据）。
5. Phase 3：确定性预算反馈循环与全局质量门（预算偏差 0.6230 与低预算/多人预算硬约束满足率 0 是当前最痛指标；Phase 2.5 增强脑仅作提议者）。
6. Phase 4 结构化追问、Phase 5 持久化/真实进度/E2E 按序推进。

