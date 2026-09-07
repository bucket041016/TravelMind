from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

try:
    from sync.multi_agent.structured_planner import StructuredTravelPlanner
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from sync.multi_agent.structured_planner import StructuredTravelPlanner

try:
    from .fixtures import EvalScenario, FixtureDeepSeekBrain, FixtureToolbox, build_scenarios
    from .metrics import aggregate_results, evaluate_plan
except ImportError:
    from fixtures import EvalScenario, FixtureDeepSeekBrain, FixtureToolbox, build_scenarios
    from metrics import aggregate_results, evaluate_plan


def run_scenario(scenario: EvalScenario) -> dict[str, Any]:
    planner = StructuredTravelPlanner("fixture://travelmind")
    toolbox = FixtureToolbox(scenario)
    brain = FixtureDeepSeekBrain(scenario)
    planner.toolbox = toolbox
    planner.deepseek_brain = brain
    started = perf_counter()
    plan = planner.run(scenario.payload)
    duration_ms = round((perf_counter() - started) * 1000)
    return evaluate_plan(plan, scenario, toolbox, brain, duration_ms)


def run_all(scenarios: list[EvalScenario] | None = None) -> dict[str, Any]:
    selected = scenarios or build_scenarios()
    results = [run_scenario(scenario) for scenario in selected]
    return {
        "suite": "travelmind-phase0-baseline",
        "version": 1,
        "scenarios": results,
        "aggregate": aggregate_results(results),
    }


def _format_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report.get("aggregate") or {}
    averages = aggregate.get("averages") or {}
    suite = str(report.get("suite") or "")
    is_phase1 = "phase1" in suite
    is_phase2 = "phase2" in suite
    is_phase3 = "phase3" in suite
    if is_phase3:
        title = "TravelMind Phase 3 预算反馈循环评测"
        intro = "本报告使用 Fake MCP 和 Fake DeepSeek fixture，未访问外部网络、`.env` 或真实供应商；预算反馈循环默认开启（TRAVELMIND_BUDGET_LOOP=on），用于观察预算调整后的指标变化。"
    elif is_phase2:
        title = "TravelMind Phase 2 候选 Contract 与排序评测"
        intro = "本报告使用 Fake MCP 和 Fake DeepSeek fixture，未访问外部网络、`.env` 或真实供应商；用于观察候选 Contract 接入后的变化。"
    elif is_phase1:
        title = "TravelMind Phase 1 约束接入评测"
        intro = "本报告使用 Fake MCP 和 Fake DeepSeek fixture，未访问外部网络、`.env` 或真实供应商；用于观察约束接入后的变化。"
    else:
        title = "TravelMind Phase 0 离线评测基线"
        intro = "本报告使用 Fake MCP 和 Fake DeepSeek fixture，未访问外部网络、`.env` 或真实供应商。指标用于建立优化前对照，不是最终发布阈值。"
    lines = [
        f"# {title}",
        "",
        intro,
        "",
        "## 汇总",
        "",
        f"- 场景数：{aggregate.get('scenario_count', 0)}",
        f"- 总调用数：{aggregate.get('total_calls', 0)}；工具 fixture 失败数：{aggregate.get('total_tool_failures', 0)}",
        f"- 规划模式：{aggregate.get('planning_modes', {})}",
        "",
        "| 指标 | 平均值 |",
        "|---|---:|",
    ]
    labels = {
        "real_place_binding_rate": "真实地点绑定率",
        "duplicate_place_rate": "重复地点率",
        "hard_constraint_satisfaction": "硬约束满足率",
        "route_over_tolerance_rate": "路线超容忍率",
        "budget_deviation": "预算偏差",
        "return_hotel_contamination_rate": "返程住宿串台率",
        "fallback_rate": "fallback 率",
    }
    for key, label in labels.items():
        lines.append(f"| {label} (`{key}`) | {_format_metric(averages.get(key))} |")
    lines.extend(["", "## 场景明细", "", "| 场景 | 绑定率 | 重复率 | 约束满足 | 超容忍 | 预算偏差 | 串台 | fallback | 调用 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for result in report.get("scenarios", []):
        metrics = result.get("metrics") or {}
        lines.append(
            "| {scenario} | {binding} | {duplicate} | {hard} | {route} | {budget} | {return_rate} | {fallback} | {calls} |".format(
                scenario=result.get("scenario"),
                binding=_format_metric(metrics.get("real_place_binding_rate")),
                duplicate=_format_metric(metrics.get("duplicate_place_rate")),
                hard=_format_metric(metrics.get("hard_constraint_satisfaction")),
                route=_format_metric(metrics.get("route_over_tolerance_rate")),
                budget=_format_metric(metrics.get("budget_deviation")),
                return_rate=_format_metric(metrics.get("return_hotel_contamination_rate")),
                fallback=_format_metric(metrics.get("fallback_rate")),
                calls=result.get("calls", {}).get("total", 0),
            )
        )
    lines.extend(
        [
            "",
            "## 解释",
            "",
            "- 绑定率只统计行程中 `activity`、`food`、`hotel` 项目，并要求真实地点标记和有效坐标同时存在。",
            "- 重复率按候选 `poi_id`、坐标或地点名归一后计算重复出现次数。",
            "- 路线超容忍率使用场景的 `maxTransferMinutes`，没有路线段时记为 0，但不代表路线已得到验证。",
            "- 预算偏差为 `abs(total-target)/target`；未设置预算时记为 `n/a`。",
            "- fallback 率统计天气、POI、酒店、规划、评审和市内路线六类可观察降级组件。",
            "- Phase 2 重点观察候选 Contract、坐标/真实地点过滤、重复处理和可解释排序；供应商结构化协议和预算反馈仍保留到后续小步。"
            if is_phase2
            else "- Phase 1 重点观察自由文本、显式 hard/soft 列表和质量审计是否进入同一条结构化链路；预算反馈和候选排序仍保留到后续阶段。"
            if is_phase1
            else "- 本阶段刻意保留当前业务行为；例如自由文本未进入 `preferences` 的场景会作为基线缺口记录，留给 Phase 1 修复。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline TravelMind Phase 0 baseline.")
    parser.add_argument("--json", dest="json_path", type=Path, default=Path("tests/evals/baseline_report.json"))
    parser.add_argument("--markdown", dest="markdown_path", type=Path, default=Path("tests/evals/baseline_report.md"))
    parser.add_argument("--suite", default="travelmind-phase0-baseline")
    args = parser.parse_args()
    report = run_all()
    report["suite"] = args.suite
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
