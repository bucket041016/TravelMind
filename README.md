# TravelMind 启动说明

TravelMind 是一个基于 LangGraph/Multi-Agent + MCP + 高德 Web 服务的智能旅行规划工作台。当前版本重点支持结构化行程规划、真实 POI 行程点、酒店匹配、静态地图、预算评估、天气与出行建议，以及右侧追问对话。

## 运行端口

本项目使用：

- MCP Server：`http://127.0.0.1:8098/my-custom-path`
- Web App：`http://127.0.0.1:8010`


## 环境要求

- Windows + PowerShell
- Python 虚拟环境：`.venv`
- Node.js：用于检查前端脚本
- `.env` 中需要配置：

```env
DEEPSEEK_API_KEY=your_key
AMAP_MAPS_API_KEY=your_key
```

兼容的高德 Key 变量名：

```env
AMAP_MAPS_API_KEY
AMAP_API_KEY
GAODE_API_KEY
```

不要把 `.env` 内容打印到终端或文档里。

## 启动步骤

在项目目录执行：

```powershell
cd D:\Codexwork\my-langgraph-agent-main
```

### 1. 启动 MCP Server

打开第一个 PowerShell：

```powershell
$env:MCP_PORT='8098'
.\.venv\Scripts\python.exe sync\fastmcp_server_streamhttp.py
```

正常情况下会监听：

```text
http://127.0.0.1:8098/my-custom-path
```

### 2. 启动 Web App

打开第二个 PowerShell：

```powershell
$env:MCP_SERVER_URL='http://127.0.0.1:8098/my-custom-path'
.\.venv\Scripts\python.exe -m uvicorn sync.travel_web_app:app --host 127.0.0.1 --port 8010
```

非常重要：Web 必须设置 `MCP_SERVER_URL`。如果不设置，代码会默认连 `8083`，导致 POI、天气、路线全部失败。

### 3. 打开页面

浏览器访问：

```text
http://127.0.0.1:8010/?t=phase14-mapfix
```

默认表单可直接测试“广州到深圳 2 天游”。

## 当前主要功能

- `POST /api/plan`：结构化规划接口。
- `POST /api/multi-agent-chat`：右侧追问对话。
- `GET /api/map-static`：高德静态地图代理接口。
- 结果页展示：
  - 行程概览
  - 天气与出行建议
  - 住宿匹配
  - 景点与特色候选
  - 景点地图
  - 每日行程
  - 预算评估
- 每日行程支持前端编辑：上移、下移、删除。
- 支持导出 Markdown 和打印/保存 PDF。

## 结构化规划数据

`/api/plan` 返回核心字段：

```json
{
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
  "markdown": "",
  "trace": []
}
```

每日行程 item 会包含：

```json
{
  "title": "",
  "location": "",
  "address": "",
  "category": "activity|food|hotel|transfer|note",
  "is_real_place": true,
  "place_source": "amap_poi|hotel_poi|transport_hub|planning_note",
  "location_point": {"lng": 0, "lat": 0},
  "map_included": true
}
```

真实活动和餐饮应来自高德 POI 或酒店 POI。说明项不进入地图，不伪装成地点。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m py_compile .\sync\travel_web_app.py .\sync\multi_agent\structured_planner.py .\sync\fastmcp_server_streamhttp.py
node --check .\web\app.js
```

检查端口：

```powershell
Get-NetTCPConnection -LocalPort 8010,8098 -State Listen |
  Select-Object LocalPort,OwningProcess |
  Sort-Object LocalPort |
  Format-Table -AutoSize
```

检查当前记录：

```powershell
Get-Content .\travel-demo.pids.txt
```

## 推荐手工测试

### 广州到深圳 2 天游

预期：

- 推荐跨城主交通为高铁/城际或自驾候选。
- 每日行程不重复安排同一景点。
- `笔架山公园` 不应出现两次。
- 餐饮应为真实餐厅 POI，例如带地址、评分、人均的餐厅。
- 不出现 `特色晚餐与夜间散步` 这种泛化地点。
- 地图显示高德底图、编号点位和线路，不显示“暂不可用”兜底图。
- 预算在每日行程后展示。

### 北京到三亚 4 天游

预期：

- 飞机应作为主交通候选。
- 因未接入真实航班供应商，不展示虚构航班号、实时票价或余票。
- 酒店/景点/餐饮仍优先使用高德 POI。

### 高德失败或限流

预期：

- 页面不崩溃。
- POI 不足时显示“真实候选不足”说明项。
- 地图失败时显示明确兜底原因，例如限流或高德错误。

## 常见问题

### 页面显示“地图暂不可用，已显示点位示意图”

可能原因：

- 高德 QPS 限流。
- 高德静态地图返回 JSON 错误。
- 请求参数不合法。
- 浏览器缓存了旧 SVG 兜底图。

当前已修复第 10 个 marker label 导致的高德 `UNKNOWN_ERROR`。如果仍出现，先刷新并重新生成；再看 `travel-demo-web.out.log` 和 `/api/map-static` 返回类型。

### `/api/plan` 返回全是候选不足

通常是 Web 没连上 MCP。确认 Web 启动时设置了：

```powershell
$env:MCP_SERVER_URL='http://127.0.0.1:8098/my-custom-path'
```

也确认 MCP `8098` 正在监听。

### 高德限流

不要连续猛刷。可等待一会儿，或调整：

```env
AMAP_MIN_REQUEST_INTERVAL_SECONDS=0.45
AMAP_MAX_RETRIES=3
AMAP_CACHE_TTL_SECONDS=600
```

## 重要开发注意事项

- 项目当前不是标准 Git 仓库，不要依赖 `git status` 或 `git diff`。
- 修改文件后优先跑 `py_compile` 和 `node --check`。
- 修改后端 `sync/travel_web_app.py` 或 `sync/multi_agent/structured_planner.py` 后，需要重启 Web `8010`。
- 修改 `sync/fastmcp_server_streamhttp.py` 后，需要重启 MCP `8098`。
- 修改 `web/index.html` 的静态资源引用版本，避免浏览器缓存旧 `app.js/styles.css`。
- 不要新增高德请求数量太多，容易触发 QPS。
- 不要编造实时航班、火车票、酒店库存、门票库存。

## 安全重启示例

只停止本项目的 Web Python 进程：

```powershell
$webPids = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*uvicorn sync.travel_web_app:app*--port 8010*' } |
  Select-Object -ExpandProperty ProcessId

foreach ($procId in $webPids) {
  Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
```

重新启动 Web：

```powershell
$env:MCP_SERVER_URL='http://127.0.0.1:8098/my-custom-path'
.\.venv\Scripts\python.exe -m uvicorn sync.travel_web_app:app --host 127.0.0.1 --port 8010
```

注意：不要用 `$pid` 作为变量名，PowerShell 里 `$PID` 是只读变量。
