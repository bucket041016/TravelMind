# TravelMind 勘察发现与阶段发现

> 合并自根目录 `findings.md`（发现记录）与 `CONTINUATION_SUMMARY.md`（续接摘要），2026-08-04 去重整理；代码根目录为 `my-langgraph-agent-main/`。
> 规则类约束见 `CONTRIBUTING.md` 与 `DEVLOG.md` 维护规则，阶段结果与看板见 [implementation-plan.md](implementation-plan.md)，本文件只保留发现性结论和续接入口。

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
- 当前产品 Web 与同步 MCP Server 默认端口已统一为 `8098`，路径为 `/my-custom-path`；`8083` 只残留在遗留 LCEL Agent 和适配器命令行示例，运行时仍建议显式设置 `MCP_SERVER_URL` 避免环境漂移。
- `MCPToolAdapter` 的同步 API 通过 `asyncio.run` 包装异步 FastMCP Client；当前同步 Web 规划器由 FastAPI 同步 endpoint 驱动，外部调用在请求线程内完成。

## 前端现状

- `web/index.html` 是三栏工作台：结构化出行表单、结果主区、追问侧栏；静态资源通过版本参数管理缓存（页面统一为 `phase50`）。
- `web/app.js` 默认提交 `/api/plan`，规划阶段进度为 8 步（当前为前端定时器模拟，真实任务事件待 Phase 5）；追问提交 `/api/multi-agent-chat`，并持久化当前计划、追问和轻量偏好到 `localStorage`。
- 结果页以每日行程为主，支持路线/天气/酒店/预算/POI/地图等支持信息折叠查看；编辑模式支持每日 item 上移、下移、删除，并在前端重建市内路线和预算。
- 生成结果后布局从约 `320/主区/340` 调整为更窄的侧栏；在 760px 以下转为纵向堆叠，表单和多数网格改为单列。
- 当前 CSS 采用浅色、蓝青绿多色调、半透明面板和渐变背景；v2 页面已替代 v1 成为唯一入口（`web/index.html` + `web/styles.css`），`/v2` 路由保留为重定向，且表单已包含"补充要求"（freeText）输入。

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
- `contracts.py`、`fact_normalizer.py` 和 `candidate_ranker.py` 已完成第一版；DeepSeek 候选输入优先使用筛选后的 POI/酒店候选，旧列表不重排、不删除；`candidate_contracts` 的构建（`_build_candidate_contracts`）与消费端（`itinerary_builder`）已就绪，但 `run()` 尚未调用构建函数，生产响应里实际不产生该字段（2026-08-14 核对，见工程债务 D2）。
- 真实地点候选要求名称、有效坐标和真实地点标识才能进入规划脑；来源元数据、评分、距离、偏好匹配、天气适配和过滤原因会保留在候选的 `selection`/`validation` 字段。
- Phase 2 评测与 Phase 1 对比：绑定率 `0.5940` 不变，重复率 `0.0000` 不变，硬约束满足率 `0.7500` 不变，路线超容忍率从 `0.0750` 降至 `0.0500`，预算偏差从 `0.6217` 降至 `0.6191`，返程住宿串台率保持 `0.0000`，fallback 率从 `0.0833` 升至 `0.1000`。
- 紧换乘场景的候选排序会把可用真实地点送入规划脑，但远距离 fixture 仍触发规则路线切换；这验证了候选排序不能替代 Phase 3 的全局路线质量门。
- 当前需继续验证混合来源和严格坐标过滤的 fallback 行为；在此证据完成前，不切换 MCP 供应商返回协议，也不放宽真实地点/坐标护栏。

## 工具增强规划脑预验证发现（2026-08-14）

两轮受控实验验证"DeepSeek 自主调 MCP 工具补查事实"是否可行（脚本在 `output/verify_agentic_plan*.py`，未改业务代码）：

- 第一轮（本地假工具 + 真实 DeepSeek）：2 次 LLM 调用完成并行查 3 工具 + 输出 JSON，地点零编造；但 prompt 只列 3 个字段时模型只输出 3 个字段——**字段漂移实证**，前端 schema 必须显式全字段 + 强校验。
- 第二轮（真实 MCP + 真实高德 + 真实 DeepSeek）：6 次调用/27.6s，出现自主补查 `search_hotels(near=福田)` 的**真实 agentic 行为**；12 个 item 地点零编造；但 MCP 文本没有稳定 id，模型**自行编造 candidate_id**（`poi_shenzhen_museum`、`el_yunzhongtian` 等）。
- 附带发现：`search_poi` 因 description 未写明"一次返回全部类别"被重复调用两次（约 9KB 重复内容进上下文）；模型输出带英文前言和 ```json fence（现有 `_parse_json_object` 可兜底）。

结论与铁律：agentic 补查可行且有真实价值，但必须"**后端回填 id + 强 schema 校验 + 只读白名单**"为前提——模型永不生成 id，只能引用后端 `normalize_place_candidates` 给出的 id；补查候选回传后端重新 normalize。据此新增 Phase 2.5（工具增强规划脑），并把 Phase 2.2 升级为"稳定 id 事实层"。

## DeepSeek 输出结构化校验（2026-08-17）

- 新增 `sync/multi_agent/deepseek_contracts.py`：用 Pydantic v2 为 DeepSeek 四类输出建立契约（`PlanOutput` / `HotelPriceOutput` / `RouteJudgement` / `ReviewOutput` 及其嵌套模型），`extra="ignore"`；枚举类字段（`category`/`decision`/`price_confidence` 等）保持 `str` 交由下游 normalizer 统一兜底，避免在边界过度拒绝导致 fallback 率上升。
- `deepseek_brain.py` 四个方法统一走新增的 `_invoke_parsed`：`model_validate_json` 校验 + 类型归一化 + 校验失败回喂错误重试（最多 2 次），替代原 `_parse_json_object` 只做 `json.loads` 的单次解析。
- 类型强转顺带修复了一个潜在 bug：原下游 `bool(raw_item.get("is_suggestion"))` 会把字符串 `"false"` 误判为 `True`；现在边界已把 `"false"` 归一到 `False`。
- `repaired_plan` 改为可选（`PlanOutput | None`），避免 `needs_repair=false` 且缺 `repaired_plan` 时整份 review 被误判校验失败。
- 验证：新增 `tests/test_deepseek_contracts.py` 9 个用例（围栏清理、前言后记剥离、类型强转、缺失字段拒绝、回喂重试与重试耗尽），全量回归 70/70、离线评测 4/4、py_compile 与 `git diff --check` 通过。
- 未做：`response_format={"type":"json_object"}`（计划 2.8）仍待接入，需真实 DeepSeek API 验证；当前围栏清理仍保留作为兜底。

## 后端稳定 id 回填（2026-08-17）

- 新增 `contracts.stable_place_id()`：以「名字+坐标」生成确定性 id（坐标是地点的全局唯一身份），模型只引用、永不生成，后端可用名字/坐标回溯重算完成回填匹配。
- `text_parser._parse_numbered_section` 弃用 `_make_item_id(heading, index, name)` 的位置序号 id（序号随列表顺序变化、不可回溯），改为 `stable_place_id(name, location)`。
- `normalize_place_candidate` 统一附加 `stable_id` 并在 id 缺失时回填；显式传入的 id（fixture / 未来结构化 MCP）仍保留，保持旧接口兼容。
- 过程中发现并修复一个前置顺序问题：`_build_hotels` 在 normalize 之前就用 `item.get("id")` 请求 AI 估价，若 id 推迟到 normalize 才生成会导致估价请求落空；最终把稳定 id 生成前置到 `_parse_numbered_section`，保证 id 全程可用。
- 验证：新增 `tests/test_stable_id.py` 6 个用例（确定性、坐标区分、无坐标兜底、normalize 回填/保留、编号段解析），全量回归 76/76、离线评测 4/4、py_compile 与 `git diff --check` 通过。

## 旧 /api/multi-agent-chat 链路冒烟测试（2026-08-17）

- 为工程债务 D4 的第一步补冒烟测试：新增 `tests/test_multi_agent_chat_smoke.py` 4 个用例，用离线 Fake 工具箱覆盖 `PreferenceAgent` 正则解析与 `MultiAgentTravelPlanner.run()` 端到端。
- 确认旧链路事实 Agent（天气/路线/POI/预算）与 Writer 均只依赖 MCP 工具、不依赖 DeepSeek，因此可纯离线冒烟。
- 测试锁定并暴露了 preference_agent 正则的当前支持范围：「两人/2人」可解析，「两个人/两个孩子」不识别（`\s*人` 无法跨越「个」）。这属已知限制，待 D4 退役决策时一并决定是否用 LLM + Pydantic 抽取替代正则。
- 验证：全量回归 80/80、离线评测 4/4、py_compile 与 `git diff --check` 通过。

## 结构化 MCP 返回契约（2026-08-17）

- 新增 `sync/multi_agent/structured_result.py`：冻结 POI（attractions/foods/specialty_places/generic_foods）与酒店（candidates/area_recommendation/provider_status）字段命名，及 `is_structured_poi`/`is_structured_hotel`/`as_list` 判定与安全归一化。
- `poi_service._build_pois` 与 `hotel_service._build_hotels` 在收到结构化 dict 时直接消费、否则回退文本正则；正则逐步降级为兜底，不改变旧文本路径行为。
- 全链路结构化返回仍需一端：MCP Server 工具返回结构化（需真实高德）。适配器/工具箱原始透传原型已实现（`mcp_tools_adapter._coerce_structured` + `MCPToolbox.call` 去 `str()`），但旧入口兼容和 FastMCP 原生 structured content 读取尚未闭环，因此不计为完成。
- 验证：新增 `tests/test_structured_result.py` 4 个用例（判定、POI 结构化消费、POI 文本兜底、酒店结构化消费）与 `tests/test_mcp_adapter_structured.py` 6 个用例（JSON 对象/数组解析、纯文本与非对象 JSON 原样返回、工具箱透传），全量回归 90/90、离线评测 4/4、py_compile 与 `git diff --check` 通过。

## 当前改动与后续计划复核（2026-08-24）

### 本次改动直接引入的风险

- `MCPToolbox.call()` 从始终返回字符串改成透传 `dict/list`，但旧 `POIAgent` 会把 dict 写入 `TravelPlanState.poi: str`，`WriterAgent` 随后按字符串拼接；天气 Agent 使用 `"\n".join()`、路线 Agent 使用 `startswith()`、预算 Agent 使用正则。结构化结果一旦真正启用，旧入口存在明确类型回归，因此这组改动当前不满足合并条件。
- 2026-08-24 定向探针让 `search_poi` 返回结构化 dict，旧 `MultiAgentTravelPlanner` 的结果为 `answer_empty=true`、Writer trace `status=error`，错误为 `expected str instance, dict found`；这把 D12 从静态推断提升为当前代码可复现的兼容缺陷。
- `MCPToolAdapter.call_mcp_tool_async()` 仍只读取 `result.content[0].text`，没有优先读取 FastMCP 原生 `structured_content/data`；现有测试只验证 JSON 文本和手工构造 dict，没有验证真实 FastMCP 返回对象。
- 当前安装的 FastMCP 3.4.0 中，`CallToolResult` 明确定义 `content`、`structured_content`、`meta`、`data`、`is_error`；适配器应归一化这些字段，而不是只取第一个文本块。
- `is_structured_poi()` / `is_structured_hotel()` 只要命中任一字段就接受整个 dict；`as_list()` 只检查外层 list，不过滤非 dict 元素。酒店逻辑随后直接调用 `candidate.get()`，坏元素会使整个 HotelAgent 降级，合法候选也一起丢失。
- 当前 `90/90` 通过有价值，但字符串旧链路测试和结构化 happy-path 测试彼此分离，没有覆盖“结构化 MCP 开启后的旧三入口兼容”，所以不能作为 D12 完成证据。

### 未来启用结构化 MCP 后才会触发的风险

- 同步 MCP Server 当前仍返回文本，正常本地演示尚未走到上述 dict/list 路径；因此应把问题表述为“已确认的合并/启用风险”，而不是当前生产主链路已经持续报错。
- 供应商返回结构化数据后，需要同时处理 `structured_content/data`、文本 content、空结果、部分坏元素、schema 版本和文本 fallback；只解析看起来像 JSON 的首个文本块会丢失协议语义。

### 原有计划缺口

- D12 原方案只写“优先读取 structured content + Pydantic + 三入口测试”，没有冻结适配器对上层的返回形态。修订为稳定结果封装，并显式提供字符串兼容访问和结构化访问，避免所有旧 Agent 被迫同步迁移。
- 原顺序 `D11 -> D12 -> D2` 先做 DeepSeek 观测，未优先处理当前工作树已改变的公共类型边界。修订为“范围隔离 -> D12 -> D2 -> D11 -> 真实验收”；先消除已引入的跨入口风险，再产出候选 Contract，最后用准确观测完成真实对照。
- V3 固定 DOM 不能算产品行为，且继续保留会制造能力误解；2026-08-24 已按废案删除 `/v3` 路由和 `web/v3_*`。`.dsh/` 对本地实验有价值，但不属于 TravelMind 产品运行时，继续留在产品提交之外。

### 方案取舍

- 选择稳定结果封装而不是原始 `dict/list` 全局透传：优点是协议、业务模型和旧字符串链路解耦，新增工具可复用统一边界；缺点是多一层薄模型和访问方法。
- 选择 D12 先于 D11：优点是先封闭当前直接回归风险；缺点是 DeepSeek trace 改善稍后落地。D11 仍保留为 Phase 2 关闭前硬闸门。
- 产品主线在 Phase 2 后优先进入 Phase 3：优点是直接改善当前已量化的预算偏差和全局路线问题；缺点是 Phase 2.5 agentic 探索延后，但不会用更强自主性放大尚未稳定的事实与观测边界。

## D12 稳定 MCP 结果封装（2026-09-05）

- 适配器新增 `MCPToolResult`（`tool_name`/`text`/`data`/`source`/`validation_error`）与 `call_mcp_tool_result(_async)`；`call_mcp_tool(_async)` 恒返回字符串（结构化返回以 JSON 文本给出），`/api/chat` 的 LangChain 包装与旧多 Agent 链路因此字符串安全，2026-08-24 复现的 `expected str instance, dict found` 缺陷从边界上消除。
- 结构化数据只读 FastMCP 解包后的 `result.data`（dict/list 判定），不读线协议 `structured_content`：3.4.0 中非 object 返回会被 `{"result": ...}` 包裹（wrap 陷阱），`data` 即其解包值；`-> str` 工具的 `data` 是字符串，不会被误判为结构化。
- 空结果判定必须覆盖空白文本：3.4.0 中工具返回 `''` 时 `content=[TextContent('')]` 非空，仅判 `result.content` 抓不到；现统一归一化为「工具 X 返回了空结果。」（source=empty）。
- `MCPToolbox` 提供 `call_text()`/`call_structured()`，`call()` 保留为文本别名，旧 6 个 Agent 文件零改动；规划器 5 个调用点显式化：POI/酒店 `call_structured`，天气/跨城/市内 `call_text`。
- `structured_result.py` 重写为 Pydantic 响应模型层：`PlaceCandidate`（仅强制 name 非空白，`extra="allow"`）作元素校验闸门，合法元素保留原始 dict（hotel_service 原地修改 cost/match_reason 依赖此形态）；`parse_poi_response`/`parse_hotel_response` 坏元素过滤并回填 `validation_error`；删除 `is_structured_*`/`as_list`。
- 适配器构造参数接受 FastMCP 实例（`Client(server)` 内存直连，完整 JSON-RPC 往返不起 HTTP），新增 `tests/test_mcp_protocol.py` 11 用例：dict/无注解 str/`-> str` wrap 陷阱/JSON 文本兜底/空文本/工具异常/非法 schema 全形态 + 三入口回归（旧链路 dict 返回不崩溃、规划器消费结构化、LangChain 包装返回 str）。协议事实提示：升级 fastmcp 前需重跑 wrap/data 语义探针。
- 行为变化：`call` 恒返回 str；空白文本统一空结果文案；`pois/hotels["raw"]` 恒为 str；hotel `provider_status` 空值回退 provider 状态。
- 验证：全量回归 112/112（37.6s）、评测 4/4（141 次调用/4 次 fixture 失败已固化为 `test_baseline_eval` 断言）、py_compile/`node --check`/`git diff --check` 通过。MCP Server 工具仍返回文本（供应商协议未改，按计划待混合来源证据后再切换）。

## D2 candidate_contracts 生产接线（2026-09-05）

- `run()` 在片区聚类后快照候选池，产出可选、版本化 `candidate_contracts`（`version`/`contract_version`/`source_mode` + POI 三组与酒店入选项）；位置选在 `_enrich_place_clusters` 之后，契约候选携带完整 `cluster_id/cluster_name/nearby_anchor`、`selection.score/reasons` 和 `source_meta`。
- 契约对齐基线文档声明，新增 `source_mode=legacy_text_compatible`。
- 取舍决策：落选原因暂不输出。现有构建器只收入选项，落选理由在 `_normalize_and_rank_*` 内部被 rank_candidates 丢弃；如 D3 需要展示落选理由，先扩展归一化函数保留 rejected 再接线，不在 D2 混入。
- `_planning_brain_payload` 消费端确认无需改动：`pois/hotels` 内部的 `candidate_contracts` 键仍无人设置，payload 走排序后分组回退分支，与契约快照内容一致。
- 新增 run() 级离线测试 `test_run_wires_candidate_contracts_and_keeps_legacy_fields`（本地 `_FakeRunToolbox` 文本 fixture + `_UnavailableBrain` 全规则降级）：断言版本化内容、cluster 字段、`selection/source_meta` 完整性，以及旧 `pois/hotels` 字段兼容和契约与旧字段入选项数量一致。
- 验证：全量回归 113/113、评测 4/4（141/4 断言保持——构建器内部二重排序为确定性重算，不影响指标与调用次数）、py_compile/`node --check`/`git diff --check` 通过。

## D11 DeepSeek 降级观测（2026-09-05）

- `_invoke_parsed` 改为返回 `(parsed, attempt_count)`，重试预算耗尽抛 `DeepSeekInvocationError`（`error_kind`: schema=输出无法解析/校验、call=网络/鉴权/超时；附 `attempt_count`）；调用错误与输出质量错误分类统计，不再混为一个 `parse_failed`。
- 四类脑调用（plan/estimate_hotel_prices/judge_route/review_itinerary）失败状态细化为 `schema_failed`/`call_failed`，并统一携带 `error_kind`/`attempt_count`/`fallback_reason`（如 `deepseek_schema_failed`）；`unavailable`（无 Key）也带同一组元数据（attempt_count=0）。
- 关键取舍：`llm_status` 保持结果语义——成功恒为 `used`（含重试后成功），`retry_success` 只在 trace 层由 `attempt_count>1` 派生；这样四个 `!= "used"` 消费方（hotel_service/local_transport_service/quality_reviewer/itinerary_builder）零改动，不会把重试成功误判为失败。
- `_record` 对携带 `llm_status` 的业务结果把 trace 状态从普通 `success` 细化为 `used/retry_success/schema_failed/call_failed/unavailable`；规则降级行程步显式记录 `rule_fallback`（Phase 2.5 铁律 5 的五态齐备）。普通结果与 `status_hint` 语义不变。
- `ReviewOutput` 跨字段校验：`needs_repair=true` 必须携带 `repaired_plan`，缺失即触发回喂重试；行程可用项不足的物化失败改记 `schema_failed` + `fallback_reason=itinerary_insufficient_items`。
- 边界声明：酒店价格估算与路线评审的脑降级仍在组件层消化（`cost_source`、`route_judgement` 来源已可观测），trace 五态聚焦规划脑与体检两个主脑步。
- 验证：DeepSeek 契约测试 16/16（错误分类、重试计数、plan 层状态、跨字段校验）、trace 状态测试 5 个（`_record` 派生 + run() 级 `schema_failed`→`rule_fallback` 全链路断言）；全量回归 124/124、评测 4/4（141/4 断言保持）、py_compile/`node --check`/`git diff --check` 通过。真实固定 DeepSeek 场景基线归入 Phase 2 真实验收步（需真实 Key 与服务）。

## Phase 2 真实验收记录（2026-09-05）

执行环境：Windows + .venv，MCP Server `8098` + Web `8010`，真实高德 Web Key 与真实 DeepSeek Key；固定输入与原始响应存 `D:\Temp\travelmind-acceptance\`（临时目录，不入库）。共 3 次真实 `/api/plan` 规划。

### 场景 A：真实高德 + 真实 DeepSeek（固定输入）

广州→深圳，2026-09-12，2 天 1 人，预算 800，舒适档，兴趣经典景点/美食/地方特色，freeText「优先地铁附近，晚上不要安排太晚的活动」。耗时 49.1s，HTTP 200，响应 165KB。

- `llm_status=used`、`planning_mode=deepseek_hybrid`；trace 状态：success×10、used×2。
- **DeepSeek 五态真实基线：used=2（规划脑 + 体检各一次成功）、retry_success=0、schema_failed=0、call_failed=0、rule_fallback=0**——首次真实观测无格式失败，`response_format=json_object` 的收益仍待更多样本。
- 高德真实数据：景点/美食/特色各 8 个候选全部 `is_real_place=true`；酒店 6 候选（provider_status=amap_fallback）；天气来自高德（雷阵雨 25~33°C）。
- `candidate_contracts` 生产输出正确：travelmind-candidate-v1，8/8/8+6，候选带 `selection.score`（样例 62.2）、入选理由、`source_meta`、cluster 标注。
- `quality_review` overall 72，5 issues，无返工；行程 2 天 9 items，7 项 real+map。

### 场景 B：高德 Key 缺失降级（同一固定输入）

MCP Server 以空 `AMAP_*` 环境变量重启（空值优先于 .env）。耗时 27.5s，响应 165KB→66KB。

- 天气降级 wttr.in（英文摘要）；POI 降级本地知识库（5 景点 + 7 美食），全部 `is_real_place=false`/`is_suggestion=true`/无坐标——**真实地点护栏在降级态守住**：`candidate_contracts` 景点/美食输出 0，不放行不可定位项。
- 酒店 `provider_status=not_configured`，3 个名称带「（示例）」的区域候选进入 contracts（观察项 3）。
- DeepSeek 仍真实 `used`×2；`quality_review` overall 65（较健康态 72 下降，合理）。trace 无 error——降级发生在供应商层，通过 `provider_status`/`source_meta` 表达而非 trace 错误。

### 场景 C：浏览器主流程（桌面）

默认表单（广州→深圳，2026-09-06）点击 Plan My Trip，真实规划一次。结果页完整渲染：「DEEPSEEK 智能规划 + 高德事实校验」标识、路线对比（高铁/自驾真实数据）、真实 POI 照片与评分、跨天真实交通接驳（步行 21 分钟 1.6km、高德票价参考）、「DeepSeek 已从高德候选中绑定真实地点」标记、返程住宿隔离说明、精选推荐带「高德参考」来源标签、预算 ¥662 预算内。**浏览器控制台 0 错误**。截图：`D:\Temp\travelmind-acceptance\browser_main_flow.png`。

### 未覆盖与观察项

- 移动端视口未测（遗留项：Phase 5 Playwright 或单独一轮移动视口检查）；高德限流路径未主动触发（CUQPS 退避已有离线覆盖）。
- 观察项 1：降级态本地 POI 的 `source` 标签仍为 `amap_poi`（normalize 默认值），建议记为小债务改为 `knowledge_base`。
- 观察项 2：真实 DeepSeek 体检路径下 `quality_review.constraints=0`（约束逐项评审只在规则体检路径产出）——与 Phase 1 规则路径行为不一致，建议随 Phase 3/追问改造统一。
- 观察项 3：本地 fallback 酒店「示例」区域候选进入 contracts——名称显式标注示例、非编造真实酒店，可接受；如需更严可在构建器过滤 `not_configured` 酒店。

## Phase 3 预算反馈循环（2026-09-05）

- 新增 `budget_optimizer.py`：确定性反馈循环（零 LLM/工具调用），超预算时按优先级执行三杠杆——同片区高价项替换（activity+food，候选经 `_cost_metadata` 同口径预测重建成本，**免费候选可替换付费项**）、住宿 `budget_strategy=cheapest_first`（与 `_average_cost_by_source` 同一 source 优先级框架内取 min，不按 selection.status 过滤）、非硬性付费活动删减（`_retime_day_items` 重排时间槽）。每动作记录 before/after/saved/reason；轮上限 2；deepcopy 快照异常回滚。
- 插入位置：评审后、市内路线重建前。临时预算用 movement_count 口径（实测比最终口径高估 5-15 倍），循环决策只消费「每轮节省量 vs 剩余缺口」相对量；金额统一标注"调整期估算"；最终 budget 仍由 BudgetAgent 按真实 segments 计算。
- 硬质量门 `quality_gate.py`：返程后住宿串台、item 总量下限、硬约束预算↔最终 verdict、单日时长粗检。违规写独立字段 `quality_review.gate_violations`——不动 issues（前端 slice(0,3) 截断 + phase1 契约）、不改 source（metrics fallback 语义）。
- 用户决策：循环默认开启（`TRAVELMIND_BUDGET_LOOP=on`，off 为回滚开关）；评测 141 调用断言重定为实测 139（删项减少 2 次 judge_route 对），指标重定基线并生成 phase3_report 对照。
- 评测对照（Phase 2 → Phase 3）：预算偏差 **0.6230 → 0.4897**；low_budget ~1.9 → 0.854（跨城+最低酒店已超 500 目标，无法完全达标——验收口径为"真实调整+缺口可解释+偏差下降"）；return_transfer_isolation 2107→1601 转预算内、串台率保持 0；fallback 率与污染率不变；真实地点绑定率 0.5940→0.5903（微调）；硬约束满足率 0.7500 不变。
- 前端与导出：预算卡「预算自动调整」折叠块（动作/缺口/口径）、体检「硬门槛提醒」区块、导出 Markdown 与后端 markdown_writer 同步调整段；新字段经快照整包克隆自动持久化。
- 验证：新增 21 个测试（优化器 10、门禁 6、run() 级 4、eval 对照 1）；全量回归 145/145、评测 5/5（139/4 固化）、py_compile/`node --check`/`git diff --check` 通过。

## 续接摘要（下一次继续入口）

### 最近决定与当前状态

- 产品主线顺序已经修订为：离线基线 -> 约束进入结构化规划 -> 候选 JSON Contract/排序（稳定 id 事实层）-> 预算反馈与全局质量门 -> 结构化追问版本 -> 持久化与真实任务事件。工具增强规划脑是可选 Phase 2.5 支线，不再阻塞 Phase 3。
- Phase 0 已建立 10 个固定场景、141 次 fixture 调用、4 次工具 fixture 故障和 7 类指标（基线见上）。
- Phase 1 已完成：请求模型和前端 payload 传递自由文本/硬约束/软偏好；归一化生成 `constraintSummary`；规划脑、规则路径和质量评审共用摘要；`quality_review.constraints` 提供状态和证据；前端展示逐条约束检查。
- Phase 2 已完成 Contract/归一化/排序基础并接入 DeepSeek 候选输入；已提交基线保持旧 POI/酒店和文本 MCP 协议。2026-09-05 D12 已完成并提交（`dfb5a5b`）：稳定结果封装、`call_text`/`call_structured` 双访问、Pydantic 坏元素过滤、内存协议级测试与三入口兼容；同日 D2 完成并提交（`029ef20`）：`run()` 接线可选版本化 `candidate_contracts`（落选原因延后至 D3）；同日 D11 代码完成并提交（`05def10`）：DeepSeek 错误分类、attempt_count、fallback_reason 与 trace 五态（真实固定场景基线随真实验收步执行）。Phase 2 剩余闸门：高德成功/限流/Key 缺失/混合来源测试与真实服务对照、浏览器主流程验收。
- 2026-08 收尾修复已推送到 main：v2 替代 v1 成为唯一前端入口、MCP 默认端口统一 8098、样式文件更名 styles.css；全量回归 61/61、评测 4/4 通过。
- 当前评测仍暴露未解决问题：平均硬约束满足率 `0.7500`，低预算/多人预算没有反馈重规划，紧换乘场景仍需要全局路线门槛；预算偏差 `0.6230`（超预算酒店如实呈现，等待 Phase 3 替换/降级）。
- Phase 2.5 已写入执行计划（`docs/implementation-plan.md`），前置条件包括 Phase 2.2 稳定 id/D12 协议边界、D11 准确观测和 D1 MCPToolAdapter 连接复用。

### 下一次继续步骤

1. 先读取本文件、[target-architecture.md](target-architecture.md)、`docs/implementation-plan.md` 的 Phase 2/2.5 与看板、`docs/project-baseline.md`。
2. 先隔离结构化 MCP、`.dsh/` 和文档范围，完成 D12 的稳定结果封装、双访问方式、严格响应校验、真实 FastMCP 协议测试和三入口兼容；V3 已关闭，不再进入后续工作。
3. [已完成 2026-09-05] D2，在 `/api/plan` 接线可选、版本化 `candidate_contracts`，并补旧字段兼容断言（提交 `029ef20`）。
4. [代码已完成 2026-09-05] D11，错误分类和准确降级 trace 已落地（提交 `05def10`）；固定真实 DeepSeek 场景基线随真实验收步执行。
5. 重跑全量回归、离线评测、Python/Node/diff、真实服务对照和主页面浏览器验收；关闭 Phase 2 后产品主线进入 Phase 3，Phase 2.5 保持可选实验支线。

### 建议排除出日常上下文的材料

以下材料继续保留在仓库，定位问题时再读取，不作为每次决策的默认输入：

- GitHub 各仓库的逐目录原始调研细节；日常以 `docs/open-source-comparison.md` 的结论矩阵和已确认机制为准。
- `tests/evals/baseline_report.json`、`phase1_report.json`、`phase2_report.json` 的完整逐场景明细；日常使用对应 Markdown 聚合报告，出现指标回归时再读取 JSON。
- `async/` 和早期单 Agent 示例（`sync/agent_chatbot_*.py`、`sync/user_api.py`）；它们是遗留实验材料，除非当前 Phase 明确触及。
- `docs/archive/` 下的历史文档（早期交接与产品化分析）；如与源码、现有测试或本摘要冲突，以源码和最近验证结果为准。
