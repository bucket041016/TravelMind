"""TravelMind 酒店匹配与价格估算。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable
import re

from .text_parser import (
    _extract_prefixed_line,
    _parse_numbered_section,
)
from .fact_normalizer import normalize_place_candidate
from .candidate_ranker import rank_candidates

def _parse_price_range(value) -> dict | None:
    import re as _re
    text = str(value or "").strip()
    if not text:
        return None
    m = _re.search(r"(\d+(?:\.\d+)?)\s*[-~\u2014\u2013]\s*(\d+(?:\.\d+)?)", text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return {"min": round(min(lo, hi)), "max": round(max(lo, hi)), "currency": "CNY"}
    m2 = _re.search(r"(\d+(?:\.\d+)?)", text)
    if m2:
        val = round(float(m2.group(1)))
        return {"min": val, "max": val, "currency": "CNY"}
    return None


def _price_midpoint(price_range: dict | None) -> int | None:
    if not isinstance(price_range, dict):
        return None
    lo = price_range.get("min")
    hi = price_range.get("max")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        return round((lo + hi) / 2)
    return None


def _normalize_price_confidence(value, default: str = "unknown") -> str:
    text = str(value or default).strip().lower()
    return text if text in {"high", "medium", "low", "unknown"} else default


def _build_hotels(self, prefs: dict[str, Any]) -> dict[str, Any]:
    provider_message = self.hotel_provider.message()
    raw = self.toolbox.call(
        "search_hotels",
        city=prefs["destinationCity"],
        hotel_level=prefs["hotelLevel"],
        limit=6,
    )
    candidates = _parse_numbered_section(raw, "酒店候选")
    fallback_price = _hotel_reference_price(prefs["hotelLevel"])
    ai_price_estimates = _estimate_hotel_price_ranges(prefs, candidates, deepseek_brain=self.deepseek_brain)
    for candidate in candidates:
        if isinstance(candidate.get("cost"), (int, float)) and candidate["cost"] > 0:
            candidate["cost_estimate"] = round(float(candidate["cost"]))
            candidate["cost_source"] = "amap_cost"
            candidate["price_range"] = {
                "min": candidate["cost_estimate"],
                "max": candidate["cost_estimate"],
                "currency": "CNY",
                "unit": "night",
            }
            candidate["price_confidence"] = "high"
            candidate["cost_note"] = "高德酒店 POI 参考消费，不代表实时房态或可预订价。"
        elif candidate.get("id") in ai_price_estimates:
            estimate = ai_price_estimates[candidate["id"]]
            price_range = estimate["price_range"]
            candidate["cost_estimate"] = _price_midpoint(price_range) or fallback_price
            candidate["cost_source"] = "ai_price_range"
            candidate["price_range"] = price_range
            candidate["price_confidence"] = estimate["price_confidence"]
            candidate["cost_note"] = estimate["price_note"]
        else:
            candidate["cost_estimate"] = fallback_price
            candidate["cost_source"] = "category_rule"
            candidate["price_range"] = {
                "min": round(fallback_price * 0.8),
                "max": round(fallback_price * 1.25),
                "currency": "CNY",
                "unit": "night",
            }
            candidate["price_confidence"] = "low"
            candidate["cost_note"] = f"{prefs['hotelLevel']}档住宿规则估算，需以酒店平台实时房价和房态为准。"
        candidate["match_reason"] = (
            f"{_hotel_nearby_label(candidate)}，{prefs['hotelLevel']}档住宿，"
            "便于换乘、晚间返程和寄存行李。"
        )
    status = "amap_fallback" if "provider_status=amap_fallback" in raw else self.hotel_provider.status()
    if status == "live":
        status = "amap_fallback"
    area_recommendation = _extract_prefixed_line(raw, "住宿区域建议")
    if _is_generic_hotel_area(area_recommendation):
        area_recommendation = _hotel_area_from_candidates(prefs, candidates)
    return {
        "area_recommendation": area_recommendation or _hotel_area_from_candidates(prefs, candidates),
        "candidates": candidates,
        "provider_status": status,
        "notes": [provider_message, "酒店候选来自 POI 搜索，不代表实时房态或可预订价格。"],
        "raw": raw,
    }


def _normalize_and_rank_hotels(
    hotels: dict[str, Any],
    prefs: dict[str, Any],
) -> None:
    """对酒店候选执行事实归一化和偏好排序（原地修改 hotels）。"""
    candidates = hotels.get("candidates")
    if not candidates:
        return
    city = prefs.get("destinationCity", "")
    budget = prefs.get("budget")
    max_price = float(budget) / max(prefs.get("days", 1), 1) if budget else None
    normalized = [
        normalize_place_candidate(
            c,
            city=city,
            category="hotel",
            source=str(c.get("cost_source") or "hotel_poi"),
        )
        for c in candidates
    ]
    ranked = rank_candidates(
        normalized,
        expected_city=city,
        preferences={"interests": [prefs.get("hotelLevel", "")]},
        max_price=max_price,
    )
    selected = ranked.get("selected")
    if selected:
        hotels["candidates"] = selected
    else:
        # 价格上限等硬过滤可能把候选整组清空（如低预算场景），
        # 此时回退"仅因价格超限"被拒的真实候选并显式标记，避免酒店组件整体降级。
        fallback = [
            item["candidate"]
            for item in ranked.get("rejected", [])
            if item.get("reasons") == ["over_price_limit"]
        ]
        fallback = fallback or normalized
        for candidate in fallback:
            selection = candidate.setdefault("selection", {})
            selection["status"] = "over_budget"
            selection.setdefault("reasons", []).append("over_price_limit")
        hotels["candidates"] = fallback

def _estimate_hotel_price_ranges(
    prefs: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    deepseek_brain=None,
) -> dict[str, dict[str, Any]]:
    missing = [
        {
            "candidate_id": item.get("id"),
            "name": item.get("name"),
            "address": item.get("address", ""),
            "type": item.get("type", ""),
            "description": str(item.get("description") or "")[:160],
        }
        for item in candidates
        if item.get("id") and not (isinstance(item.get("cost"), (int, float)) and item["cost"] > 0)
    ]
    if not missing:
        return {}

    payload = {
        "city": prefs["destinationCity"],
        "hotel_level": prefs["hotelLevel"],
        "start_date": prefs.get("startDate", ""),
        "candidates": missing[:6],
        "constraints": [
            "只输出常识估算区间，不是实时房价",
            "价格单位为人民币/晚",
            "必须提醒以酒店平台实时房价和房态为准",
        ],
    }
    if deepseek_brain is None:
        return {}
    result = deepseek_brain.estimate_hotel_prices(payload)
    if result.get("llm_status") != "used":
        return {}

    estimates: dict[str, dict[str, Any]] = {}
    for raw in result.get("prices", []):
        if not isinstance(raw, dict):
            continue
        candidate_id = str(raw.get("candidate_id") or "").strip()
        price_range = _parse_price_range(raw.get("estimated_price_range"))
        if not candidate_id or not price_range:
            continue
        price_range = {**price_range, "unit": "night"}
        note = str(raw.get("price_note") or "").strip()
        if "实时" not in note and "房态" not in note:
            note = f"{note} 需以酒店平台实时房价和房态为准。".strip()
        estimates[candidate_id] = {
            "price_range": price_range,
            "price_confidence": _normalize_price_confidence(raw.get("price_confidence"), "low"),
            "price_note": note or "AI 常识估算，需以酒店平台实时房价和房态为准。",
        }
    return estimates

def _default_hotel_area(prefs: dict[str, Any]) -> str:
    return f"建议住在{prefs['destinationCity']}核心商圈、地铁枢纽或第一天重点景点附近，减少换乘和搬运行李。"

def _is_generic_hotel_area(value: Any) -> bool:
    text = str(value or "")
    generic_markers = ["核心商圈", "地铁枢纽", "第一天重点景点", "交通枢纽"]
    return any(marker in text for marker in generic_markers)

def _hotel_area_from_candidates(prefs: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    landmarks: list[str] = []
    for candidate in candidates[:4]:
        for landmark in _hotel_nearby_landmarks(candidate):
            if landmark not in landmarks:
                landmarks.append(landmark)
            if len(landmarks) >= 3:
                break
        if len(landmarks) >= 3:
            break
    if landmarks:
        return f"建议优先住在{'、'.join(landmarks)}周边，减少换乘和搬运行李。"
    return _default_hotel_area(prefs)

def _hotel_nearby_label(candidate: dict[str, Any]) -> str:
    landmarks = _hotel_nearby_landmarks(candidate)
    if landmarks:
        return f"近{'/'.join(landmarks[:2])}"
    address = str(candidate.get("address") or "").strip()
    if address:
        return f"位于{address}"
    return "位于候选酒店所在片区"

def _hotel_nearby_landmarks(candidate: dict[str, Any]) -> list[str]:
    labels: list[str] = []

    def add(value: Any) -> None:
        label = _clean_hotel_nearby_label(value)
        if label and label not in labels and _looks_like_nearby_label(label):
            labels.append(label)

    address = str(candidate.get("address") or "")
    for piece in re.findall(r"[（(]([^（）()]+)[）)]", address):
        add(piece)

    for source in [candidate.get("type"), candidate.get("name")]:
        text = _clean_hotel_nearby_label(source)
        if not text:
            continue
        pattern = (
            r"([\u4e00-\u9fffA-Za-z0-9]+?(?:国际会展中心|会展中心|地铁站|"
            r"火车站|高铁站|北站|东站|西站|南站|机场|口岸|码头|公园|广场|"
            r"景区|美术馆|博物馆|购物中心|商业中心))"
        )
        for landmark in re.findall(pattern, text):
            add(landmark)

    if any(marker in address for marker in ["旁", "附近", "对面"]):
        piece = re.split(r"[，,；;]", address)[-1]
        if "号" in piece:
            piece = piece.rsplit("号", 1)[-1]
        add(piece)

    return labels[:3]

def _clean_hotel_nearby_label(value: Any) -> str:
    text = str(value or "").strip(" \t\r\n，,；;。()（）")
    text = re.sub(r"^(近|靠近|毗邻|位于|距离)", "", text)
    text = re.sub(r"(酒店|宾馆|公寓)?店$", "", text)
    return text.strip(" \t\r\n，,；;。()（）")

def _looks_like_nearby_label(value: str) -> bool:
    concrete_markers = [
        "地铁",
        "站",
        "会展",
        "机场",
        "口岸",
        "码头",
        "公园",
        "广场",
        "景区",
        "美术馆",
        "博物馆",
        "购物中心",
        "商业中心",
        "花园",
        "旁",
        "附近",
        "对面",
        "步行",
    ]
    generic_labels = {"高端酒店", "舒适酒店", "经济酒店", "酒店", "宾馆", "公寓"}
    return value not in generic_labels and any(marker in value for marker in concrete_markers)

def _hotel_reference_price(hotel_level: str) -> int:
    return {"经济": 220, "舒适": 380, "高端": 680}.get(hotel_level, 380)

