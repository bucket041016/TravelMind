# TravelMind 交接文档

更新时间：2026-07-14  
项目目录：`D:\Codexwork\my-langgraph-agent-main`  
当前任务：准备重新设计 TravelMind 用户端页面。用户明确反馈“现在这个太丑了”，希望重新设计一个更好看的用户端页面。

## 我们在做什么

我们正在把原来的 LangGraph/MCP 聊天 Demo 打磨成一个可展示、可信、可回归的旅行规划产品：TravelMind。

当前产品链路是：

- 用户在左侧表单输入出发地、目的地、日期、天数、人数、预算、兴趣、交通、住宿和偏好画像。
- 后端查询高德事实数据：跨城路线、天气、POI、酒店、目的地内路线。
- DeepSeek 负责规划脑、路线体验评审、行程自检返工和常识价格区间判断。
- 后端负责校验 DeepSeek 输出、补路线段、补地图、算预算、降级兜底。
- 前端展示结构化结果页、每日行程、路线、住宿、地图、预算、智能体检和右侧追问。

最新新任务还没有开始实现：重新设计用户端 UI/UX，让页面更像成熟旅行产品，而不是现在这种偏 Demo 的工作台。

## 当前运行状态

只使用 TravelMind 两个端口：

- Web App：`http://127.0.0.1:8010`
- MCP Server：`http://127.0.0.1:8098/my-custom-path`

当前快照：

- `8010` listen PID：`9612`
- `8098` listen PID：`48476`

PID 只能作为当前快照。下一会话必须重新检查端口和命令行，确认进程属于 `D:\Codexwork\my-langgraph-agent-main` 后再处理。

启动 Web 时必须带：

```powershell
$env:MCP_SERVER_URL='http://127.0.0.1:8098/my-custom-path'
.\.venv\Scripts\python.exe -m uvicorn sync.travel_web_app:app --host 127.0.0.1 --port 8010
```

## 已完成了什么

### 结构化规划与展示

- `/api/plan` 已返回结构化 JSON，并保留 `markdown`、`trace` 等兼容字段。
- 主页面有结构化结果页和“方案原文”标签。
- 右侧只保留追问对话，不恢复旧系统面板。
- 旧 localStorage 快照有前端归一化和降级文案。
- 静态资源版本当前为 `phase33`。

### 高德 + DeepSeek 混合规划

- 高德负责事实数据：天气、跨城路线、POI、酒店候选、目的地内路线。
- DeepSeek 负责：
  - 生成初版每日行程。
  - 判断路线是否太折腾。
  - 行程自检：区域一致性、交通痛苦度、返程逻辑、住宿逻辑、疲劳度、预算可信度。
  - 提供 AI 参考数据/线索，例如酒店和活动价格常识区间、区域建议、体验判断；但必须标注非实时、需核实，并提醒用户以官方/现场/平台实际为准。
- DeepSeek 不可用或输出非法时，后端有规则降级。

### 目的地内交通与路线评审

- `local_transport.segments` 已按最终每日行程中相邻真实地点生成。
- segment 包含模式、耗时、距离、价格、来源、状态、warning、DeepSeek judge 字段等。
- 前端每日 item 已展示“上一站到本站”路线摘要。
- 目的地内交通只展示在每日行程里，没有和跨城交通混在一起。
- DeepSeek 路线评审可判断：
  - `accept`
  - `switch_mode`
  - `replace_place`
  - `mark_impractical`
- 超长公交不会再作为 `success + transit` 普通展示。
- 打车价格只做距离规则估算，不伪装成实时价格。

### 价格和预算

- 景点/活动无高德 cost、无 AI 正价时默认 `0`，来源为 `free_or_no_ticket_default`。
- 活动 0 元文案是“无门票/免费默认，需核实”，不是官方免费声明。
- 高德有 cost 时保留 `amap_cost`。
- DeepSeek 明确给正价区间时使用 `ai_price_range`。
- 餐饮、酒店等非活动类缺价仍可用规则估算，不受活动默认 0 影响。
- 预算在每日活动、路线评审和市内路线段之后计算。
- 前端进度条已修正为：
  `安排每日活动 -> 智能体检与路线评审 -> 估算旅行预算`

### 酒店与返程逻辑

- 酒店卡展示价格来源、可信度、非实时说明和“近哪里”的匹配理由。
- 已避免“匹配深圳核心商圈/地铁枢纽/第一天重点景点附近”这种泛化写法，尽量写具体地标。
- 已修复“回家了还要住”：返程 transfer 不再带目的地住宿建议。

### 区域聚类、偏好画像和智能体检

- 后端已为景点、餐饮、酒店生成 `cluster_id`、`cluster_name`、`nearby_anchor`。
- 每日行程有 `primary_cluster`。
- 规则降级路径也会优先同片区选 POI。
- 前端表单新增：
  - 旅行节奏：轻松 / 标准 / 紧凑
  - 单段交通容忍：30 / 45 / 60 分钟
  - 住宿策略：近景点 / 近地铁枢纽 / 近商圈
- 追问和手动编辑会沉淀轻量偏好到 localStorage，例如：
  - 少公交
  - 别太赶
  - 不去太远景点
  - 少走路
  - 少换乘
- `/api/plan` 请求新增 `preferenceProfile`。
- `/api/plan` 响应新增 `quality_review`。
- 前端“行程概览”下新增“智能体检”摘要。
- 旧快照缺少 `quality_review` 时显示重新规划提示，不崩。

## 最近验证结果

完整回归曾通过：

```powershell
.\.venv\Scripts\python.exe -m py_compile .\sync\fastmcp_server_streamhttp.py .\sync\multi_agent\structured_planner.py .\sync\travel_web_app.py .\sync\mcp_tools_adapter.py
node --check .\web\app.js
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

结果：

- 后端核心文件 py_compile 通过。
- `node --check web/app.js` 通过。
- 单测 `22` 个通过。

广州到深圳 2 天游接口回归结果：

- `planning_mode=deepseek_hybrid`
- `llm_status=used`
- 轻松偏好下：`day1=4; day2=3`
- 超长 success 公交：`0`
- 返程住宿串台：`0`

进度条顺序修复后又单独验证：

- `node --check web/app.js` 通过。
- 首页返回 `phase33`。
- 浏览器确认加载 `app.js?v=phase33`。
- 控制台无 error。

## 当前卡在哪

当前没有技术阻塞。新需求刚出现，尚未开始实现：

> 重新设计用户端页面，因为当前页面太丑。

还没有做：

- 设计审计。
- 新页面信息架构。
- 新视觉方案。
- 前端 CSS/布局改造。
- 桌面和移动端截图验证。

下一会话不要直接乱改样式。应先看现状页面和现有 DOM/CSS，再给出明确的 redesign 方案，然后实现。

## 下一步计划

1. 读取当前前端结构：
   - `web/index.html`
   - `web/app.js`
   - `web/styles.css`

2. 用浏览器打开 `http://127.0.0.1:8010/` 做视觉审计：
   - 首屏表单是否拥挤。
   - 结果页信息层级是否混乱。
   - 每日行程、智能体检、路线、预算、住宿、地图是否抢焦点。
   - 移动端是否重叠或太长。

3. 设计用户端新方向：
   - 保留现有业务功能和 API。
   - 不重构后端规划链路。
   - 不恢复右侧旧系统面板。
   - 做成更成熟的旅行规划产品界面，而不是多 Agent 技术 Demo。

4. 实现建议：
   - 左侧表单变得更轻、更分组、更少噪音。
   - 主结果区突出“每日行程”和“路线体验”，不是堆卡片。
   - “智能体检”做成轻量摘要，不要压过行程主体。
   - 酒店、预算、地图作为支持信息，层级弱于每日安排。
   - 保证桌面和移动端都不重叠、不溢出。

5. 验证：
   - `node --check web/app.js`
   - 如果触碰业务逻辑，再跑 `python -m unittest discover -s tests -v`
   - 浏览器验证桌面宽屏。
   - 浏览器验证移动端。
   - 截图确认 UI 不是空白、无重叠、文字不挤。

## 绝对不要再踩的坑

### 不要打印 `.env`

`.env` 有 DeepSeek 和高德 Key。不要 `type .env`，不要把 Key 写进回复或文档。

### 不要碰无关端口

只处理 TravelMind：

- `8010`
- `8098`

不要误杀其它项目端口。处理进程前必须确认监听端口和命令行都属于当前项目。

### Web 启动必须带 MCP_SERVER_URL

否则 Web 会连错 MCP 地址，导致工具调用失败。

### 不要把泛化文本当真实地点

不能把这些当真实 POI：

- `深圳`
- `地方特色餐食`
- `特色晚餐与夜间散步`
- `潮汕牛肉火锅`
- `核心商圈`
- `地铁枢纽`

真实地点必须来自高德 POI、酒店 POI、交通枢纽，或明确标成说明项/待确认建议。

### 不要恢复右侧旧空面板

用户明确不要右侧系统面板。右侧只保留追问对话。

### 高德静态图 marker label 不要传多字符

第 10 个点不能传 `10`。高德静态图 marker label 必须保持单字符。

### PowerShell 不要用 `$PID` 当变量名

`$PID` 是只读变量。循环里用 `$procId`。

### 不要用宽泛命令误杀当前 shell

不要用会匹配到当前 PowerShell 命令行的过滤条件后直接 `Stop-Process`。先查监听端口，再查命令行，再处理。

### 不要为了变好看破坏兼容

UI 重设计时必须保留：

- `localStorage` 旧会话恢复。
- 旧快照缺字段降级。
- `quality_review` 缺失提示。
- `local_transport.segments` 每日 item 展示。
- 返程不再带住宿建议。
- 活动无票价默认 0 的预算逻辑。

## 关键文件

- `sync/multi_agent/structured_planner.py`：结构化规划主逻辑，DeepSeek、路线评审、体检返工、聚类、预算都在这里。
- `sync/travel_web_app.py`：FastAPI Web 服务，`/api/plan`、`/api/map-static` 等。
- `sync/fastmcp_server_streamhttp.py`：本地 MCP 工具，高德天气、路线、POI、酒店搜索。
- `web/index.html`：页面骨架和静态资源版本。
- `web/app.js`：前端状态、请求 payload、会话保存、结果页渲染、编辑、预算和地图重建。
- `web/styles.css`：当前页面视觉和布局。
- `tests/test_travelmind_regression.py`：核心回归测试。
