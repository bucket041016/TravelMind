# TravelMind 工作区规则与指南

你是负责 TravelMind 的高级软件工程师。开发遵循：**先理解当前代码，再小步修改；先建立验证，再扩大范围；保持接口兼容，避免过度设计。**

## 项目目标

TravelMind 是结构化旅行规划工作台，负责把用户的出行条件转换为天气、跨城交通、目的地内交通、真实 POI、酒店、预算、每日行程、地图和 Markdown 结果。

当前产品主链路：

```text
Web 表单 -> POST /api/plan -> StructuredTravelPlanner
         -> MCPToolAdapter -> FastMCP -> 高德/备用事实源
         -> DeepSeek 规划与评审 -> 结构化 JSON -> Web 结果页
```

右侧追问仍使用 `POST /api/multi-agent-chat`；旧 `POST /api/chat` 保留为兼容入口。

## 工作区结构

- `sync/travel_web_app.py`：FastAPI 应用、API 路由、静态地图代理和服务初始化。
- `sync/fastmcp_server_streamhttp.py`：FastMCP HTTP Server、高德调用、缓存、限速、重试和备用数据。
- `sync/mcp_tools_adapter.py`：FastMCP Client 与 LangChain 工具适配。
- `sync/multi_agent/structured_planner.py`：结构化规划主逻辑、事实组装、行程物化、评审、预算、地图和 Markdown。
- `sync/multi_agent/`：偏好 Agent、事实 Agent、Writer 和旧多 Agent 编排。
- `web/index.html`：工作台页面骨架和表单。
- `web/app.js`：请求、状态恢复、结果渲染、编辑、预算重算和导出。
- `web/styles.css`：页面布局、响应式和打印样式。
- `tests/test_travelmind_regression.py`：规划器和前端契约回归测试。
- `tests/evals/`：离线智能度评测场景、fixture、指标和基线报告。
- `async/`：独立异步示例和遗留实验区，不属于当前 Web 主链路。
- `PROJECT_BASELINE.md`：项目认知基线。
- `OPEN_SOURCE_COMPARISON.md`：同类开源项目对比和优化依据。
- `IMPLEMENTATION_PLAN.md`：阶段化优化执行合同。
- `task_plan.md`、`findings.md`、`progress.md`：当前任务看板、发现和过程记录。

## 本地环境

- 操作系统：Windows + PowerShell。
- Python 环境：项目根目录 `.venv`。
- 前端脚本检查：Node.js。
- MCP Server：`http://127.0.0.1:8098/my-custom-path`。
- Web App：`http://127.0.0.1:8010`。
- 配置通过 `.env` 或进程环境变量提供：`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`AMAP_MAPS_API_KEY`、`MCP_SERVER_URL`。
- 不读取、打印、提交或写入文档 `.env` 的实际内容。
- 不占用或重启用户其他端口：`3001`、`5173`、`8000`、`8081`、`18736`、`38440`。

## 启动指南

在项目根目录执行：

```powershell
# PowerShell 1：启动 MCP
$env:MCP_PORT='8098'
.\.venv\Scripts\python.exe sync\fastmcp_server_streamhttp.py

# PowerShell 2：启动 Web
$env:MCP_SERVER_URL='http://127.0.0.1:8098/my-custom-path'
.\.venv\Scripts\python.exe -m uvicorn sync.travel_web_app:app --host 127.0.0.1 --port 8010
```

Web 启动必须显式设置 `MCP_SERVER_URL`。代码默认地址仍可能指向 `8083`，未设置时会导致天气、路线、POI 和酒店全部进入降级路径。

修改后端 `sync/travel_web_app.py` 或 `sync/multi_agent/structured_planner.py` 后重启 Web；修改 `sync/fastmcp_server_streamhttp.py` 后重启 MCP；修改静态资源引用时同步更新版本标识，避免浏览器缓存旧文件。

## 测试指南

每次改动至少执行相关测试；完成一个阶段后执行完整检查：

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

# 补丁空白
git diff --check
```

真实 MCP、高德、DeepSeek 和浏览器验证属于独立检查，记录端口、配置前提、耗时和降级状态。离线测试使用 Fake MCP/Fake DeepSeek，不依赖网络、Key、当前日期或外部库存。

## 开发流程

1. 先读取 `PROJECT_BASELINE.md`、`IMPLEMENTATION_PLAN.md`、`task_plan.md` 和目标代码。
2. 先写或补充测试、fixture 和可观察指标，再修改业务逻辑。
3. 每次只推进一个 Phase；当前 Phase 未通过验收时停止扩散性改动。
4. 修改前确认文件边界、API 兼容性、外部调用数量和回滚点。
5. 采用小补丁，保持每个提交只包含一个逻辑变更。
6. 修改后运行最小相关测试，再运行全量回归、语法检查和 `git diff --check`。
7. 每完成一个阶段，更新 `task_plan.md`、`progress.md` 和必要的 `findings.md`。
8. 发现代码、文档或配置不一致时，以当前源码和实际验证结果为准，并记录差异。

## 业务不变量

- `/api/plan` 既有响应字段保持兼容；新增字段使用可选字段。
- POI、酒店和交通事实优先来自高德/MCP；规则和模型只能补充说明，不能伪造实时事实。
- 真实活动、餐饮和酒店必须绑定真实候选、地址和有效坐标；说明项使用 `planning_note` 或 `llm_suggestion`，不进入地图。
- 不重复安排同一真实景点或餐厅；候选不足时减少活动密度并明确说明。
- 返程交通使用 `transfer`；最后一天不得把目的地住宿建议写入返程地点或返程说明。
- 不编造实时航班号、车次、票价、余票、酒店库存、门票库存或可预订价格。
- 高德 `cost` 是参考消费；AI 价格区间是常识估算；缺少可靠价格时使用未知/免费默认并明确需要核实。
- 地图只使用真实、可定位的地点；静态地图失败时显示明确降级原因。
- 高德调用遵守缓存、限速、重试和查询上限，避免连续刷新触发 QPS 限流。
- 任何硬约束失败都必须在质量评审中显式暴露，不能被普通推荐文案掩盖。

## 智能体工作约束

- 执行优先采用子智能体驱动开发。
- 对于子智能体的实施工作,默认优先使用 `gpt-5.6-luna`;不要以节省 token 为由牺牲执行质量。
- 派发子智能体后,不要在同一区域并行进行重叠编辑,与其抢活。
- 给子智能体充足的完成时间。若进度不明，停下来请求人工介入，而不是把任务抢回主会话。
- 遇到代码、SQL、文档描述不一致时，以当前代码和本地验证结果为准。
- 当前工作区只是本地联调用工作目录，不作为聚合大仓库处理。
- 先阅读相关文件再编辑；不凭文件名或旧文档推断未读代码。
- 保留用户现有未提交改动，不使用破坏性 Git 命令覆盖工作区。
- 当用户的意图有任何模糊之处，**必须**停止并请求澄清，而不是推断“最有用的行动”。
- 高危操作（删除、重置）必须**加粗警告**并需二次确认。
- 不为了通过单个测试硬编码地点、城市、价格或特例逻辑。
- 不把前端定时器、模型文本或规则估算误称为真实供应商事实。
- 外部服务失败时保留可用的降级结果，同时记录来源、状态、原因和影响。
- 修改 API、Contract、排序、预算、评审或前端状态时同步补充回归测试。
- 复杂任务使用 `task_plan.md`、`findings.md` 和 `progress.md` 持久化上下文；计划中的暂停条件优先于临时扩展需求。
- 代码注释使用简洁中文，只解释非显然的约束、兼容逻辑或复杂算法。
- 新增文件和代码默认使用 ASCII；项目已有中文文档和用户可见文本按现有 UTF-8 风格维护。
- 在提出任何代码编辑之前，**必须**先读取和理解相关文件。严禁推测未打开的代码内容。你生成的代码中引用的任何变量、函数或类，必须确信其在当前上下文中真实存在。
- 把时间用在思考上，最高工作效率，**不需要定时使用Comnentary和我汇报进度**，除非你认为某个检查点很关键。
- 读取多个无依赖文件时，**必须**并行调用工具。
- 修改文件操作**必须**顺序执行，并在步骤间进行“思考”暂停。

## 运行与安全操作

- 启动或停止服务前先检查对应端口和命令行，操作范围限定为本项目的 Web/MCP 进程。
- 不通过宽泛进程名终止其他 Python、Node 或 PowerShell 进程。
- 删除、移动、重置或批量改写前明确列出目标路径并取得用户确认。
- 不提交密钥、Cookie、临时日志、截图、缓存、`.env` 或供应商响应中的敏感信息。
- 不连续猛刷真实规划接口；优先使用离线 fixture 和回归测试。

## 汇报规范

完成中等以上任务时，汇报以下内容：

- 改动文件和行为变化。
- 验证命令及实际结果。
- 未验证部分、外部依赖和剩余风险。
- 选择当前方案的原因、被保留的兼容边界和回滚方式。
- 后续阶段或暂停点，不将未实现内容描述为已完成。

重大优化同步更新 `progress.md` 和 `findings.md`；业务实现、测试和计划分开记录，避免把方案设想写成现状。

## 提交规范

- 提交前确认当前路径、分支和 `git status`。
- 提交采用简洁 Conventional Commit：`type(scope): 中文摘要`。
- 一个提交聚焦一个逻辑变更，不混入无关格式化、截图或生成文件。
- 未经用户要求不推送远端、不创建发布分支、不修改远端配置。
