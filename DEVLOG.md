# Ay 分支 - 开发日志

> **维护规则**：每次修改代码前，在本文件顶部（最新条目在最上方）新增一条记录。
> 每条记录包含：日期、意图、改动、验证、备注五个部分。
> 本日志仅跟踪 `Ay` 分支的工作，不记录 `bucket1` 的内容。

---

## [2026-11-01 15:30] 新增知识库检索工具 kb_retrieve

### 意图
- 行程里的景点详情、建议时长、预约规则等事实此前完全由 DeepSeek 自由生成，是幻觉的主要来源。落地 `docs/open-source-comparison.md` 中已列为 P1 的「目的地知识库」缺口：新增第 10 个 MCP 工具做检索，用检索结果替代模型对事实性文字的自由生成。

### 改动清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `sync/knowledge/__init__.py` | 新增 | 知识库包入口与共享检索器实例 |
| `sync/knowledge/retriever.py` | 新增 | `KnowledgeRetriever` 接口 + `KeywordRetriever` 纯 Python 关键词打分，零新依赖 |
| `sync/knowledge/cities/*.json` | 新增 | 9 城人工策展语料（城市攻略、分区、景点详情、美食注记、季节贴士） |
| `sync/fastmcp_server_streamhttp.py` | 修改 | 新增 `kb_retrieve` 工具，返回结构化 dict，异常不抛 |
| `sync/multi_agent/knowledge_service.py` | 新增 | 规划侧消费者：`knowledge_enabled()` flag、候选匹配与富化 |
| `sync/multi_agent/structured_planner.py` | 修改 | `run()` 插入 `KnowledgeAgent 知识库检索` 步骤，计划新增可选 `knowledge` 字段 |
| `sync/multi_agent/itinerary_builder.py` | 修改 | 规划脑 payload 暴露 knowledge 字段；行程项新增 `knowledge_detail` 与 `detail_source` |
| `sync/multi_agent/markdown_writer.py` | 修改 | Markdown 导出增加「知识库详情」行 |
| `web/app.js` | 修改 | `KnowledgeAgent` 映射到进度第 3 阶段；优先渲染知识库详情并打标；导出同步 |
| `web/styles.css` | 修改 | `.activity-knowledge` 与 `.knowledge-badge` 样式 |
| `.env.example` | 修改 | 补充 `TRAVELMIND_KNOWLEDGE=off` |
| `tests/test_knowledge_retrieval.py` | 新增 | 检索器、flag 灰度、富化、refine 保持性 |
| `tests/test_mcp_protocol.py` | 修改 | 内存 FastMCP server 增加 `kb_retrieve` dict 往返用例 |
| `tests/evals/fixtures.py` | 修改 | `FixtureToolbox` 增加 `kb_retrieve` 分支与 `kb_covered` 开关 |
| `tests/evals/test_knowledge_eval.py` | 新增 | 知识库专用评测场景（4 个）与可观测指标 |
| `docs/findings.md`、`docs/project-baseline.md` | 修改 | 记录设计、验证结果与观察项 |

### 验证
- [x] `py_compile` 通过（sync、async、tests 全量）
- [x] `node --check web/app.js` 通过
- [x] 全量单测 252/252 通过（原 220 + 新增 32）
- [x] 离线评测重新生成与库内 `phase3_report.json` aggregate 完全一致（139 次调用、4 次 fixture 失败、七项指标平均值逐一相同）
- [x] 发布质量门通过（关键指标无回退）
- [x] Playwright E2E 11 通过 / 1 跳过，与既有基线一致
- [x] 真实验收：8098 + 8010 双服务、`TRAVELMIND_KNOWLEDGE=on`，广州→深圳 2 天规划成功；知识库命中 3/24 候选，两个室内项正好匹配「优先室内场所」freeText

### 备注
- 知识库只补背景知识与解释，不引入地点、坐标、票价、库存或班次；候选 `place_source` 仍是 `amap_poi`，真实地点护栏不受影响，契约层零改动。
- 语料原计划放 `sync/multi_agent/knowledge/`，但会经 `multi_agent/__init__.py` 把 langchain 拖进 MCP Server 进程，遂改为 `sync/knowledge/` 与 `multi_agent` 平级。
- `TRAVELMIND_KNOWLEDGE` 默认 off，关闭时零工具调用、计划与现状逐字段一致；flag 翻默认时需合并评测场景并重定基线（做法见 findings.md 观察项 3）。
- 下一步：扩张语料覆盖（当前 9 城是命中率的主要上限）。

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

## [2026-08-01 11:38] Phase E 约束链路集成

### 意图
- 将已搬运但未接入的 contracts.py、fact_normalizer.py、candidate_ranker.py 三个模块集成到实际规划流程
- 提升行程规划的数据质量（归一化）和候选排序能力（偏好匹配+天气适配+价格过滤）

### 改动清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `sync/multi_agent/poi_service.py` | 修改 | 导入 fact_normalizer/candidate_ranker，新增 _normalize_and_rank_pois() 对景点/美食/特色店铺做归一化+排序 |
| `sync/multi_agent/hotel_service.py` | 修改 | 导入 fact_normalizer/candidate_ranker，新增 _normalize_and_rank_hotels() 对酒店候选做归一化+排序 |
| `sync/multi_agent/weather_service.py` | 修改 | 导入 fact_normalizer，新增 _normalize_weather_facts() 将原始天气文本转为结构化 WeatherFact |
| `sync/multi_agent/structured_planner.py` | 修改 | 在 run() 中调用三个归一化/排序函数，输出新增 weather_facts 字段，兼容层绑定新函数 |
| `tests/test_phase_e_constraints.py` | 新增 | 22 个测试覆盖 contracts/fact_normalizer/candidate_ranker 单元和集成场景 |

### 验证
- [x] 全部 29 个 .py 文件 py_compile 通过
- [x] 全部 44 个测试通过（22 旧 + 22 新，零回归）
- [ ] 已提交到 Ay 分支

### 备注
- 设计为非侵入式：归一化和排序作为后处理步骤追加，不改变 _build_pois/_build_hotels/_build_weather 的原有输入输出
- 每个 POI/酒店候选现在携带 source_meta（数据来源可信度）、validation（字段完整性检查）、selection（排序分数和理由）
- candidate_ranker 会根据天气自动降权不适合的候选（如雨天降权户外公园/海边）
- candidate_ranker 会根据用户偏好兴趣做匹配加分，有坐标和评分的候选自动加权
- 下一步：UI 重设计，或前端展示 source_meta/selection 排序理由

---

## [2026-08-01 11:24] Phase D 模块化修复 + 文档清理

### 意图
- 修复模块化拆分后的测试失败（14 个 -> 0 个）
- 清理不属于 Ay 分支的文档文件

### 改动清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `sync/multi_agent/deepseek_brain.py` | 修改 | 添加 _sanitize_no_proxy() 清理系统 NO_PROXY 环境变量中 httpx 0.28+ 无法解析的条目 |
| `sync/multi_agent/structured_planner.py` | 修改 | 兼容层全部改为 staticmethod 绑定，run() 方法显式传入 toolbox/deepseek_brain |
| `sync/multi_agent/local_transport_service.py` | 修改 | _amap_local_segment 和 _judge_local_segment 从 self 依赖改为显式 toolbox/deepseek_brain 参数 |
| `sync/multi_agent/hotel_service.py` | 修改 | _estimate_hotel_price_ranges 从 self 依赖改为显式 deepseek_brain 参数 |
| `sync/multi_agent/*.py` | 修改 | 批量清理模块级函数中遗留的 self/cls 参数，解决循环导入 |
| `tests/test_travelmind_regression.py` | 修改 | 适配纯函数调用方式，在调用中传入 toolbox/deepseek_brain |


### 验证
- [x] 全部 27 个 .py 文件 py_compile 通过
- [x] 全部 22 个测试通过（从 14 失败降到 0 失败）
- [x] 已提交到 Ay 分支

### 备注
- 测试失败的三个根因：1) 系统 NO_PROXY 格式与 httpx 0.28+ 不兼容；2) 模块级函数保留了 self 参数但兼容层绑定类型不匹配；3) 模块内部函数调用链中 self.toolbox/self.deepseek_brain 无法通过纯函数传递
- 解决方案：将所有模块级函数改为纯函数（不依赖 self），需要 toolbox/deepseek_brain 的函数改为通过显式 keyword 参数传入
- 4 个删除的 .md 文件是 Bucket55 在 Initial commit 时加入的工作笔记，有价值的内容已在 Gold-WC-bucket1/ 审计副本中保留
- 下一步：UI 重设计 或 Phase E 约束链路集成

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
- [x] 已提交到 Ay 分支

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
