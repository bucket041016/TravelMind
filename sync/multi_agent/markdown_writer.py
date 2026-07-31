"""TravelMind Markdown 输出。"""

from __future__ import annotations

from typing import Any, Callable

from .constants import (
    MODE_LABELS,
)


def _build_markdown(
    self,
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    weather: dict[str, str],
    weather_advice: dict[str, str],
    pois: dict[str, Any],
    budget: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
) -> str:
    recommended = MODE_LABELS.get(routes.get("recommended"), routes.get("recommended", ""))
    lines = [
        f"## {prefs['originCity']} 到 {prefs['destinationCity']} {prefs['days']} 天结构化行程方案",
        "",
        "### 跨城主交通",
        f"- 推荐：{recommended}",
    ]
    for option in routes.get("options", []):
        warning = f"；{option.get('warning')}" if option.get("warning") else ""
        lines.append(f"- {option.get('title')}：{option.get('summary')}{warning}")

    lines.extend(["", "### 酒店匹配", f"- 区域：{hotels.get('area_recommendation', '')}"])
    for hotel in hotels.get("candidates", [])[:4]:
        price = hotel.get("cost") or hotel.get("cost_estimate")
        price_text = f"；参考房价约 {round(float(price))} 元/晚" if price else ""
        if hotel.get("cost_source") == "amap_cost":
            source_text = "（高德参考消费）"
        elif hotel.get("cost_source") == "ai_price_range":
            source_text = "（AI 常识区间，需以平台实时价为准）"
        else:
            source_text = "（档位规则估算，需以平台实时价为准）"
        match_reason = hotel.get("match_reason") or ""
        lines.append(f"- {hotel['name']}：{hotel.get('description', '')}{price_text}{source_text}；{match_reason}")

    lines.extend(["", "### 天气与出行建议"])
    if weather:
        lines.extend(f"- {city}：{text}" for city, text in weather.items())
    else:
        lines.append("- 暂无天气数据。")
    for label, key in [
        ("防晒", "sun_protection"),
        ("穿衣", "clothing"),
        ("雨具", "umbrella"),
        ("行程", "schedule_note"),
    ]:
        if weather_advice.get(key):
            lines.append(f"- {label}建议：{weather_advice[key]}")

    lines.extend(["", "### 每日活动安排"])
    for day in itinerary_days:
        lines.append(f"- 第 {day['day']} 天 {day.get('date', '')}：{day['theme']}")
        for item in day.get("items", []):
            lines.append(f"  - {item['time']}｜{item['title']}｜交通：{item['transport']}｜{item['detail']}")
            segment = item.get("arrival_transport_segment")
            if segment:
                mode_label = segment.get("mode_label") or MODE_LABELS.get(segment.get("mode"), segment.get("mode", ""))
                lines.append(
                    f"    - 上一站到本站：{mode_label}｜{segment.get('duration', '耗时待核实')}｜"
                    f"{segment.get('distance', '距离待核实')}｜{segment.get('price', '价格待核实')}｜"
                    f"{segment.get('summary', '')}"
                )

    lines.extend(
        [
            "",
            "### 预算评估",
            f"- 预计总计：{budget.get('total') or '待校准'} 元；目标预算：{budget.get('target') or '未指定'} 元。",
            f"- 建议：{budget.get('advice', '')}",
            *[f"- 依据：{item}" for item in budget.get("basis", [])],
            "",
            "### 说明",
            "- 当前未接入真实航班/酒店库存供应商，不展示虚构航班号、实时房价或余票。",
            "- 高德 POI 的 cost 是参考消费；AI 价格区间只是常识估算，活动 0 元默认值也需出行前核实。",
        ]
    )
    return "\n".join(lines)

