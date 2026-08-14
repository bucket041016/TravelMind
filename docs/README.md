# TravelMind 文档索引

本目录是工作区根目录 Markdown 文件**合并去重**后的文档体系（2026-08-04 整理）。根目录原文件保留不动，仅作历史留档；**后续维护以本目录为准**。

代码根目录为 `my-langgraph-agent-main/`（本仓库即项目本体），下文所有相对路径均以此为基准。

## 文档角色一览

| 文档 | 职责 | 更新频率 |
|---|---|---|
| [target-architecture.md](target-architecture.md) | 目标架构：现状/理想规划流程、五处断点、逐环节 Phase 映射、设计红线 | 低频（架构目标变更时） |
| [how-it-works.md](how-it-works.md) | 白话讲解：用旅行社规划师的比喻讲清八步理想流程，面向非技术读者 | 低频（流程大改时） |
| [project-baseline.md](project-baseline.md) | 架构、目录职责、API/MCP 契约、运行方式、验证结果 | 低频（架构或契约变更时） |
| [product-overview.md](product-overview.md) | 产品对外介绍、亮点、MCP 工具表、启动演示 | 低频 |
| [open-source-comparison.md](open-source-comparison.md) | GitHub 同类项目对比、差距矩阵 | 低频（新调研时） |
| [implementation-plan.md](implementation-plan.md) | 阶段执行合同、任务看板、工程债务台账、过程记录、当前状态 | 高频（每个 Phase/小步/债务项） |
| [findings.md](findings.md) | 勘察发现、各阶段发现、验证证据、续接摘要与下一步入口 | 中频（按需补充） |

## 维护约定

1. 新增认知或规划内容前，先判断属于哪个角色，写入对应文档，避免重复记录。
2. 阶段结果、指标和验证命令只记录在 `implementation-plan.md`；分析结论与实验证据记录在 `findings.md`。
3. 规则类约束（分支、提交、日志、emoji 禁令等）维护在根目录 `CONTRIBUTING.md` 与 `DEVLOG.md`，其他文档需要时引用它们，不重复抄写。
4. 根目录同名原文件为历史留档，不再同步更新；如有异议以本目录文档为准。
