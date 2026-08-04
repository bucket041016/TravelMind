# TravelMind 文档索引

本目录是工作区根目录 13 个 Markdown 文件**合并去重**后的文档体系（2026-08-04 整理）。根目录原文件保留不动，仅作历史留档；**后续维护以本目录为准**。

代码根目录为 `my-langgraph-agent-main/`（本仓库即项目本体），下文所有相对路径均以此为基准。

## 文档角色一览

| 文档 | 职责 | 更新频率 | 来源文件 |
|---|---|---|---|
| [workspace-rules.md](workspace-rules.md) | 工作区规则、开发约定、安全与提交流程 | 低频（约定变更时） | `AGENTS.md`、`CLAUDE.md`、`HANDOFF.md`（坑清单）、`CONTINUATION_SUMMARY.md`（规则节） |
| [project-baseline.md](project-baseline.md) | 架构、目录职责、API/MCP 契约、运行方式、验证结果 | 低频（架构或契约变更时） | `PROJECT_BASELINE.md` |
| [product-overview.md](product-overview.md) | 产品对外介绍、亮点、MCP 工具表、启动演示 | 低频 | `TRAVELMIND_README.md` |
| [open-source-comparison.md](open-source-comparison.md) | GitHub 同类项目对比、差距矩阵、目标架构 | 低频（新调研时） | `OPEN_SOURCE_COMPARISON.md` |
| [implementation-plan.md](implementation-plan.md) | 阶段执行合同、任务看板、过程记录、当前状态 | 高频（每个 Phase/小步） | `IMPLEMENTATION_PLAN.md`、`task_plan.md`、`progress.md` |
| [findings.md](findings.md) | 勘察发现、各阶段发现、续接摘要与下一步入口 | 中频（按需补充） | `findings.md`、`CONTINUATION_SUMMARY.md` |
| [archive/handoff-2026-07-14.md](archive/handoff-2026-07-14.md) | 早期 UI 重设计交接，历史归档 | 不更新 | `HANDOFF.md` |
| [archive/product-upgrade-plan.md](archive/product-upgrade-plan.md) | 早期产品化升级分析，历史归档 | 不更新 | `PRODUCT_UPGRADE_PLAN.md` |
| [archive/multi-agent-upgrade-2026-07-10.md](archive/multi-agent-upgrade-2026-07-10.md) | 早期多 Agent 设计笔记，历史归档 | 不更新 | `MULTI_AGENT_UPGRADE.md` |

## 工具目录（不属于本文档体系）

- `docs/openspec/`、`docs/superpowers/`：由 openspec / superpowers 技能初始化生成，目前仅有配置或空框架，不要在里面放业务文档。

## 维护约定

1. 新增认知或规划内容前，先判断属于哪个角色，写入对应文档，避免重复记录。
2. 阶段结果、指标和验证命令只记录在 `implementation-plan.md`；分析结论记录在 `findings.md`。
3. 规则类约束只维护在 `workspace-rules.md`，其他文档需要时引用它，不重复抄写。
4. 根目录同名原文件为历史留档，不再同步更新；如有异议以本目录文档为准。
