# TravelMind

> 把“想去哪里”变成一份可执行的旅行计划。

TravelMind 是一个智慧旅行规划助手。输入出发地、目的地、日期、预算和兴趣偏好后，它会整理路线、天气、住宿、景点、美食、每日安排、地图和预算，帮助你更快做出旅行决定。

## 你可以用 TravelMind 做什么

- 规划周末短途、城市周边游和多日旅行。
- 对比高铁/城际、自驾、公共交通、打车和步行等出行方式。
- 根据天气给出穿衣、降雨、防晒和出行建议。
- 推荐真实景点、餐厅、特色地点和酒店候选。
- 按天生成行程，并按照地点距离安排顺序。
- 查看地图、预算拆分和路线说明。
- 在结果页编辑行程：调整顺序、删除项目或重新规划。
- 通过右侧对话继续提出要求，例如“节奏慢一点”“少安排步行”“增加室内景点”。
- 导出 Markdown，或直接打印/保存为 PDF。

## 计划使用流程

1. 填写出发城市、目的地、日期、天数、人数和预算。
2. 选择交通方式、住宿档次和旅行兴趣。
3. 在“补充要求”中写下特殊偏好，例如“不要安排夜间活动”或“优先室内场所”。
4. 点击生成计划，查看路线、天气、住宿、每日行程、地图和预算。
5. 根据需要编辑行程，或继续追问让 TravelMind 调整方案。

### 示例需求

```text
从广州出发去深圳玩 2 天，预算 800 元，喜欢经典景点和美食，
希望住在地铁附近，行程节奏轻松，晚上不要安排太晚的活动。
```

## 计划内容

一份完整计划通常包括：

- **行程概览**：目的地、日期、人数、旅行节奏和核心建议。
- **跨城交通**：推荐方式、备选方式、预计耗时和费用参考。
- **天气建议**：目的地天气以及穿衣、防晒、降雨和出行提醒。
- **住宿匹配**：酒店候选、所在片区、附近地标和选择理由。
- **景点与美食**：地点、地址、坐标、评分、人均和推荐理由。
- **每日行程**：按时间顺序排列的景点、餐饮、住宿和交通安排。
- **地图视图**：行程点位和地点之间的路线。
- **预算评估**：交通、住宿、餐饮、门票和市内交通的费用拆分。

## 页面入口

本地启动后访问默认页面：<http://127.0.0.1:8010/>

旧版 `/v2` 入口已合并进首页，访问 `/v2` 会自动重定向回首页。

默认示例可以直接体验“广州 → 深圳 2 天游”。

## 本地运行

### 环境准备

- Windows + PowerShell
- Python 3.10 或更高版本
- Node.js（用于前端检查）
- DeepSeek API Key
- 高德 Web 服务 Key

### 安装

在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Copy-Item .env.example .env
```

编辑 `.env`，填写至少以下配置：

```env
DEEPSEEK_API_KEY=你的 DeepSeek API Key
AMAP_MAPS_API_KEY=你的高德 Web 服务 Key

MCP_PORT=8098
MCP_SERVER_URL=http://127.0.0.1:8098/my-custom-path
```

`requirements.txt` 已包含 Web、Agent、模型调用和 MCP 服务所需依赖。密钥仅保存在本地 `.env` 文件中。

高德 Key 也兼容以下变量名：

```env
AMAP_MAPS_API_KEY
AMAP_API_KEY
GAODE_API_KEY
```

### 启动

打开第一个 PowerShell，启动旅行数据服务：

```powershell
$env:MCP_PORT = '8098'
.\.venv\Scripts\python.exe sync\fastmcp_server_streamhttp.py
```

再打开第二个 PowerShell，启动网页：

```powershell
$env:MCP_SERVER_URL = 'http://127.0.0.1:8098/my-custom-path'
.\.venv\Scripts\python.exe -m uvicorn sync.travel_web_app:app --host 127.0.0.1 --port 8010
```

然后在浏览器打开 [默认页面](http://127.0.0.1:8010/)。

## 数据说明

- 高德服务用于提供天气、地点、路线和地图等信息。
- 高德请求失败、限流或 Key 未配置时，系统会显示数据状态，并使用备用内容或规则生成方案。
- 景点、餐厅和酒店优先使用带有地址与坐标的真实地点候选。
- 铁路、航班、酒店库存和实时可预订价格当前属于参考信息；具体班次、价格和房态请以官方渠道为准。

### 目的地知识库（可选）

系统另有一份人工策展的目的地知识库，用于补充高德不提供的背景事实（景点亮点、建议时长、预约购票规则、室内与雨天替代、本地贴士），减少行程文字对模型自由生成的依赖。默认关闭，在 `.env` 中开启：

```env
TRAVELMIND_KNOWLEDGE=on
```

开启后每次规划会多一次知识库检索调用，并在结果页为命中条目显示「知识库」详情。知识库只补充背景说明，不提供地点坐标、实时价格、库存或班次；真实地点与坐标仍由高德提供。

高德服务的稳定性参数可以按需调整：

```env
AMAP_CACHE_TTL_SECONDS=600
AMAP_CACHE_MAX_ITEMS=256
AMAP_MIN_REQUEST_INTERVAL_SECONDS=0.45
AMAP_MAX_RETRIES=3
```

默认情况下，系统使用本地 MCP 服务；如果需要加载高德官方远程 MCP，可以额外配置：

```env
ENABLE_AMAP_REMOTE_MCP=false
# AMAP_MCP_URL=https://mcp.amap.com/mcp?key=你的高德 Web 服务 Key
```

## 进阶使用：结构化规划接口

如果你希望从自己的页面、脚本或自动化流程调用 TravelMind，可以使用以下接口：

| 方法 | 地址 | 作用 |
| --- | --- | --- |
| `POST` | `/api/plan` | 生成结构化旅行计划 |
| `POST` | `/api/multi-agent-chat` | 发送自然语言追问 |
| `POST` | `/api/chat` | 使用传统单 Agent 对话 |
| `GET` | `/api/tools` | 查看可用工具 |
| `GET` | `/api/map-static` | 获取静态地图 |
| `POST` | `/api/reset` | 清空单 Agent 对话记录 |

### `/api/plan` 请求示例

```json
{
  "originCity": "广州",
  "destinationCity": "深圳",
  "startDate": "2026-08-15",
  "days": 2,
  "travelers": 1,
  "budget": 800,
  "intercityModes": ["高铁/动车/城际", "自驾"],
  "localModes": ["公共交通", "打车", "步行"],
  "hotelLevel": "舒适",
  "interests": ["经典景点", "美食", "地方特色"],
  "freeText": "优先地铁附近，晚上不要安排太晚的活动"
}
```

返回结果包含行程、交通、天气、酒店、POI、地图、预算、质量检查和 trace：

```json
{
  "plan_id": "tm-xxxxxxxxxx",
  "preferences": {},
  "intercity_transport": {},
  "local_transport": {},
  "hotels": {},
  "weather": {},
  "weather_advice": {},
  "pois": {},
  "map": {},
  "budget": {},
  "itinerary_days": [],
  "quality_review": {},
  "markdown": "",
  "trace": [],
  "planning_mode": "deepseek_hybrid",
  "llm_status": "used"
}
```

每日行程项目通常包含：

```json
{
  "title": "深圳湾公园",
  "location": "深圳湾公园",
  "address": "广东省深圳市南山区",
  "category": "activity",
  "is_real_place": true,
  "place_source": "amap_poi",
  "location_point": {"lng": 113.95, "lat": 22.52},
  "map_included": true
}
```

`category` 支持 `activity`、`food`、`hotel`、`transfer` 和 `note`。说明项可以出现在行程文字中，但地图只展示带有效地点和坐标的项目。

## 常见问题

### 页面提示候选不足或数据降级

先确认两个服务都已启动，并检查 Web 启动时的 `MCP_SERVER_URL` 是否与 MCP 服务端口一致。高德服务限流时可以稍后再次生成。

### 地图显示示意图

这通常表示高德静态地图 Key 缺失、请求被限流或暂时返回错误。行程文字和坐标仍会保留，补充高德 Key 后可以重新生成地图。

### 想调整行程

可以直接在每日行程中移动或删除项目，也可以在右侧对话中提出新的要求，例如：

```text
把第二天安排得轻松一些，减少跨区域移动，并增加一个室内景点。
```

## 推荐体验场景

### 广州到深圳 2 天游

适合验证完整的短途规划流程，重点观察：

- 高铁/城际和自驾是否都有候选。
- 每日景点是否重复。
- 餐饮是否带有地址、评分或人均等地点信息。
- 地图是否展示点位和路线。
- 预算是否出现在每日行程之后。

### 北京到三亚 4 天游

适合验证远距离出行策略，重点观察：

- 飞机是否作为主要交通候选。
- 页面是否明确标注航班、票价和库存的实时数据边界。
- 目的地酒店、景点和餐饮是否仍优先使用地点候选。

### 高德 Key 缺失或接口限流

适合验证降级体验，重点观察：

- 页面保持可用，并显示明确的数据状态。
- POI 不足时出现“真实候选不足”等说明。
- 地图失败时显示具体原因或点位示意图。

## 自检与验证

修改项目后可以运行以下命令：

```powershell
# Python 语法
Get-ChildItem sync,async,tests -Recurse -Filter *.py | ForEach-Object {
    .\.venv\Scripts\python.exe -m py_compile $_.FullName
}

# 前端语法
node --check .\web\app.js

# 全量回归
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 离线评测
.\.venv\Scripts\python.exe -m unittest discover -s tests\evals -v

# 发布质量门（当前评测 vs 仓库内参照报告，关键指标回退即失败）
.\.venv\Scripts\python.exe -m tests.evals.release_gate

# 端到端（Playwright，桌面 + 移动视口；自动起离线 fixture 服务，无需 Key）
npm install
npx playwright test

# 补丁空白检查
git diff --check
```

检查服务端口：

```powershell
Get-NetTCPConnection -LocalPort 8010,8098 -State Listen |
  Select-Object LocalPort,OwningProcess |
  Sort-Object LocalPort |
  Format-Table -AutoSize
```

离线评测使用固定场景和 fixture，不依赖网络、API Key 或当前日期。报告位于 `tests/evals/`。

E2E 首次运行前需 `npm install` 安装 `@playwright/test`，并确保已安装 Chromium（`npx playwright install chromium`）。测试跑在 `tests/e2e/fixture_server.py` 上：它挂载生产 FastAPI app，但把工具箱和规划脑换成评测 fixture，因此同样不依赖网络、API Key 或当前日期。HTML 报告在 `playwright-report/`，失败现场在 `test-results/`，两者都已在 `.gitignore` 中。

## 故障排查

### 页面显示“地图暂不可用，已显示点位示意图”

常见原因包括高德 QPS 限流、静态地图接口返回错误、请求参数异常或浏览器缓存旧资源。可以先刷新页面并重新生成计划，再查看 `logs/` 下的日志文件和 `/api/map-static` 返回类型。

### `/api/plan` 返回候选不足

重点确认：

1. MCP Server 正在 `8098` 端口运行。
2. Web 启动时设置了：

   ```powershell
   $env:MCP_SERVER_URL = 'http://127.0.0.1:8098/my-custom-path'
   ```

3. 高德 Key 已写入 `.env`，且变量名为 `AMAP_MAPS_API_KEY`、`AMAP_API_KEY` 或 `GAODE_API_KEY`。

### 高德接口限流

连续生成多个计划时可能触发高德 QPS 限制。可以等待一段时间后再试，并使用上面的缓存、请求间隔和重试配置降低请求压力。

### 修改代码后页面仍显示旧内容

后端文件修改后重启对应服务；前端静态资源修改后刷新浏览器。页面中的资源版本号用于帮助浏览器获取最新的 `app.js` 和 CSS。

## 了解项目

TravelMind 的详细项目资料位于 `docs/`：

- [产品概览](docs/product-overview.md)
- [项目认知基线](docs/project-baseline.md)
- [执行计划](docs/implementation-plan.md)
- [文档索引](docs/README.md)

开发者可以在修改代码后运行：

```powershell
node --check .\web\app.js
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
