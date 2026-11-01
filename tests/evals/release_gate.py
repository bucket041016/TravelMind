"""发布质量门（Phase 5.6）：当前评测聚合 vs 仓库内参照报告，关键指标回退即阻止发布。

设计要点：
- compare() 是纯函数：不触 DB、不触网络、不依赖历史文件存在（参照由调用方加载）；
- 默认参照物是仓库内已提交的 tests/evals/phase3_report.json（干净 clone 可复现）；
- total_calls 不进闸门（调用数是成本不是质量）；
- 指标缺失/为 None 时跳过该项（无法比较不视为回退）；
- CLI 退出码：0 通过 / 1 回退 / 2 参照或当前数据不可用。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_REFERENCE = Path(__file__).resolve().parent / "phase3_report.json"
ZERO_REFERENCE_EPSILON = 0.01

# 指标 -> (方向, 判据)。direction: "lower_is_better" | "higher_is_better"
# threshold_kind: "relative"（相对变化率）| "absolute"（绝对差）
METRIC_RULES: dict[str, dict[str, Any]] = {
    "budget_deviation": {"direction": "lower_is_better", "threshold_kind": "relative", "threshold": 0.10},
    "real_place_binding_rate": {"direction": "higher_is_better", "threshold_kind": "absolute", "threshold": 0.05},
    "hard_constraint_satisfaction": {"direction": "higher_is_better", "threshold_kind": "absolute", "threshold": 0.05},
    "fallback_rate": {"direction": "lower_is_better", "threshold_kind": "absolute", "threshold": 0.10},
}


def _averages(aggregate: dict[str, Any]) -> dict[str, Any]:
    return aggregate.get("averages") or {}


def compare(current: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """比较两份聚合（含 averages），返回 {passed, regressions, improvements, skipped}。"""
    current_values = _averages(current)
    reference_values = _averages(reference)
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    skipped: list[str] = []

    for metric, rule in METRIC_RULES.items():
        cur = current_values.get(metric)
        ref = reference_values.get(metric)
        if not isinstance(cur, (int, float)) or not isinstance(ref, (int, float)):
            skipped.append(metric)
            continue
        delta = float(cur) - float(ref)
        if rule["threshold_kind"] == "relative" and abs(float(ref)) > 1e-9:
            exceeded = (abs(delta) / abs(float(ref))) > rule["threshold"]
        elif rule["threshold_kind"] == "relative":
            # 参照为 0：相对变化率无定义，退化为绝对 epsilon 判定。
            exceeded = abs(delta) > ZERO_REFERENCE_EPSILON
        else:
            exceeded = abs(delta) > rule["threshold"]

        worsened = delta > 0 if rule["direction"] == "lower_is_better" else delta < 0
        entry = {"metric": metric, "before": round(float(ref), 4), "after": round(float(cur), 4), "delta": round(delta, 4)}
        if worsened and exceeded:
            regressions.append(entry)
        elif not worsened and abs(delta) > 1e-9:
            improvements.append(entry)

    return {
        "passed": not regressions,
        "regressions": regressions,
        "improvements": improvements,
        "skipped": skipped,
    }


def _load_aggregate(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    aggregate = report.get("aggregate") if isinstance(report, dict) else None
    if not isinstance(aggregate, dict):
        raise ValueError(f"{path} 不含 aggregate 段")
    return aggregate


def render_report(result: dict[str, Any], reference_path: Path) -> str:
    lines = [f"# 发布质量门（参照：{reference_path.name}）", ""]
    if result["passed"]:
        lines.append("结论：通过——关键指标无回退。")
    else:
        lines.append("结论：**未通过**——以下指标回退超过阈值：")
    for item in result["regressions"]:
        lines.append(f"- {item['metric']}: {item['before']} → {item['after']}（Δ {item['delta']:+}）")
    if result["improvements"]:
        lines.append("")
        lines.append("改善项：")
        for item in result["improvements"]:
            lines.append(f"- {item['metric']}: {item['before']} → {item['after']}（Δ {item['delta']:+}）")
    if result["skipped"]:
        lines.append("")
        lines.append(f"跳过（数据缺失）：{', '.join(result['skipped'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TravelMind release quality gate.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE, help="参照报告 JSON（默认 phase3_report.json）")
    parser.add_argument("--current", type=Path, default=None, help="当前报告 JSON；缺省时现场运行离线评测")
    args = parser.parse_args(argv)

    try:
        reference = _load_aggregate(args.reference)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"参照报告不可用：{exc}")
        return 2

    if args.current:
        try:
            current = _load_aggregate(args.current)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"当前报告不可用：{exc}")
            return 2
    else:
        try:
            from .run_baseline import run_all
        except ImportError:  # pragma: no cover - 直接脚本执行
            from run_baseline import run_all
        current = run_all().get("aggregate") or {}

    result = compare(current, reference)
    print(render_report(result, args.reference))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
