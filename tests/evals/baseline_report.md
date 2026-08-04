# TravelMind Phase 0 离线评测基线

本报告使用 Fake MCP 和 Fake DeepSeek fixture，未访问外部网络、`.env` 或真实供应商。指标用于建立优化前对照，不是最终发布阈值。

## 汇总

- 场景数：10
- 总调用数：141；工具 fixture 失败数：4
- 规划模式：{'deepseek_hybrid': 9, 'rule_fallback': 1}

| 指标 | 平均值 |
|---|---:|
| 真实地点绑定率 (`real_place_binding_rate`) | 0.5940 |
| 重复地点率 (`duplicate_place_rate`) | 0.0000 |
| 硬约束满足率 (`hard_constraint_satisfaction`) | 0.6000 |
| 路线超容忍率 (`route_over_tolerance_rate`) | 0.0750 |
| 预算偏差 (`budget_deviation`) | 0.6217 |
| 返程住宿串台率 (`return_hotel_contamination_rate`) | 0.0000 |
| fallback 率 (`fallback_rate`) | 0.0833 |

## 场景明细

| 场景 | 绑定率 | 重复率 | 约束满足 | 超容忍 | 预算偏差 | 串台 | fallback | 调用 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| standard_weekend | 0.7143 | 0.0000 | 1.0000 | 0.0000 | 0.3783 | 0.0000 | 0.0000 | 15 |
| family_budget | 0.6364 | 0.0000 | 0.5000 | 0.0000 | 1.9067 | 0.0000 | 0.0000 | 17 |
| rainy_indoor_preference | 0.7143 | 0.0000 | 0.5000 | 0.0000 | 0.3783 | 0.0000 | 0.0000 | 15 |
| low_budget | 0.7143 | 0.0000 | 0.0000 | 0.0000 | 1.4380 | 0.0000 | 0.0000 | 15 |
| slow_pace | 0.6667 | 0.0000 | 0.5000 | 0.0000 | 0.4672 | 0.0000 | 0.0000 | 13 |
| tight_transfer_tolerance | 0.7143 | 0.0000 | 0.0000 | 0.7500 | 0.2583 | 0.0000 | 0.0000 | 15 |
| return_transfer_isolation | 0.6364 | 0.0000 | 1.0000 | 0.0000 | 0.0400 | 0.0000 | 0.0000 | 17 |
| duplicate_candidate | 0.4286 | 0.0000 | 1.0000 | 0.0000 | 0.4450 | 0.0000 | 0.0000 | 13 |
| dependency_fallback | 0.0000 | 0.0000 | 1.0000 | 0.0000 | 0.5267 | 0.0000 | 0.8333 | 6 |
| free_text_hard_constraint | 0.7143 | 0.0000 | 0.5000 | 0.0000 | 0.3783 | 0.0000 | 0.0000 | 15 |

## 解释

- 绑定率只统计行程中 `activity`、`food`、`hotel` 项目，并要求真实地点标记和有效坐标同时存在。
- 重复率按候选 `poi_id`、坐标或地点名归一后计算重复出现次数。
- 路线超容忍率使用场景的 `maxTransferMinutes`，没有路线段时记为 0，但不代表路线已得到验证。
- 预算偏差为 `abs(total-target)/target`；未设置预算时记为 `n/a`。
- fallback 率统计天气、POI、酒店、规划、评审和市内路线六类可观察降级组件。
- 本阶段刻意保留当前业务行为；例如自由文本未进入 `preferences` 的场景会作为基线缺口记录，留给 Phase 1 修复。
