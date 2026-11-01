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
| Phase 2 | 事实结构化、候选评分和可解释选择 | 稳定 id 事实层、排序器、工具适配和测试 | 已完成（2026-09-05 验收） |
| Phase 2.5 | 可选工具增强规划脑（agentic 补查） | 只读白名单、id 回填、三步灰度、新增评测指标 | 待开始 |
| Phase 3 | 预算反馈和全局质量门 | 调整循环、全局评审、差异字段 | 已完成（2026-09-05） |
| Phase 4 | 结构化追问与计划版本 | refine API、版本 Diff、前端交互 | 已完成（2026-09-05） |
| Phase 5 | 持久化、真实进度和产品化质量门 | Memory、事件流、观测、E2E | 待开始 |

执行分流（2026-08-19）：Phase 2.5 是可选实验支线，不再作为 Phase 3 的必经阶段。Phase 2 达到 D2/D11/D12 验收闸门后，产品主线优先进入 Phase 3；只有当前目标明确为验证 agentic 补查时，才在独立 feature flag/分支上推进 Phase 2.5。

## 当前改动合理性评审（2026-08-24）

| 改动组 | 判断 | 保留价值 | 当前代价/限制 |
|---|---|---|---|
| `4623a8b` 旧 `/api/multi-agent-chat` 冒烟测试 | 合理，已形成独立提交 | 先锁定兼容行为，再决定退役或改造旧链路 | 目前只覆盖字符串工具结果，不能作为结构化 MCP 兼容证据 |
| `e612dc9` DeepSeek Pydantic 输出契约 | 合理，已形成独立提交 | 把模型 JSON 漂移挡在边界，修复字符串布尔值等类型问题 | 属预防性加固；缺真实固定场景、错误分类和重试观测，不能据此声称真实格式事故已解决 |
| `7a27c02` 稳定地点 id 第一版 | 合理，已形成独立提交 | 位置序号不再影响 id，候选可被模型引用和后端回溯 | 名字+坐标只是确定性 fallback；provider id 优先、无坐标同名冲突和 `id_version` 仍需定义 |
| 未提交结构化 MCP 适配 | 方向合理，当前实现不满足合并闸门 | 减少文本正则依赖，为稳定事实 Contract 铺路 | `MCPToolbox.call()` 全局从 `str` 放宽为 `dict/list`，旧天气/路线/预算/Writer 仍按字符串处理；FastMCP 原生 `structured_content/data` 未优先读取；响应判定和列表元素校验过宽 |
| V3 页面和 `/v3` 路由 | 已关闭，按废案处理 | 历史评审结论保留在文档中，避免再次误判为产品能力 | 2026-08-24 已删除原型文件和路由，不再投入接线、测试或维护成本 |
| `.dsh/` 本地技能资产 | 对实验环境有用，产品提交中不合理 | 可辅助独立 DSH 试验 | 与 TravelMind 运行时无直接依赖，会放大评审范围和发布包噪音 |

结论：三个已提交小步具备独立价值；未提交结构化 MCP 是**半完成的跨入口契约迁移**，应先闭环或隔离，不能仅凭 `90/90` 离线回归通过就合并。V3 已按废案删除；`.dsh/` 继续留在产品提交之外。文档同步应在对应代码和测试闸门通过后最后提交，避免计划状态领先于源码。

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

- [completed] 2.1 定义 `PlaceCandidate`、`HotelCandidate`、`RouteFact`、`WeatherFact` 和来源元数据。
- [in_progress] 2.2 建立稳定 id 事实层：由适配器把 FastMCP 结果收敛为稳定结果封装，规划器显式选择结构化数据，旧入口显式读取文本；结构化数据按工具专属 Pydantic 模型校验，失败时回退文本兼容解析。**铁律：模型永不生成 id，只能引用后端给出的 id；原始 `dict/list` 不直接泄漏给仍使用字符串协议的旧 Agent。**
- [completed] 2.3 统一真实地点判定、城市匹配、坐标有效性、类别、价格区间和来源置信度第一版。
- [completed] 2.4 实现候选硬过滤第一版：目的地、重复、坐标、预算上限和用户排除项；营业/时间窗仍由后续供应商事实补强。
- [completed] 2.5 实现可解释排序第一版：偏好匹配、距离、评分、价格、事实完整度、天气适配和重复惩罚。
- [pending] 2.6 将排序分数、入选理由、落选原因写入可选响应字段，不破坏原字段（D2）。
- [in_progress] 2.7 增加高德成功、限流、Key 缺失、本地 fallback 和混合来源测试。
- [ ] 2.8 低成本增强（由 2026-08-14 验证实证）：精修 `search_poi` 等工具 description（写明一次返回全部类别，避免重复调用与重复 token）；DeepSeek 输出加 `response_format={"type":"json_object"}` 约束，复用现有 `_parse_json_object` 兜底。

### 验收标准

- 规划器不再依赖单一自由文本正则才能获得核心地点字段。
- 每个入选 POI/酒店都可定位到来源、坐标、评分理由和**稳定 id**；缺失信息明确标记。
- 重复地点和目的地串台在进入模型前被过滤或显式警告。
- 任何 LLM 路径产出的真实地点都能回溯到后端生成的 id；模型生成的 id 一律视为非法。
- Phase 0 的真实地点绑定率、重复地点率和 fallback 指标可量化比较。
- `/api/chat`、`/api/multi-agent-chat` 在结构化 MCP 开启后仍保持既有文本响应；`/api/plan` 可消费结构化 POI/酒店，坏元素不会使整组有效候选丢失。
- 至少一组真实 FastMCP 协议级测试覆盖 `structured_content/data`、文本 content、空结果、非法 schema 和文本 fallback，而不只测试手工构造的 `dict`。
- `/api/plan` 新增的 `candidate_contracts` 是可选、版本化字段；旧 `pois`、`hotels` 和前端读取路径保持兼容。

### 暂停条件

- 高德字段在不同接口中不稳定：先在适配器层归一化，不把供应商字段直接泄漏到规划器。
- 结构化和文本返回同时维护导致契约不明确：冻结新字段命名，先补测试再继续。

### 回滚点

保留旧工具返回路径，通过 feature flag 或兼容解析器切回；候选排序可单独关闭，回到原候选顺序。

### 当前小步结果

- 已新增 `sync/multi_agent/contracts.py`、`fact_normalizer.py`、`candidate_ranker.py`，并以 `tests/test_phase2_contracts.py` 覆盖地点、酒店、路线、天气、来源、过滤和排序。
- 规划器保留旧 `pois`/`hotels` 字段，DeepSeek 候选输入优先使用有效坐标、真实地点、去重和排序结果；`candidate_contracts` 的构建与消费代码已就绪，但 `run()` 尚未接线产出（见工程债务 D2）。
- MCP Server 仍返回旧文本；工作树已尝试让适配器和 `MCPToolbox` 透传 `dict/list`，但这已改变旧字符串边界且三入口兼容尚未闭环，因此只计为 D12 原型，不计为 Phase 2 完成项。
- Phase 2 初始专项/集成测试曾为 `7/7`、全量回归 `38/38`；截至 2026-08-24 当前工作树全量回归为 `90/90`，Node 检查、`pip check` 和 `git diff --check` 通过。该结果仍不包含真实 FastMCP 结构化协议和浏览器端到端验收。
- 独立报告：`tests/evals/phase2_report.json`、`tests/evals/phase2_report.md`。与 Phase 1 相比，路线超容忍率由 `0.0750` 降至 `0.0500`，预算偏差由 `0.6217` 降至 `0.6191`，fallback 率由 `0.0833` 升至 `0.1000`。
- 2026-09-05 D12 完成并提交（`dfb5a5b`）：适配器新增 `MCPToolResult`（`tool_name`/`text`/`data`/`source`/`validation_error`）与 `call_mcp_tool_result(_async)`，`call_mcp_tool(_async)` 恒返回字符串；`MCPToolbox` 提供 `call_text()`/`call_structured()`，`call()` 保留为文本别名，旧 6 个 Agent 文件零改动；规划器 5 个调用点显式化（POI/酒店走 `call_structured` + Pydantic 解析，天气/跨城/市内走 `call_text`）；`structured_result.py` 重写为响应模型层（`PlaceCandidate`/`POIResponse`/`HotelResponse` + `parse_poi_response`/`parse_hotel_response`，坏元素过滤并回填 `validation_error`，删除 `is_structured_*`/`as_list`）；适配器构造参数接受 FastMCP 实例支持内存直连。结构化数据只读 FastMCP 解包后的 `result.data`，不读线协议 `structured_content`（3.4.0 非 object 返回被 `{"result": ...}` 包裹的 wrap 陷阱）。新增 `tests/test_mcp_protocol.py` 11 个用例（dict/无注解 str/wrap 陷阱/JSON 文本兜底/空文本/异常/非法 schema + 三入口回归，其中旧链路 dict 返回用例直接覆盖 2026-08-24 复现的 Writer 崩溃）。全量回归 112/112，评测 4/4（141 次调用/4 次 fixture 失败已固化为 `test_baseline_eval` 断言）。
- 2026-09-05 D2 完成并提交（`029ef20`）：`run()` 在片区聚类后快照候选池产出可选、版本化 `candidate_contracts`（`version`/`contract_version`/`source_mode` + POI/酒店入选项，候选携带 `selection.score/reasons`、`source_meta`、cluster 标注）；契约对齐文档声明新增 `source_mode=legacy_text_compatible`；取舍决策——落选原因暂不输出（现有构建器只收入选项，落选理由在 rank_candidates 被丢弃，需要时先扩展 `_normalize_and_rank_*` 再接 D3 展示）。新增 run() 级离线测试 `test_run_wires_candidate_contracts_and_keeps_legacy_fields`：断言版本化内容、cluster 字段和旧 `pois`/`hotels` 兼容。全量回归 113/113，评测 4/4（141/4 断言保持，二重排序不影响指标与调用次数）。
- 2026-09-05 D11 完成并提交（`05def10`）：`_invoke_parsed` 返回 `(parsed, attempt_count)`，重试预算耗尽抛 `DeepSeekInvocationError`（`error_kind` 区分 schema/call）；四类脑调用的失败状态从笼统 `parse_failed` 细化为 `schema_failed`（输出无法解析/校验，含行程可用项不足）与 `call_failed`（网络/鉴权/超时），统一携带 `error_kind`/`attempt_count`/`fallback_reason`；`llm_status` 保持结果语义（成功恒为 `used`，四个 `!= "used"` 消费方零改动），trace 由 `_record` 从 `attempt_count>1` 派生 `retry_success`；规则降级行程步显式记录 `rule_fallback`；`ReviewOutput` 增加跨字段校验（`needs_repair=true` 必须带 `repaired_plan`）。设计取舍：酒店价格估算与路线评审的脑降级仍在组件层消化（`cost_source`/`route_judgement` 已可观测），trace 细化聚焦规划脑与体检两个主脑步。离线新增 16 个 DeepSeek 契约测试与 5 个 trace 状态测试；全量回归 124/124，评测 4/4（141/4 断言保持）。真实固定 DeepSeek 场景基线（`used/retry_success/schema_failed/call_failed/rule_fallback` 计数）归入 Phase 2 真实验收步执行。
- 当前未宣告 Phase 2 完成；剩余闸门为高德成功/限流/Key 缺失/本地 fallback 与混合来源测试、真实服务对照和浏览器主流程验收，不降低真实地点与坐标护栏来换取表面 fallback 指标。

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

2026-08-19 复核边界：现有运行日志和离线报告里没有一次可归因于真实 `/api/plan` 的 DeepSeek JSON/Schema 失败记录；离线报告中的 `rule_fallback` 是 fixture 主动设置 `llm_status=unavailable`。因此 `deepseek_contracts.py` 当前属于**预防性加固**，已有实证是独立 agentic 实验中的字段漂移、Markdown 围栏和模型自造 id，而不是已确认的线上格式事故。进入 Phase 2.5 前先补真实固定场景和降级观测，避免把潜在风险写成已发生故障。

### 铁律（由验证得出，违反即回退）

1. `candidate_id` 绝不允许模型生成：模型输出只填 `title`（或引用工具返回的编号），后端用名字/坐标回溯匹配 `normalize_place_candidates` 生成的候选并回填真 id；匹配不上的降级 `is_suggestion=true` 或丢弃。
2. 输出 schema 显式列出前端全部字段；`response_format={"type":"json_object"}` + Pydantic 校验 + `_parse_json_object` 清理兜底。只对 JSON/Schema 错误回喂重试一次；网络、鉴权、限流和超时分别记录，进入对应降级状态。
3. 补查返回的新候选必须回传后端重新 normalize 生成 id，再并入候选池，绝不直接采信模型转述。
4. 工具只读白名单：`get_weather`、`search_poi`、`search_hotels`、`amap_plan_routes`、`amap_geocode`；排除 `write_itinerary_file` 等副作用工具。
5. `trace` 必须区分 `used`、`retry_success`、`schema_failed`、`call_failed` 和 `rule_fallback`；业务函数返回降级对象时不得继续记成普通 `success`。

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
- 至少运行一组固定真实 DeepSeek 场景，记录 `used/retry_success/schema_failed/call_failed/rule_fallback` 次数；没有真实观测时只声明“契约测试通过”。

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

### 具体步骤（已完成 2026-09-05）

- [x] 3.1 将质量检查拆为硬门槛和软评分，先验证硬门槛。
- [x] 3.2 计算全天时间线、移动耗时、开放时间、用餐间隔、休息间隔、天气适配和返程安全余量。
- [x] 3.3 定义预算调整优先级：先替换同片区高价活动，再调整酒店档位/住宿策略，最后调整交通或非硬性活动。
- [x] 3.4 增加最多 2-3 轮的预算/可行性反馈，保留每轮输入摘要、调整动作和结果。
- [x] 3.5 超出循环上限仍不满足时，输出最接近方案和明确缺口，不无限重试。
- [x] 3.6 增加返回目的地、跨城日期和最后一晚住宿一致性检查。
- [x] 3.7 增加预算偏差、路线超容忍率和不可行行程测试。

### Phase 3 实际结果（2026-09-05）

- 新增 `sync/multi_agent/budget_optimizer.py`（确定性反馈循环，零 LLM/工具调用；杠杆顺序：同片区高价项替换 activity+food → 住宿 `budget_strategy=cheapest_first` → 非硬性付费活动删减；每动作记录 before/after/saved/reason，轮上限 2，deepcopy 快照异常回滚）、`sync/multi_agent/quality_gate.py`（硬门槛：返程后住宿串台、item 总量下限、硬约束预算↔verdict、单日时长粗检；违规写独立字段 `quality_review.gate_violations`，不改 issues/scores/source）、`sync/multi_agent/itinerary_builder._retime_day_items`（删项后时间槽重排）。
- `run()` 集成：循环插在评审后、市内路线重建前（临时预算用 movement_count 口径，决策只用相对节省量，金额标注"调整期估算"）；门禁在 BudgetAgent 后读取最终 verdict；响应新增顶层 `budget_adjustments`（同步写 `budget.adjustments` 供 markdown/前端）；`TRAVELMIND_BUDGET_LOOP` 默认 on，off 为回滚开关（off 时响应 `{enabled:false}` 且跳过门禁）。
- 决策记录（用户确认）：循环默认开启；评测 141 调用断言重定为实测 **139**（删项减少 2 次 judge_route），指标重定基线并生成 `tests/evals/phase3_report.*` 对照。
- 评测对照（Phase 2 → Phase 3）：**预算偏差 0.6230 → 0.4897**；low_budget 偏差 ~1.9 → 0.854（仍超预算——跨城+最低酒店已超 500 目标，符合"真实调整+缺口可解释"验收口径）；return_transfer_isolation 2107 → 1601 转为预算内且串台率保持 0；fallback 率 0.1000 不变；真实地点绑定率 0.5940 → 0.5903（替换/删项后可定位项微调）；硬约束满足率 0.7500 不变（low_budget/family_budget 数学上无法达标，留待供应商接入）。
- 前端：`#budgetSection` 新增「预算自动调整」折叠块（轮次/缺口/每动作 改了什么·为什么·代价 + 口径标注）；体检详情新增「硬门槛提醒」区块（gate_violations 全量展示）；导出 Markdown 与后端 markdown_writer 同步两段。
- 测试：新增 `tests/test_phase3_budget_loop.py` 20 用例（优化器 10 + 门禁 6 + run() 级 4）与 eval 对照测试 1 例；全量回归 145/145，评测 5/5（新基线 139/4 固化）。

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

### 具体步骤（已完成 2026-09-05）

- [x] 4.1 定义 `plan_id`、`version`、`parent_version` 和输入约束快照。
- [x] 4.2 增加结构化 refine 请求，包含当前计划、用户追问和可选修改范围。
- [x] 4.3 将追问解析为增量操作：替换地点、调整预算、改变节奏、增加/删除活动、修改住宿策略。
- [x] 4.4 对增量操作重新执行受影响的候选、路线、预算和质量检查。若 Phase 2.5 已启用，受影响部分的候选补查可复用工具增强脑；本轮不依赖它。
- [x] 4.5 返回结构化 Diff、解释和最新 Markdown；失败时保留旧版本。
- [x] 4.6 前端追问改为调用 refine 接口，展示版本和修改摘要。

### Phase 4 实际结果（2026-09-05）

- 新增 `plan_version.py`（`bootstrap_version`/`next_version`/`compute_diff`/`build_explanation`：version 从 0 起、refine_history 截断 10 条、constraint_snapshot 首次引导落盘、diff 含 items_changed（day/action/item_id/before/after，同日同类一删一增配对为 replaced）+ budget（含 verdict 前后）+ preferences + constraints_changed 预留字段）与 `refine_parser.py`（`build_refine_payload` 紧凑摘要含 item_id 与候选 type、`locate_targets` 两阶段定位——retime 会重生成 id 故先定位后应用、`apply_operations` 七类操作与护栏）。
- 契约与脑：`RefineOperation`/`RefineOutput`（action 必填、budget>0、pace/strategy 枚举白名单、operations≤12、无操作时 answer 必填的跨字段校验）+ 第 5 个脑方法 `parse_refine_ops`（降级三态与既有方法一致）。铁律落实：模型只引用 plan 摘要中的 item_id 与候选池 candidate_id，后端逐条校验，非法引用跳过并进 explanation。
- `StructuredTravelPlanner.refine_plan(plan, message)`：**run() 冻结不动**。入口校验 7 个必需键（缺 → failed）；状态恢复**禁止重跑 `_normalize_preferences`**（canonical 交通 code 会被重置），只重跑幂等的 `_normalize_preference_profile`；重算尾部用 rule 体检替代 LLM 体检（防止 repaired_plan 覆写用户 op），顺序与 run() tail 一致；`TRAVELMIND_REFINE` 服务端开关（off → 503）。
- 护栏（与 gate/loop 同口径）：remove 后总量（含 note）≥ max(2, days×2) 且每日 concrete≥2；add 每天 movable<5、无候选时落 `llm_suggestion` 建议项不进地图；同一 (day,item) 只接受第一条结构 op；replace 不触发 retime（保留整天原始时间槽），add/remove 才 retime。实现中发现并修复：候选查重不能用伪 item 调 `_itinerary_used_place_keys`（POI 的 id 字段名与 item 的 poi_id 不同、location 是坐标 dict，查重键永远错位），改为显式 `_candidate_place_keys`（id + 名称|地址）。
- API：`POST /api/refine-plan`（400 缺键/空 message、503 开关关闭）；旧三端点零改动。
- 前端：`sendMessage` 三路径——有计划先走 refine（ok+changed：更新计划/重渲染/版本徽标+解释；ok+无变更：只回答），failed/不可用自动回退旧 `/api/multi-agent-chat` 并标注「旧链路文本回答，未修改当前计划」；无计划直接走旧链路。快照整包克隆自动持久化 version/refine_history。
- 测试：新增 `tests/test_phase4_refine.py` 44 用例（版本 7、契约 8、脑 3、应用 14、编排 6、HTTP 2、前端 3 + 辅助）；全量回归 189/189，评测 5/5（139/4 不变——refine 不触碰 run_baseline），py_compile/`node --check`/`git diff --check` 通过。

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

- [x] 5.1 用 SQLite 保存明确偏好、计划版本、评测摘要和任务状态。（2026-09-05，`67aa8c9`）
- [x] 5.2 增加缓存、幂等键、超时、重试预算和敏感信息脱敏日志。（2026-09-05：幂等键 clientRequestId + 入库脱敏 redact_secrets + 同步回退 AbortController 120s 超时（D7 最小修复）；缓存/重试预算归 D1 与 Phase 2.5 前置，不在本轮）
- [x] 5.3 产生真实阶段事件，前端用 SSE 或 WebSocket 消费；断线可查询当前状态。（2026-09-05，`f464e7c`：SSE + DB 单一事实源，Last-Event-ID 重放，GET /api/task/{id} 查询）
- [~] 5.4 接入结构化 trace 和可选 Langfuse/OpenTelemetry，不让观测依赖主流程成功。（部分完成：trace/事件/快照全部落 SQLite 即本轮结构化观测，持久化失败吞错不影响主流程；Langfuse/OTel 按计划保持可选未接）
- [x] 5.5 使用 Playwright 覆盖桌面、移动端、规划、追问、编辑、导出和错误状态。（2026-11-01）
- [x] 5.6 建立质量阈值、回归报告和发布前检查清单。（2026-11-01）

### Phase 5 已落地部分（2026-09-05）

- **持久化**（`67aa8c9`）：新增 `sync/persistence.py`（sqlite3 标准库，5 表：tasks/task_events/plan_snapshots/user_preferences/eval_summaries；WAL + busy_timeout；每方法吞异常返回安全默认；`TRAVELMIND_PERSISTENCE=off` 全 no-op 不建目录；14 天顺手清理；running 超 10 分钟判 interrupted）。`/api/plan`、`/api/refine-plan` 写计划快照与 learnedHints；`run_baseline.main()` 写评测摘要（`run_all()` 绝不触库——139/4 测试边界）。入库统一过 `redact_secrets`（敏感键名整体掩码 + sk-/key= 模式替换）。`.gitignore` 补 `/data/`（journal/wal/shm 伴生文件不被 `*.db` 覆盖）。
- **真实进度**（`f464e7c`）：`StructuredTravelPlanner` 增加 `threading.local` 进度钩子——planner 是单例，实例属性在线程池与后台任务线程并发时会串台；`_record` 首尾发 step_start/step_end，回调异常吞掉，**事件绝不进 trace 数组**（139 断言保护，全量 209/209 与评测 139/4 均已验证）。`POST /api/plan-async`（daemon 线程 + clientRequestId 幂等 + off 时 503）；`GET /api/plan-events/{task_id}`（SSE 以 task_events 表为唯一事实源——无内存态、进程重启后可恢复、Last-Event-ID 续传、孤儿任务补发终态事件、done/error 后关流）；`GET /api/task/{task_id}`（断线可查询 + done 带快照）。
- **前端**：`sendPlan` 双路径——EventSource 可用时走异步（`BACKEND_STEP_TO_STAGE` 把 15 个后端步骤映射到既有 8 阶段进度，step_start 实时点亮）；**回退矩阵禁止二次外部调用**：只有任务未启动（404/405/501/503 或提交网络失败）才回退同步 `/api/plan`，任务已启动后绝不重发；120s 看门狗；done 后 `es.close()` 防重连风暴；`travelmind:activeTask:v1`（sessionStorage）支持刷新恢复进行中任务；同步回退路径补 AbortController 超时（D7）；reset 关闭事件流。顺手修复 `.progress-step.running` 无样式（只有 `.active`）；静态资源 bump `phase51`；`requirements.txt` 显式声明 `sse-starlette==3.0.3`。
- **测试**：`tests/test_phase5_persistence.py` 10 例（tmp DB 隔离、off 不建文件、脱敏、事件增量、幂等、stale、快照/偏好/摘要往返、坏路径吞错）+ `tests/test_phase5_task_events.py` 10 例（SSE 事件序列/seq 单调/成对断言、幂等重提交调用数不增长、任务状态查询、off 503、未知 404、回调异常不影响 run、trace 形状不变、前端契约 4 断言）。全量 209/209、评测 5/5、pip check 通过。

### Phase 5 收尾：E2E 与发布质量门（2026-11-01）

- **5.5 Playwright E2E**（`tests/e2e/`）：`fixture_server.py` 用生产 FastAPI app + 评测 fixture toolbox/brain 起服务，零 Key、零网络、零日期依赖；`E2EBrain` 补 `parse_refine_ops`（评测 fixture 没有该方法，否则 `/api/refine-plan` 500 会让追问 spec 假绿）；`freeText == "__e2e_force_error__"` 时 `run()` 抛错，单服务器双场景；`E2E_PERSISTENCE_OFF=1` 覆盖 503 回退；独立 `data/e2e.db` 每次启动清理。五个 spec × 桌面/移动两个 project（iPhone 14 视口，显式覆盖 `defaultBrowserType` 为 chromium——`devices["iPhone 14"]` 默认 webkit 而本项目只装 chromium）。配置走单 `webServer`：MCP Server 的 streamable-http 端点对普通 GET 返回 406，不能作为就绪探测目标，因此不采用双 webServer。
- **5.6 发布质量门**（`tests/evals/release_gate.py` + `tests/test_release_gate.py`）：`compare()` 是纯函数（不触 DB/网络/历史文件），默认参照物是仓库内已提交的 `phase3_report.json`（干净 clone 可复现）；`total_calls` 不进闸门（调用数是成本不是质量）；指标缺失或 None 跳过而非判回退；CLI 退出码 0 通过 / 1 回退 / 2 数据不可用。四条指标：`budget_deviation`（相对 10%）、`real_place_binding_rate`（绝对 0.05）、`hard_constraint_satisfaction`（绝对 0.05）、`fallback_rate`（绝对 0.10）。
- **E2E 逼出的真实缺陷**：`.topbar` 因 `.glass-panel` 的 `backdrop-filter` 成为层叠上下文却不带显式 `z-index`，`.export-menu` 的 `z-index:30` 被困在其中；DOM 更靠后的 `.main-tabs`（同为 backdrop-filter 层叠上下文、`z-index:auto`）在 390px 下盖住导出菜单并吞掉点击，"导出 Markdown"/"打印/保存 PDF" 在移动端完全不可点。修复是给 `.topbar` 显式 `position: relative; z-index: 2`。这是移动端视口覆盖（Phase 2 真实验收遗留缺口）第一次抓到产品缺陷，而非仅仅是测试问题。
- **三个 spec 的写法修正**：`mobile-viewport` 原先用文件级 `test.skip(({}, testInfo) => testInfo.project.name ...)` 做条件跳转，而该 callback 只收到 fixtures，`testInfo` 恒为 undefined，两个 project 都必然 TypeError——改为 test 体内 `test.skip(condition, description)`；`edit-export` 原先点 `#exportButton` 就等 download，而该按钮只切换 `#exportMenu` 的 hidden，真正触发下载的是菜单内 `[data-export="markdown"]`（导出菜单 UI 上线后 spec 未同步）；`error-state` 断言 `.bubble` 可见，但失败气泡由 `sendPlan` 的 catch 写进默认折叠的 `<details class="followup-panel">`，需先展开（与 `refine-followup.spec.ts` 同一处理）。
- **验证**：E2E 11 通过 / 1 跳过（桌面正确跳过移动专属的横向溢出断言），3.1 分钟；全量单测 220/220；发布质量门对照 `phase3_report.json` 通过；`py_compile`、`node --check`、`git diff --check`、`pip check` 通过。8010/8098 未监听，以上仍只覆盖离线受控路径。

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
| D1 | MCPToolAdapter 每次调用新建连接 | `call_mcp_tool` 每次 `asyncio.run` + 新建 `Client`（2 次 HTTP 握手）；单次规划数十次调用；agentic 实验 6 调用 27.6s | 先选定“请求级异步 Client 会话”或“专用后台事件循环”；禁止把全局 Client 跨 `asyncio.run`、线程池和事件循环直接共享 | 高 | Phase 2.5 前序条件 | 未开始（调试 print、空 content 防护已清理） |
| D2 | `candidate_contracts` 生产未接线 | `_build_candidate_contracts` 已定义但 `run()` 未调用；消费端 `itinerary_builder` 已就绪；文档声称"新增可选字段"与实际不符（2026-08-14 核对） | 在 `run()` 接入输出可选字段并补断言测试，或修正文档声明 | 高 | Phase 2 收尾；D3 前提 | 已完成（2026-09-05，`029ef20`：`run()` 片区聚类后快照产出 + `source_mode` 对齐 + run() 级响应断言；落选原因延后至 D3 前定结构） |
| D3 | 前端不展示来源/排序理由 | `source_meta`/`validation`/`selection` 后端已生成（D2 接线后才有产出），页面未展示 | 结果页展示来源置信度、入选/落选理由 | 中 | 依赖 D2 | 未开始 |
| D4 | 遗留链路退役 | `async/` 4 文件、`sync/agent_chatbot_*.py`、`sync/user_api.py`、legacy `*_agent.py`+`orchestrator.py`；旧 `/api/multi-agent-chat` 已补字符串 Fake 冒烟测试，但尚未覆盖结构化 dict/list | 先补结构化返回兼容测试，再决定保留 API、适配返回类型或明确下线 | 中 | D12 关联 | 冒烟测试已补，退役决策待定 |
| D5 | 重复函数收敛 | haversine ×4（1 份无 clamp）、`_poi_key`×2、`_parse_price_range`×2（全角～处理不一致）、`_default_hotel_area`×3 | 收敛到 `contracts.py`/`text_parser.py` 单一实现 | 中 | — | 未开始 |
| D6 | app.js 单文件约 2300 行 | 双页面历史遗留，维护困难 | 按渲染/请求/编辑/导出拆 ES modules | 中 | 建议 Phase 4 动前端前完成 | 未开始 |
| D7 | 前端 fetch 无超时、错误透传 | 请求可能永久挂起；错误直接显示后端 detail | AbortController 超时 + 结构化错误提示 | 中 | — | 部分完成：同步回退 `/api/plan` 已有 AbortController 120s；其余 fetch（追问、任务快照）仍无超时，待统一收敛 |
| D8 | staticmethod 兼容层 | `structured_planner.py` 约 150 行桥接（Phase E 遗留） | 测试全部改纯函数调用后移除桥接 | 低 | — | 未开始 |
| D9 | 仅测试使用的函数 | `normalize_route_fact`、`validate_place_candidate` 生产链路未使用 | 明确接入或移除，避免误导读者 | 低 | — | 未开始 |
| D10 | 小项合集 | CORS `allow_origins=*`+`allow_credentials=True` 无效组合；`max_tokens=3500` 多日行程截断风险；`write_itinerary_file` 文件名边界；Windows 日志 GBK 编码 | 逐项顺手修 | 低 | — | 未开始 |
| D11 | DeepSeek 降级不可准确统计 | `parse_failed` 作为普通返回进入 `_record`，外层 trace 仍可能记 `success`；现有日志没有保存真实模型状态和重试次数 | 增加 `error_kind`、`attempt_count`、`fallback_reason` 和降级状态；用固定真实场景建立基线 | 高 | Phase 2 收尾；Phase 2.5 前提 | 已完成（2026-09-05，`05def10`：schema/call 错误分类 + attempt_count + fallback_reason + trace 五态 + 跨字段校验；真实固定场景基线归入 Phase 2 真实验收步） |
| D12 | 结构化 MCP 跨入口兼容 | `MCPToolbox.call` 开始透传 `dict/list`；旧 Writer/天气/路线/预算 Agent 仍按字符串拼接、`join`、`startswith` 或正则处理。当前适配器只读 `content[0].text`，结构化判定只要求命中任一字段，候选列表也未逐项校验 | 在适配器边界建立稳定结果封装（至少含 `text`、`data`、`source`、`validation_error`）；保留字符串兼容的 `call_text()`，规划器通过 `call_structured()` 显式取数据；优先读取 FastMCP `structured_content/data`，JSON 文本解析只作兜底；POI/酒店用 Pydantic 严格校验并过滤坏元素；覆盖实际 FastMCP 结果形态和三入口 | 高 | Phase 2.2 收尾 | 已完成（2026-09-05，`dfb5a5b`） |
| D13 | V3 静态原型暴露为路由 | `/v3` 原型只切换固定 DOM，没有请求 `/api/plan`，继续保留会制造产品能力误解和维护分支 | 关闭该方向，删除 `/v3` 路由及 `web/v3_*` 文件；保留本条作为决策记录 | 已关闭 | 前端废案 | 2026-08-24 已删除 |

建议执行顺序：先隔离当前工作树的结构化 MCP、`.dsh/` 和文档三类范围，再按 **D12 → D2 → D11 → 混合来源/真实验收 → 关闭 Phase 2** 推进。原因是 D12 已直接改变公共返回类型，是当前最高回归风险；D2 应建立在稳定事实边界上；D11 随后为真实验收提供准确观测。D1 放在 Phase 2.5 实验支线开始前；D3 依赖 D2；D13 已关闭；D4/D5 作为低风险清理穿插；D6 在 Phase 4 之前完成；D7/D8/D9/D10 不与 Phase 2 收尾提交混合。

---

## 当前任务看板

### 阶段状态

- [completed] 基线勘察与 GitHub 同类项目对比
- [completed] Phase 0：离线评测基线和护栏
- [completed] Phase 1：约束完整进入 `/api/plan`
- [completed] Phase 2：事实 Contract、候选评分与选择（2026-09-05 真实验收后关闭）
- [pending] Phase 2.5：可选工具增强规划脑（agentic 补查）
- [completed] Phase 3：预算反馈循环与全局质量门（2026-09-05）
- [completed] Phase 4：结构化追问、计划版本与 Diff（2026-09-05）
- [completed] Phase 5：持久化、真实进度与产品化质量门（2026-11-01，5.5 E2E 与 5.6 发布质量门收尾）
- [pending] 工程债务 D1/D3-D10（D2/D11/D12/D13 已关闭；D1 为 Phase 2.5 前置）

### Phase 2 当前步骤

- [completed] 盘点现有 MCP 文本返回、规划器正则解析和离线 fixture 字段
- [completed] 定义 `PlaceCandidate`、`HotelCandidate`、`RouteFact`、`WeatherFact` 和来源元数据 Contract
- [completed] 为 Contract 增加事实归一化、硬过滤和可解释排序纯函数测试
- [completed] 接入规划器，同时保留旧文本字段和兼容解析器
- [completed] 定位 fallback 率上升来源：`tight_transfer_tolerance` 场景本地路线段在候选排序接入后转为非 amap 来源（+1/6 组件），与酒店过滤无关
- [completed] 修复酒店候选全部超预算时被静默清空的问题：回退"仅因价格超限"被拒候选并标记 `selection.status="over_budget"`，避免酒店组件整体降级
- [completed] 修复 `fact_normalizer._status` 把 `rule_fallback` 误标为 `amap_fallback`，并统一 MCP 默认端口与文档约定
- [completed] 两轮 agentic 预验证实验（2026-08-14，脚本在 `output/` 待迁移）：证明补查可行、零地点编造；实证模型编造 candidate_id 与字段漂移
- [completed] 新增 `deepseek_contracts.py` 与 DeepSeek 输出 Pydantic 校验 + 回喂重试（2026-08-17）：四类输出在边界用 `model_validate_json` 校验并做类型归一化。该项按预防性加固管理，真实 `/api/plan` 格式失败次数仍未知
- [in_progress] 后端稳定 id 第一版（2026-08-17）：`stable_place_id()` 已用「名字+坐标」替代位置序号；仍需定义 provider POI id 优先、无坐标同名冲突和 `id_version`
- [in_progress] 结构化 MCP 返回准备（2026-08-17）：字段名、规划器侧消费和原始透传原型已实现；真实 MCP Server 仍返回文本，旧入口 dict/list 兼容已发现风险，需改成稳定结果封装后才达到全链路完成
- [completed] D11（2026-09-05）：DeepSeek 错误分类与准确降级 trace 已落地（`05def10`）；真实固定场景基线随 Phase 2 真实验收步执行
- [completed] D12（2026-09-05）：建立稳定结果封装和 `call_text`/`call_structured` 双访问，改用 FastMCP 解包后的 `data` + Pydantic 响应校验，并完成真实协议形态与三入口兼容测试
- [completed] D2（2026-09-05）：在 `run()` 接线 `candidate_contracts` 并增加响应断言；D3 前端来源/排序展示成为下一可选清理项
- [completed] 覆盖高德成功、限流/Key 缺失、本地 fallback 和混合来源，并比较 Phase 2 指标（2026-09-05 真实验收：场景 A/B 覆盖高德成功与 Key 缺失降级，限流路径由离线退避测试覆盖；见 findings.md 验收记录）
- [completed] 2026-09-05 真实验收：真实高德成功/降级、固定 DeepSeek 场景五态基线（used=2，其余 0）、桌面浏览器主流程（控制台 0 错误）；移动端视口遗留 Phase 5
- [pending] 2.8 工具 description 精修与 `response_format=json_object`（低成本增强；真实基线暂无格式失败样本，收益待更多观测）

### 修订后的 Phase 2 收尾方案（2026-08-24）

| 顺序 | 小步 | 交付物与验收 | 为什么现在做 | 优点 | 代价 |
|---:|---|---|---|---|---|
| 0 | 隔离范围 | 确认三个本地提交的目标分支；结构化 MCP、`.dsh/`、文档分别处理，V3 废案已经从工作树删除 | 当前 `main` 领先远端 3 个提交且仍混有产品代码、辅助资产和文档，继续叠加会让回滚和评审失真 | 每组可独立测试、回滚和决定是否发布 | 多一次分支/提交管理 |
| 1 | 完成 D12（已完成 2026-09-05，`dfb5a5b`） | 稳定 MCP 结果封装；`call_text`/`call_structured` 双访问；POI/酒店响应模型；坏元素过滤；真实 FastMCP 协议级测试；三入口兼容测试 | 当前 diff 已改变公共返回类型，属于正在发生的合并风险 | 以后增加结构化工具时边界统一，旧链路不被迫同时重写 | 比直接返回 `dict` 多一个薄适配层和少量模型代码 |
| 2 | 完成 D2（已完成 2026-09-05，`029ef20`） | `run()` 构建并返回可选、版本化 `candidate_contracts`；补 `/api/plan` 响应断言和旧字段兼容测试 | D3 前端来源展示和候选可解释性都依赖真实生产输出 | 小改动即可打通已有构建/消费代码，前后端契约可验证 | 响应体增大；需要明确只输出入选项还是同时输出落选原因 |
| 3 | 完成 D11（代码已完成 2026-09-05，`05def10`） | DeepSeek 返回 `error_kind`、`attempt_count`、`fallback_reason`、最终状态；trace 区分 `used/retry_success/schema_failed/call_failed/rule_fallback` | 没有准确观测就不能解释真实服务对照结果 | 能区分模型格式、网络、鉴权、限流和规则降级 | trace 契约会增加字段，需保持前端容忍未知字段 |
| 4 | Phase 2 验收（已执行 2026-09-05，桌面） | 离线全量/评测、真实高德成功与降级、固定 DeepSeek 场景、桌面/移动浏览器主流程；记录执行与证据来源 | 单元测试通过只证明受控路径，不能代表外部协议和用户流程 | 关闭 Phase 2 的判断有产品证据，不再靠代码存在性 | 真实调用有波动和成本，需固定输入并保留时间戳 |
| 5 | 转入 Phase 3 | 先做预算反馈循环和全局路线门；Phase 2.5 保持可选支线 | 当前评测的主要产品差距是预算偏差和全局路线质量，不是增加更多 agentic 自主性 | 直接改善用户方案质量，范围与指标清楚 | 暂缓工具增强规划脑的探索速度 |

方案取舍：稳定结果封装比“全局透传原始 `dict/list`”多一层代码，但它把 FastMCP 协议、业务结构化模型和遗留字符串协议拆开，是以少量局部复杂度换取跨入口兼容和可演进性。先 D12 后 D11 会稍后获得 DeepSeek 观测，但能优先消除当前工作树已经引入的类型回归；D11 仍是 Phase 2 关闭前的硬闸门。

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

- [in_progress] 前序条件 1：Phase 2.2 稳定 id 第一版已实现；provider id 优先、冲突策略、D12 结构化全链路仍需完成
- [pending] 前序条件 2：D11 DeepSeek 真实观测和准确降级 trace
- [pending] 前序条件 3：D1 MCPToolAdapter 请求级异步会话或专用事件循环（agentic 循环会放大新建 Client 的开销）
- [pending] 2.5.1 迁移 `output/verify_agentic_plan*.py` 到 `tools/verify/` 或 `tests/evals/`
- [pending] 2.5.3-2.5.5 三步灰度：挂 `get_weather` → 加 POI/酒店 → 加路线，每步离线评测 + 真实对照
- [pending] 2.5.6-2.5.7 评测适配与压力场景（预算/天气/返程，与 Phase 3 共用 fixture）

### 工作边界

- 当前阶段文件范围限定为 `sync/multi_agent/contracts.py`、`sync/multi_agent/fact_normalizer.py`、`sync/multi_agent/candidate_ranker.py`、必要的 `structured_planner.py` 和 `tests/`；供应商协议先不改。
- `async/`、旧单 Agent 示例、v2 静态资源和供应商接入保持排除。
- V3 方向已关闭；`web/v3_*` 与 `/v3` 已删除，不再进入后续计划、提交或验收。
- `.env` 内容保持私密；核心测试走离线 fixture，真实服务只作为手动验证路径。
- 维持现有响应契约；后续新增字段必须可选并保留旧入口。

## 提交拆分与合并闸门

本轮工作区曾同时包含模型契约、稳定 id、旧入口测试、结构化 MCP、V3 原型和文档六类目标；V3 已作为废案删除，其余范围按以下顺序拆分，保证每个提交可独立测试与回滚：

1. [completed] `4623a8b test: add legacy multi-agent smoke coverage`：只提交 `tests/test_multi_agent_chat_smoke.py`；专项测试 4/4 通过。
2. [completed] `e612dc9 feat: harden DeepSeek structured output validation`：提交 `deepseek_contracts.py`、`deepseek_brain.py` 和专项测试；专项测试 9/9 通过。`needs_repair=true` 跨字段校验与错误分类继续由 D11 跟踪。
3. [completed] `7a27c02 feat: add stable place identifiers`：提交 `contracts.py`、`fact_normalizer.py`、`text_parser.py` 和专项测试；专项测试 6/6 通过。该提交是第一版确定性 fallback id，不宣称全局唯一。
4. [completed] `dfb5a5b feat: support structured MCP results with text fallback`（2026-09-05）：D12 稳定结果封装、文本/结构化双访问、严格响应校验、内存 FastMCP 协议级集成和三入口兼容已提交。
5. [cancelled] `prototype: add TravelMind v3 visual shell`：2026-08-24 决定按废案处理，已删除路由和静态文件，不创建原型提交。
6. `docs: synchronize implementation status`：最后更新本文、`findings.md` 和 `project-baseline.md`，测试数量、完成状态和已知缺口以提交后的代码为准。

`.dsh/` 属本地 DSH 技能资产，与 TravelMind 运行链路没有直接依赖，保持在产品提交之外。

每个提交至少执行专项测试和 `git diff --cached --check`；结构化 MCP、编排器或公共契约变更必须再跑全量回归与离线评测。

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

2026-11-01：Phase 5 五个小步全部落地，5.5 Playwright E2E 与 5.6 发布质量门收尾后产品主线（Phase 0-5）已无未关闭阶段。本轮工作区在 `main` 上，把遗留的 Phase 5.5/5.6 代码、SSE 终态顺序修复与一批死代码清理分别提交为 `dabc91c`（refactor）、`f78f9b9`（fix）、`9e5353c`（feat）。E2E 11 通过 / 1 跳过（3.1m）、全量单测 220/220、发布质量门对照 `phase3_report.json` 通过、`py_compile`/`node --check`/`git diff --check` 通过；8010/8098 未监听，因此仍只证明离线受控路径稳定，真实高德/DeepSeek 与浏览器端到端验收未做。

遗留事项按优先级：D1（MCPToolAdapter 连接复用）是 Phase 2.5 唯一硬前置；D3（前端展示来源/落选理由）依赖 D2 已产出但页面未消费；D6（`app.js` 单文件约 2800 行拆 ES modules）建议在下次大改前端前做；D7 剩余 fetch 超时待统一；D4/D5/D8/D9/D10 为低风险清理。Phase 2.5 保持可选实验支线。

已建立认知基线并完成朋友 `Ay` 分支的深度评估；相关 Phase A-E 代码已经进入当前代码历史。2026-08-24 当前工作区位于 `main`、HEAD `7a27c02`，相对 `origin/main` 领先 3 个本地提交，并混有结构化 MCP、`.dsh/` 和文档三类未提交范围；V3 废案已经删除。当前工作树全量回归 90/90、Node 语法、`pip check` 和 `git diff --check` 通过；8010/8098 均未监听，因此这些结果只证明离线路径稳定，不代表结构化 MCP、真实 DeepSeek/高德或浏览器端到端验收完成。

2026-09-05 D12 已按闸门完成并提交：`dfb5a5b feat: support structured MCP results with text fallback`（仅 sync/ 与 tests/，文档单独提交）。工作树全量回归 112/112、离线评测 4/4（141 次调用/4 次 fixture 失败已固化断言）、py_compile、Node 语法与 `git diff --check` 通过；8010/8098 未监听，结果仍只证明离线路径与内存 FastMCP 协议级往返稳定，MCP Server 工具继续返回文本，真实 DeepSeek/高德与浏览器端到端验收未做。

2026-08 收尾修复已完成并推送到 main：v2 页面替代 v1 成为唯一入口、酒店超预算候选回退标记、`_status` 来源误标修复、DeepSeek 超时配置健壮化、MCP 默认端口统一为 8098、静态资源与样式文件统一、清理调试输出与过时文档。Phase 2 报告已用修复后代码重新生成。

2026-08-14 完成两轮 agentic 预验证实验（本地假工具 + 真实 MCP），结论：DeepSeek 自主补查可行且有真实价值，但必须"后端回填 id + 强 schema 校验 + 只读白名单"为前提；据此新增 Phase 2.5，并强化 Phase 2.2 为"稳定 id 事实层"。

2026-08-17 完成 DeepSeek 输出结构化校验基础（Phase 2.5 铁律「强 schema 校验」的前置）：新增 `sync/multi_agent/deepseek_contracts.py`，用 Pydantic 为 plan / estimate_hotel_prices / judge_route / review_itinerary 四类输出建立契约；`deepseek_brain.py` 在边界用 `model_validate_json` 校验并做类型归一化（`is_suggestion="false"` -> False、`day="2"` -> 2、评分字符串 -> float），校验失败回喂错误重试（最多 2 次），替代原只做 `json.loads` 的单次解析。2026-08-19 复核确认：仓库中没有真实 `/api/plan` 因 DeepSeek 格式失败的历史证据，该改动按预防性加固定位；仍需补 `needs_repair=true` 必须带 `repaired_plan` 的跨字段校验、调用错误分类、真实 DeepSeek 固定场景和准确降级 trace。

2026-08-17 完成后端稳定 id 第一版（Phase 2.2「后端回溯映射生成 id」路径）：新增 `contracts.stable_place_id()`，以「名字+坐标」生成确定性 fallback id；`text_parser._parse_numbered_section` 不再用位置序号生成 id，`normalize_place_candidate` 统一附加 `stable_id` 并在 id 缺失时回填。当前保留显式传入 id，后续需定义 provider POI id 优先、`id_version` 和无坐标同名冲突策略，因此暂不宣称全局唯一身份。

2026-08-17 为旧 `/api/multi-agent-chat` 链路补冒烟测试（工程债务 D4 第一步）：新增 `tests/test_multi_agent_chat_smoke.py` 4 个用例，覆盖 `PreferenceAgent` 正则解析与 `MultiAgentTravelPlanner.run()` 端到端（离线 Fake 工具箱）。测试锁定了 preference_agent 正则的当前支持范围（如「两人/2人」可用、「两个人/两个孩子」不识别，属已知限制待退役决策时一并处理）。全量回归 80/80、离线评测 4/4 通过。

2026-08-17 完成结构化 MCP 返回的第一版准备：新增 `structured_result.py` 冻结 POI/酒店字段名，规划器侧优先消费 dict，适配器可把 JSON 文本转成 dict/list，文本仍走正则兜底。2026-08-19 复核确认该链路尚未闭环：MCP Server 仍返回文本；适配器还未优先读取 FastMCP `structured_content/data`；旧 `/api/multi-agent-chat` Writer 收到结构化 POI 后会出现 `expected str instance, dict found`。该组改动进入 D12，完成严格响应模型、真实 FastMCP 内存集成和三入口兼容后再标记完成。

2026-08-19 会话审计还确认：`candidate_contracts` 的构建和消费代码存在，但 `StructuredTravelPlanner.run()` 尚未输出该字段（D2）；V3 原型没有请求 `/api/plan`（D13）；`.dsh/` 是本地技能资产。2026-08-24 已将 V3 按废案删除，其余两项分别处理。

下一轮建议（2026-08-24 复核后顺序）：
1. 先按“提交拆分与合并闸门”确认三个本地提交的目标分支，并隔离结构化 MCP、`.dsh/` 和文档；不在混合工作树上继续加业务功能。V3 已关闭，不再占用后续步骤。
2. [已完成 2026-09-05] D12：稳定 MCP 结果封装与 `call_text`/`call_structured` 双访问、Pydantic POI/酒店校验、坏元素隔离、内存协议级测试与三入口兼容（提交 `dfb5a5b`）。
3. [已完成 2026-09-05] D2：在 `run()` 接线并输出可选、版本化 `candidate_contracts`（含 `source_mode=legacy_text_compatible`），run() 级响应与旧字段兼容断言已落地（提交 `029ef20`）；落选原因暂不输出，D3 做前端来源/落选展示时再定结构。
4. [代码已完成 2026-09-05] D11：`error_kind`/`attempt_count`/`fallback_reason` 与 trace 五态已落地（提交 `05def10`）；用固定真实 DeepSeek 场景建立 `used/retry_success/schema_failed/call_failed/rule_fallback` 基线，随 Phase 2 真实验收步执行，再判断 `response_format=json_object` 的收益。
5. 补高德成功、Key 缺失、本地 fallback 和混合来源测试，重跑全量回归、离线评测、真实服务对照和主页面 Playwright 检查，满足全部闸门后关闭 Phase 2。
6. 产品主线进入 Phase 3，处理预算偏差、低预算/多人预算硬约束和全局路线质量；Phase 2.5 保持可选实验支线，完成 D1/D11/D12 前置后再按天气 → POI/酒店 → 路线三步灰度。
7. Phase 4 结构化追问、Phase 5 持久化/真实进度按序推进。

