# Ay 分支 - 开发日志

> **维护规则**：每次修改代码前，在本文件顶部（最新条目在最上方）新增一条记录。
> 每条记录包含：日期、意图、改动、验证、备注五个部分。
> 本日志仅跟踪 `Ay` 分支的工作，不记录 `bucket1` 的内容。

---

## 格式模板

<!-- 复制下方模板到顶部，填入内容后删除本注释 -->
<!--
## [YYYY-MM-DD HH:MM] 简要标题

### 意图
- 为什么要做这次修改？解决什么问题？

### 改动清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `path/to/file` | 新增/修改/删除 | 一句话描述 |

### 验证
- [ ] `py_compile` 通过
- [ ] `node --check` 通过
- [ ] 页面功能正常
- [ ] 已提交到 Ay 分支

### 备注
- 参考了什么？遇到了什么坑？下一步打算做什么？
-->

---

## [2026-07-31 22:00] Phase A+B+C 后端模块化拆分

### 意图
- 将 3626 行的巨型 structured_planner.py 拆分为 13 个职责单一的模块
- 搬运朋友 bucket1 分支的 3 个独立模块（contracts, fact_normalizer, candidate_ranker）
- 提取常量和 DeepSeek 类到独立文件
- 逐个提取业务模块：天气、交通、POI、酒店、行程、预算、地图、质量评审、Markdown 等

### 改动清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `sync/multi_agent/constants.py` | 新增 | 城市距离、坐标、交通模式映射等全局常量 |
| `sync/multi_agent/deepseek_brain.py` | 新增 | DeepSeek 规划脑 Agent 类 |
| `sync/multi_agent/text_parser.py` | 新增 | 纯静态文本解析工具方法 |
| `sync/multi_agent/weather_service.py` | 新增 | 天气查询与穿衣建议服务 |
| `sync/multi_agent/transport_service.py` | 新增 | 跨城交通路线规划服务 |
| `sync/multi_agent/hotel_service.py` | 新增 | 酒店匹配与推荐服务 |
| `sync/multi_agent/poi_service.py` | 新增 | 景点美食 POI 查询与聚类服务 |
| `sync/multi_agent/local_transport_service.py` | 新增 | 目的地内交通路线段构建服务 |
| `sync/multi_agent/budget_calculator.py` | 新增 | 预算计算与费用估算服务 |
| `sync/multi_agent/itinerary_builder.py` | 新增 | 行程构建与 LLM 行程物化服务 |
| `sync/multi_agent/quality_reviewer.py` | 新增 | 行程质量评审与修复服务 |
| `sync/multi_agent/map_builder.py` | 新增 | 景点地图生成服务 |
| `sync/multi_agent/markdown_writer.py` | 新增 | 行程 Markdown 输出服务 |
| `sync/multi_agent/contracts.py` | 新增 | 从 bucket1 搬运的数据契约定义 |
| `sync/multi_agent/fact_normalizer.py` | 新增 | 从 bucket1 搬运的事实归一化模块 |
| `sync/multi_agent/candidate_ranker.py` | 新增 | 从 bucket1 搬运的候选排序模块 |
| `sync/multi_agent/structured_planner.py` | 修改 | 从 3626 行缩减到 601 行，保留编排器和向后兼容层 |

### 验证
- [x] 全部 27 个 .py 文件 py_compile 通过
- [x] 测试 8 通过 14 失败（与拆分前基线一致，失败均为 httpx 兼容性问题）
- [ ] 已提交到 Ay 分支

### 备注
- structured_planner.py 保留了向后兼容层，将所有提取的函数重新绑定为类属性，确保测试和其他代码的 self.method() 和 Class.method() 调用方式都能正常工作
- 上次对话中遇到 PowerShell 5.1 的编码破坏问题，已新增规则四强制使用 pwsh 7
- 下一步：Phase D 集成朋友的约束链路；UI 重设计

---

## [2026-07-31 21:18] 清除 emoji、建立持久化规则

### 意图
- 全面禁止 emoji，保持文档和输出的专业一致性
- 将开发日志和 emoji 禁令写入跨对话持久化知识条目，确保后续对话也遵守

### 改动清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `DEVLOG.md` | 修改 | 清除所有 emoji 符号，改用纯文本标题 |

### 验证
- [x] 文档内无任何 emoji
- [x] 知识条目已写入持久化存储
- [x] 已提交到 Ay 分支

### 备注
- 知识条目路径：`knowledge/gold-wc-dev-rules/`，包含日志规则、emoji 禁令、分支管理三条强制规则
- 该知识条目在每次新对话开始时自动加载，不依赖用户提醒

---

## [2026-07-31 21:00] 项目初始化与分支建立

### 意图
- 首次克隆项目，建立 Ay 开发分支，配置本地运行环境，验证项目可正常启动

### 改动清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `.env` | 新增 | 配置 DeepSeek 和高德 API Key（已在 .gitignore 中，不会提交） |
| `.venv/` | 新增 | Python 虚拟环境，安装了 requirements.txt + fastmcp |
| `.gitignore` | 修改 | 添加 `/Gold-WC-bucket1/` 忽略规则 |
| `CONTRIBUTING.md` | 新增 | 协作规范文档 |
| `Gold-WC-bucket1/` | 新增 | 朋友 bucket1 分支的只读审计副本（push 已禁用） |

### 验证
- [x] `py_compile` 通过
- [x] MCP Server 在 8098 端口正常启动
- [x] Web App 在 8010 端口正常启动
- [x] 浏览器访问页面正常显示
- [x] 已提交并推送到 Ay 分支

### 备注
- `fastmcp` 不在 requirements.txt 中，需要额外安装，后续应补充进去
- `fastmcp` 安装时升级了 `starlette`，导致与 `fastapi` 版本冲突，需要重新安装 `fastapi==0.116.1` 降级 starlette
- 朋友 bucket1 分支已有 Phase 0-2 的改动（6772 行新增），后续审计时参考
