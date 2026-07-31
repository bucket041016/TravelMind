"""TravelMind 文本解析工具函数。

从 structured_planner.py 中提取的纯静态工具方法，
用于解析高德 API 返回的文本、提取结构化数据等。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def _extract_prefixed_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith(prefix):
            return clean.split("：", 1)[-1].strip()
    return ""

def _parse_local_distance_km(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*km", text, re.I)
    if match:
        return float(match.group(1))
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*m\b", text, re.I)
    if match:
        return float(match.group(1)) / 1000
    return None

def _parse_local_duration(text: str) -> str:
    match = re.search(r"(\d+\s*小时\s*\d+\s*分钟|\d+\s*小时|\d+\s*分钟)", text)
    return match.group(1).replace(" ", "") if match else ""

def _parse_local_duration_minutes(text: str) -> int:
    clean = str(text or "").replace(" ", "")
    match = re.search(r"(?:(\d+)小时)?(?:(\d+)分钟)?", clean)
    if not match or not (match.group(1) or match.group(2)):
        return 0
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)

def _format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"

def _average_range_from_text(text: str) -> float | None:
    match = re.search(r"约\s*([0-9.]+)\s*[~\-～]\s*([0-9.]+)\s*元", text)
    if match:
        return (float(match.group(1)) + float(match.group(2))) / 2
    match = re.search(r"约\s*([0-9.]+)\s*元", text)
    if match:
        return float(match.group(1))
    return None

def _max_temperature(text: str) -> int | None:
    values = []
    for low, high in re.findall(r"(-?\d+)\s*[~\-～]\s*(-?\d+)\s*°?\s*C", text, re.I):
        values.extend([int(low), int(high)])
    return max(values) if values else None

def _max_wind_level(text: str) -> int | None:
    values = []
    for low, high in re.findall(r"(\d+)\s*[~\-～]\s*(\d+)\s*级", text):
        values.extend([int(low), int(high)])
    for single in re.findall(r"(?<![\d~\-～])([4-9])\s*级", text):
        values.append(int(single))
    return max(values) if values else None

def _parse_money(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None

def _normalize_point(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        lng = float(value.get("lng"))
        lat = float(value.get("lat"))
    except (TypeError, ValueError):
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return {"lng": lng, "lat": lat}

def _first_valid_point(items: list[dict[str, Any]]) -> dict[str, float] | None:
    for item in items or []:
        point = _normalize_point(item.get("location") or item.get("location_point"))
        if point:
            return point
    return None

def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None

def _section_summary(text: str, heading: str) -> str:
    if not text:
        return ""
    pattern = rf"【{re.escape(heading)}】(?P<body>.*?)(?:\n【|\n出行建议：|\Z)"
    match = re.search(pattern, text, re.S)
    body = match.group("body") if match else ""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return " ".join(lines[:3])

def _parse_numbered_section(text: str, heading: str) -> list[dict[str, Any]]:
    if not text:
        return []
    pattern = rf"【{re.escape(heading)}】(?P<body>.*?)(?:\n【|\n出行提示：|\Z)"
    match = re.search(pattern, text, re.S)
    body = match.group("body") if match else ""
    items = []
    for line in body.splitlines():
        clean = line.strip()
        match_item = re.match(r"^\d+\.\s*(.+)$", clean)
        if not match_item:
            continue
        value = match_item.group(1).strip()
        name = re.split(r"[（(；:：]", value, maxsplit=1)[0].strip()
        description = value[len(name):].strip(" ：；")
        cost = _extract_float(value, r"人均约\s*([0-9.]+)\s*元")
        cost_estimate = round(float(cost)) if cost else 0
        item = {
            "id": _make_item_id(heading, len(items) + 1, name),
            "name": name,
            "description": _clean_description(description or value),
            "rating": _extract_float(value, r"评分\s*([0-9.]+)"),
            "cost": cost,
            "cost_estimate": cost_estimate,
            "cost_source": "amap_cost" if cost else "unknown_price",
            "price_range": (
                {"min": cost_estimate, "max": cost_estimate, "currency": "CNY", "unit": "person"}
                if cost
                else None
            ),
            "price_confidence": "high" if cost else "unknown",
            "cost_note": (
                "高德 POI 参考消费，不代表实时票价、库存或可预订价格。"
                if cost
                else "高德未返回参考消费，价格待核实。"
            ),
            "address": _extract_address(value),
            "type": _extract_poi_type(value),
            "location": _extract_location(value),
            "photo_url": _extract_photo_url(value),
            "raw": value,
        }
        items.append(item)
    return items

def _make_item_id(prefix: str, index: int, name: str) -> str:
    safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", name).strip("-")
    safe_prefix = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", prefix).strip("-")
    return f"{safe_prefix or 'poi'}-{index}-{safe_name or 'item'}"

def _clean_description(text: str) -> str:
    clean = re.sub(r"；坐标：[^；]+", "", text)
    clean = re.sub(r"；图片：\S+", "", clean)
    return clean.strip(" ：；") or "暂无补充信息"

def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None

def _extract_address(text: str) -> str:
    match = re.search(r"地址：(.+?)(?:；坐标：|；图片：|$)", text)
    return match.group(1).strip() if match else ""

def _extract_location(text: str) -> dict[str, float] | None:
    match = re.search(r"坐标：\s*([0-9.-]+)\s*,\s*([0-9.-]+)", text)
    if not match:
        return None
    try:
        return {"lng": float(match.group(1)), "lat": float(match.group(2))}
    except ValueError:
        return None

def _extract_photo_url(text: str) -> str:
    match = re.search(r"图片：(\S+)", text)
    return match.group(1).strip() if match else ""

def _extract_poi_type(text: str) -> str:
    match = re.search(r"[（(](.*?)[）)]", text)
    if not match:
        return ""
    parts = [part.strip() for part in re.split(r"，|,", match.group(1)) if part.strip()]
    for part in reversed(parts):
        if not part.startswith("评分") and not part.startswith("人均约"):
            return part
    return ""

def _compact(value: Any, limit: int = 900) -> str:
    text = str(value).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."

