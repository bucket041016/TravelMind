# TravelMind 勘察发现与阶段发现

> 合并自根目录 `findings.md`（发现记录）与 `CONTINUATION_SUMMARY.md`（续接摘要），2026-08-04 去重整理；代码根目录为 `my-langgraph-agent-main/`。
> 规则类约束见 [workspace-rules.md](workspace-rules.md)，阶段结果与看板见 [implementation-plan.md](implementation-plan.md)，本文件只保留发现性结论和续接入口。

## 初始范围

- 项目根目录包含 `async/`、`sync/`、`web/`、`tests/`、多个 README/升级文档和环境配置。
- 当前分支为 `main`，相对 `origin/main` 无工作区改动（原勘察时记录）。
- `rg.exe` 在本环境启动失败，文件检索改用 PowerShell。

## 文档与产品定位

- 产品名为 TravelMind，目标是结构化旅行规划工作台，不是只返回自然语言的聊天机器人。
- 主要链路：用户表单/追问 -> FastAPI -> 规划编排 -> MCP 工具 -> 高德事实数据与 DeepSeek 推理 -> 结构化结果页。
- 主要事实能力：天气、跨城路线、多种市内路线、地理编码、景点/餐厅/酒店 POI、预算估算、Markdown 行程文件。
- 主要前端能力：结构化行程、地图、每日行程编辑、预算、住宿、智能体检、追问、Markdown 导出和打印/PDF。
- 对外约定端口：Web `8010`，MCP `8098/my-custom-path`。Web 启动时必须显式设置 `MCP_SERVER_URL`，否则会落到错误的默认地址。
- 外部配置核心为 DeepSeek Key 和高德 Web 服务 Key；高德调用有缓存、最小间隔、重试和最大缓存条数配置。

## 代码架构初读

- `sync/travel_web_app.py` 同时承载三条后端路径：
  - `/api/chat`：`TravelAgent`，基于 LangGraph `StateGraph` 的单 Agent ReAct，维护会话历史。
  - `/api/multi-agent-chat`：`MultiAgentTravelPlanner`，先用 `PreferenceAgent` 解析，再用线程池并行天气/路线/POI/预算 Agent，最后由 `WriterAgent` 汇总 Markdown。
  - `/api/plan`：`StructuredTravelPlanner`，接收结构化表单字段，输出结构化旅行计划，是当前用户端主路径。
- `MCPToolAdapter` 通过 FastMCP Client 连接 MCP URL；同步调用用 `asyncio.run`，每次调用创建一个新的异步 Client，上层 Agent 通过统一 `MCPToolbox` 调用。
- 结构化规划的首要依赖是本地 MCP Server，而不是直接在 Web 进程里调用高德；Web 只在 `/api/map-static` 里直接代理高德静态图。
- `structured_planner.py` 代码规模很大，包含偏好归一化、天气建议、跨城/市内路线、POI/酒店、片区聚类、路线评审与替换、预算、DeepSeek 行程生成/复核、地图和 Markdown 渲染等多个职责。
- DeepSeek 规划脑是可选增强层：代码对结构化 JSON 解析、调用失败和非法输出有规则降级路径；高德/供应商事实和本地知识库兜底共同构成事实层。

## MCP Server 与外部依赖

- 同步 MCP Server 暴露 `get_current_time`、`get_weather`、`amap_geocode`、`amap_plan_routes`、`plan_route`、`search_poi`、`search_hotels`、`estimate_budget`、`write_itinerary_file`。
- 高德请求集中经过缓存、最小间隔和 QPS 重试逻辑；天气优先高德，随后使用 `wttr.in`，两者失败时返回说明性文本。
- POI/酒店在高德 Key 缺失或请求失败时降级到本地知识/规则；航班、铁路、酒店供应商目前只有占位适配器，不展示实时班次、库存或可预订价格。
- MCP Server 的代码默认端口仍是 `8083`，仓库文档和 `.env.example` 约定演示端口是 `8098`；正式启动依赖 `MCP_PORT=8098` 环境变量。
- `MCPToolAdapter` 的同步 API 通过 `asyncio.run` 包装异步 FastMCP Client；当前同步 Web 规划器由 FastAPI 同步 endpoint 驱动，外部调用在请求线程内完成。

## 前端现状

- `web/index.html` 是三栏工作台：结构化出行表单、结果主区、追问侧栏；静态资源版本为 `phase33`。
- `web/app.js` 默认提交 `/api/plan`，规划阶段进度为 8 步；追问提交 `/api/multi-agent-chat`，并持久化当前计划、追问和轻量偏好到 `localStorage`。
- 结果页以每日行程为主，支持路线/天气/酒店/预算/POI/地图等支持信息折叠查看；编辑模式支持每日 item 上移、下移、删除，并在前端重建市内路线和预算。
- 生成结果后布局从约 `320/主区/340` 调整为更窄的侧栏；在 760px 以下转为纵向堆叠，表单和多数网格改为单列。
- 当前 CSS 采用浅色、蓝青绿多色调、半透明面板和渐变背景；`index_v2.html`、`styles_v2.css` 是未接入当前入口的另一版静态资产。

## 异步与遗留代码

- `async/` 保留了独立的异步 ReAct Agent、异步 FastMCP Server、异步 MCP 适配器和模拟用户 API，入口参数默认使用 `8084/8087` 等旧端口，不是当前 TravelMind Web 入口的一部分。
- `sync/agent_chatbot_LCEL.py`、`sync/agent_chatbot_systemmessage.py` 和 `sync/user_api.py` 更像早期示例/实验入口；当前用户端由 `sync.travel_web_app:app` 服务。
- 维护时需区分"当前产品主链路"和这些历史示例，避免把旧入口的行为误认为线上工作台契约。

## 测试覆盖初读

- `tests/test_travelmind_regression.py` 主要是结构化规划器的单元/回归契约：酒店匹配、返程住宿隔离、片区聚类、偏好影响、DeepSeek 候选 ID 校验、活动成本来源、预算来源、前端关键字符串和静态图 marker 标签。
- 当前测试使用 `FakeToolbox`、Fake DeepSeek brain 等替身，重点覆盖纯函数/组装逻辑，不等价于真实高德、MCP、DeepSeek 或浏览器端到端验证。

## GitHub 同类项目调研（检索时间：2026-07-31）

检索来源为 GitHub Repository Search、仓库 README 和公开目录树。深度对比候选及结论（详细矩阵见 [open-source-comparison.md](open-source-comparison.md)）：

- `bcefghj/multi-agent-travel-planner`：259 stars；6 Agent，Pipeline + 并行搜索 + 最多 3 轮预算循环；和当前项目的多 Agent 叙事最接近，但默认 Mock 数据，真实事实闭环较弱。
- `datarootsio/langgraph-template-travel-planner`：18 stars；LangGraph 模板，包含路由、条件边、HITL 中断、Langfuse 观测和 Reflex UI；适合作为工程骨架。
- `kbhujbal/Multi-Agent-AI-Travel-Advisor`：55 stars；CrewAI + LangChain，4 类纯 HTTP 数据服务并行，3 个 AI Agent，ChromaDB RAG；最大亮点是"数据获取与 AI 分析分离"。
- `nishant-sharma-99/PlanetPath-AI-Travel-Planner`：4 stars；FastAPI + LangGraph Supervisor + PostgreSQL，接 AviationStack、Tavily 和 Nominatim。
- `hardikverma22/travel-planner-ai`：256 stars；Next.js 14 + Convex + Clerk + OpenAI，强调四步规划、可行性检查、协作邀请和费用追踪；产品闭环强，多 Agent 细节较少。
- `LeeFly-cn/TripStar-Java`：51 stars；Spring Boot + Spring AI Alibaba StateGraph，接高德和小红书，产品与数据链路最完整，但技术栈重且为 GPL-2.0。
- `Y-66/Traveler` 与 `BjornMelin/tripsage-ai`：分别贡献 MCP/Skills/Memory 分层与 schema-first、持久化、E2E 质量门禁思路。

## 当前"智能感"不足的代码级原因

- `web/app.js` 的结构化表单只发送固定字段和少量 `preferenceProfile`；`buildTripPrompt()` 生成的自然语言仅写入追问展示，`/api/plan` 没有接收自由文本约束字段（Phase 1 已修复）。
- 结构化规划器的 DeepSeek 主要负责候选集合内的行程初排、酒店价格常识、相邻路线评审和一次体检返工；它没有全局候选评分、时间窗约束或真正的多轮预算回规划。
- 预算在最终行程、路线段和酒店候选形成后统一计算，超预算提供建议，但不会根据建议重新搜索或重新组合。
- 每个相邻真实地点段都可能触发一次路线体验判断；随着天数和地点数量增加，DeepSeek 调用数和延迟随之增长，而最终页面只显示压缩后的 trace。
- MCP 结果主要以文本返回，再由规划器用正则解析为 POI/酒店结构；结构化字段、来源时间、置信度、开放时间、室内/室外等规划所需事实不足。
- 规则兜底有片区聚类、去重和路线距离判断，但缺少全局路径排序器、天气驱动的活动替换、营业时间/预约约束和硬性需求验证。
- 右侧追问走旧 `/api/multi-agent-chat` 文本链路，结果不会直接形成新的结构化计划；长期偏好目前主要是浏览器端有限的 `localStorage` 标签。
- 当前测试重点验证数据清洗和回归不变量，没有覆盖"智能程度"的离线评测集（Phase 0 已建立）。

## Phase 0 基线发现

- 规划器可以在不改业务代码的情况下替换 `toolbox` 和 `deepseek_brain`，适合建立离线评测而不引入网络和 Key 依赖。
- 10 个固定场景的平均真实地点绑定率为 `0.5940`，说明当前行程中仍有较大比例项目未同时具备真实地点标记和有效坐标。
- 平均硬约束满足率为 `0.6000`。低预算、多人预算、紧换乘容忍度和自由文本约束场景均能复现计划中的问题。
- 平均路线超容忍率为 `0.0750`，紧换乘场景达到 `0.7500`；当前局部路线事实存在，但还没有全局反馈调整。
- 平均预算偏差为 `0.6217`。多人预算和低预算场景仍输出超预算结果，验证了"预算只报告、不重新规划"的判断。
- 返程住宿串台率为 `0.0000`，现有返程归一化护栏在该离线场景中有效；后续改造必须保持该不变量。
- 依赖降级场景 fallback 率为 `0.8333`，且 4 次 fixture 工具故障可被调用记录和输出 trace 观测到。
- 自由文本场景的原始要求没有进入 `preferences`，Phase 1 先修请求契约和偏好状态，不应先从提示词调参开始。
- 当前基线报告只用于版本间比较，尚未为发布设置阈值；阈值需要在 Phase 1-3 处理后重新讨论。

## Phase 1 约束链路发现

- `PlanRequest` 已新增可选 `freeText`、`hardConstraints`、`softPreferences`，旧请求不提供这些字段时仍使用空字符串/空数组默认值。
- 前端 `buildPlanPayload` 将补充要求传入 `/api/plan`，`buildTripPrompt` 和结构化规划请求同时呈现自由文本、硬约束和软偏好；页面新增"补充要求"输入。
- `_normalize_preferences` 保留 `freeText` 原文，并将显式/推断内容归一化为 `constraintSummary`，分组为 `hard`、`soft`、`unknown`，每项带 `id`、`kind`、`text`、`source`。
- 规划脑 payload、规则行程路径和质量评审读取同一份摘要；`quality_review.constraints` 为每项输出 `satisfied`、`violated`、`unknown` 和 `evidence`，前端和 Markdown 均可展示。
- 新增 5 个 Phase 1 契约测试；10 场景离线评测的平均硬约束满足率为 `0.7500`，自由文本硬约束场景的传递和行为检查为 `1.0000`。
- Phase 1 没有改变候选事实结构、排序、预算反馈或旧追问链路；这些缺口仍分别属于 Phase 2-4。
- 返程住宿隔离、真实地点来源标记、降级可观测和旧 API 兼容是后续改动必须保持的不变量。

## Phase 2 初步发现与当前结论

- 当前同步 MCP Server 的 `get_weather`、`amap_plan_routes`、`search_poi` 和 `search_hotels` 都返回文本；`MCPToolbox.call` 还会统一将适配器结果转换为字符串。
- `structured_planner.py` 已有 `_parse_numbered_section`、坐标/地址/评分/价格解析和 `_dedupe_pois`，但这些字段没有统一的 Contract、来源元数据或可解释排序结果。
- POI/酒店文本已经能提供名称、地址、坐标、评分、价格和图片的部分字段；本地 fallback 可能只有区域/说明文本，必须标记为缺失事实或建议，不能按真实地点处理。
- 路线和天气当前主要消费摘要文本；先建立 `RouteFact`/`WeatherFact` 形状和来源状态，不直接修改高德供应商协议。
- 离线 fixture 与现有回归测试都以旧文本契约为基础，因此 Phase 2 的第一批改动限定为纯逻辑 Contract、事实归一化和排序测试，主规划器接入放在测试通过之后。
- `contracts.py`、`fact_normalizer.py` 和 `candidate_ranker.py` 已完成第一版；`structured_planner.py` 通过可选 `candidate_contracts` 使用筛选后的 POI/酒店候选，旧列表不重排、不删除。
- 真实地点候选要求名称、有效坐标和真实地点标识才能进入规划脑；来源元数据、评分、距离、偏好匹配、天气适配和过滤原因会保留在候选的 `selection`/`validation` 字段。
- Phase 2 评测与 Phase 1 对比：绑定率 `0.5940` 不变，重复率 `0.0000` 不变，硬约束满足率 `0.7500` 不变，路线超容忍率从 `0.0750` 降至 `0.0500`，预算偏差从 `0.6217` 降至 `0.6191`，返程住宿串台率保持 `0.0000`，fallback 率从 `0.0833` 升至 `0.1000`。
- 紧换乘场景的候选排序会把可用真实地点送入规划脑，但远距离 fixture 仍触发规则路线切换；这验证了候选排序不能替代 Phase 3 的全局路线质量门。
- 当前需继续验证混合来源和严格坐标过滤的 fallback 行为；在此证据完成前，不切换 MCP 供应商返回协议，也不放宽真实地点/坐标护栏。

## 续接摘要（下一次继续入口）

### 最近决定与当前状态

- 首轮优化顺序已经确定为：离线基线 -> 约束进入结构化规划 -> 候选 JSON Contract/排序 -> 预算反馈与全局质量门 -> 结构化追问版本 -> 持久化与真实任务事件。
- Phase 0 已建立 10 个固定场景、141 次 fixture 调用、4 次工具 fixture 故障和 7 类指标（基线见上）。
- Phase 1 已完成：请求模型和前端 payload 传递自由文本/硬约束/软偏好；归一化生成 `constraintSummary`；规划脑、规则路径和质量评审共用摘要；`quality_review.constraints` 提供状态和证据；前端展示逐条约束检查。
- Phase 2 当前小步已完成 Contract/归一化/排序基础并接入 DeepSeek 候选输入；新增可选 `candidate_contracts`，旧 POI/酒店字段和文本 MCP 协议保持不变。
- 当前评测仍暴露未解决问题：平均硬约束满足率 `0.7500`，低预算/多人预算没有反馈重规划，紧换乘场景仍需要全局路线门槛；Phase 2 的候选排序已接入但 fallback 率略有上升。
- 已验证：Phase 1 专项测试 `5/5`、Phase 2 专项/集成测试 `7/7`、Phase 0 评测 `3/3`、报告渲染回归 `1/1`、业务回归 `22/22`，合计 `38/38`；Python 全量编译、`node --check web/app.js`、`git diff --check` 通过。

### 下一次继续步骤

1. 先读取本文件、`docs/implementation-plan.md` 的 Phase 2、`docs/project-baseline.md` 和 Phase 2 报告摘要。
2. 补充高德成功、Key 缺失、本地 fallback 和混合来源的 Contract/排序测试，特别记录严格坐标过滤导致的降级。
3. 根据指标决定保留严格过滤、增加可解释的 partial 候选层，或继续冻结 MCP 供应商协议；不凭感觉放宽真实地点护栏。
4. 重新运行 Phase 0/1/2 评测、业务回归、Python/Node/diff 检查，再决定是否完成 Phase 2。

### 建议排除出日常上下文的材料

以下材料继续保留在仓库，定位问题时再读取，不作为每次决策的默认输入：

- GitHub 各仓库的逐目录原始调研细节；日常以 `docs/open-source-comparison.md` 的结论矩阵和已确认机制为准。
- `tests/evals/baseline_report.json`、`phase1_report.json`、`phase2_report.json` 的完整逐场景明细；日常使用对应 Markdown 聚合报告，出现指标回归时再读取 JSON。
- `async/`、早期单 Agent 示例、`web/index_v2.html`、`web/styles_v2.css`；它们是遗留或未接入当前入口的材料，除非当前 Phase 明确触及。
- `docs/archive/` 下的历史文档（早期交接与产品化分析）；如与源码、现有测试或本摘要冲突，以源码和最近验证结果为准。
