"""Deterministic candidate filtering and explainable ranking."""

from __future__ import annotations

import math
import re
from typing import Any

from .contracts import candidate_key, normalize_point, normalize_price_range


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        _text(candidate.get(key))
        for key in ["name", "type", "address", "description", "nearby_anchor", "cluster_name"]
    ).lower()


def _candidate_price(candidate: dict[str, Any]) -> float | None:
    for key in ["cost_estimate", "cost"]:
        try:
            value = float(candidate.get(key))
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    price_range = normalize_price_range(candidate.get("price_range"))
    if price_range:
        return (price_range["min"] + price_range["max"]) / 2
    return None


def _distance_km(first: dict[str, float] | None, second: dict[str, float] | None) -> float | None:
    if not first or not second:
        return None
    try:
        lat1 = math.radians(float(first["lat"]))
        lat2 = math.radians(float(second["lat"]))
        delta_lat = lat2 - lat1
        delta_lng = math.radians(float(second["lng"]) - float(first["lng"]))
        value = 2 * 6371.0 * math.asin(
            math.sqrt(
                math.sin(delta_lat / 2) ** 2
                + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
            )
        )
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _preference_terms(preferences: Any) -> list[str]:
    if isinstance(preferences, dict):
        values: list[Any] = [preferences.get("interests")]
        values.extend([preferences.get("softPreferences"), preferences.get("freeText")])
    elif isinstance(preferences, (list, tuple, set)):
        values = list(preferences)
    else:
        values = [preferences]

    terms: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            parts = value
        else:
            parts = re.split(r"[、,，；;\n]+", _text(value))
        for part in parts:
            term = _text(part)
            if term and term.lower() not in {item.lower() for item in terms}:
                terms.append(term)
    return terms


def _excluded_terms(value: Any) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[、,，；;\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    terms = []
    for value in values:
        term = _text(value)
        if term:
            terms.append(term.lower())
    return terms


def filter_candidates(
    candidates: list[dict[str, Any]] | None,
    *,
    expected_city: str = "",
    excluded_terms: Any = (),
    seen_keys: set[str] | None = None,
    require_coordinates: bool = False,
    require_real_place: bool = False,
    max_price: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return accepted candidates and rejected candidates with reasons."""

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen = set(seen_keys or set())
    excluded = _excluded_terms(excluded_terms)

    for index, raw in enumerate(candidates or []):
        candidate = dict(raw or {})
        reasons: list[str] = []
        name = _text(candidate.get("name") or candidate.get("title"))
        if not name:
            reasons.append("missing_name")
        candidate_city = _text(candidate.get("city"))
        if expected_city and candidate_city and candidate_city != expected_city:
            reasons.append("city_mismatch")
        if require_coordinates and not normalize_point(candidate.get("location")):
            reasons.append("missing_coordinates")
        if require_real_place and not candidate.get("is_real_place"):
            reasons.append("not_real_place")
        text = _candidate_text(candidate)
        if excluded and any(term in text for term in excluded):
            reasons.append("excluded_by_preference")
        price = _candidate_price(candidate)
        if max_price is not None and price is not None and price > max_price:
            reasons.append("over_price_limit")

        key = candidate_key(candidate)
        if key and key in seen:
            reasons.append("duplicate_candidate")
        if reasons:
            rejected.append({"candidate": candidate, "reasons": reasons, "index": index})
            continue
        if key:
            seen.add(key)
        accepted.append(candidate)

    return {"accepted": accepted, "rejected": rejected}


def _score_candidate(
    candidate: dict[str, Any],
    *,
    preferences: Any = None,
    anchor: dict[str, float] | None = None,
    max_price: float | None = None,
    weather: str = "",
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    point = normalize_point(candidate.get("location"))
    if point:
        score += 24
        reasons.append("有效坐标")
    if _text(candidate.get("address")):
        score += 10
        reasons.append("地址完整")
    try:
        rating = float(candidate.get("rating"))
    except (TypeError, ValueError):
        rating = 0
    if rating > 0:
        rating_score = min(30.0, max(0.0, rating * 6))
        score += rating_score
        reasons.append(f"评分{rating:g}")

    candidate_blob = _candidate_text(candidate)
    matched_terms = [term for term in _preference_terms(preferences) if term.lower() in candidate_blob]
    if matched_terms:
        score += min(22.0, 8.0 + len(matched_terms) * 5.0)
        reasons.append(f"匹配偏好：{'、'.join(matched_terms[:3])}")

    source_meta = candidate.get("source_meta") if isinstance(candidate.get("source_meta"), dict) else {}
    confidence = str(source_meta.get("confidence") or candidate.get("price_confidence") or "unknown")
    confidence_score = {"high": 8.0, "medium": 5.0, "low": 2.0}.get(confidence, 0.0)
    if confidence_score:
        score += confidence_score
        reasons.append("来源信息较完整")

    price = _candidate_price(candidate)
    if max_price is not None and price is not None:
        if price <= max_price:
            score += 8
            reasons.append("价格在上限内")
        else:
            score -= min(20, (price - max_price) / max(max_price, 1) * 20)
            reasons.append("价格高于偏好上限")

    if anchor and point:
        distance = _distance_km(anchor, point)
        if distance is not None:
            score += max(-18.0, 12.0 - distance * 2.0)
            reasons.append(f"距锚点约{distance:.1f}km")

    weather_text = _text(weather)
    if weather_text and re.search(r"雨|雷阵雨", weather_text) and re.search(r"公园|海边|滨水|骑行|户外", candidate_blob):
        score -= 8
        reasons.append("雨天户外适配度较低")

    return round(score, 3), reasons


def rank_candidates(
    candidates: list[dict[str, Any]] | None,
    *,
    expected_city: str = "",
    preferences: Any = None,
    excluded_terms: Any = (),
    seen_keys: set[str] | None = None,
    require_coordinates: bool = False,
    require_real_place: bool = False,
    max_price: float | None = None,
    anchor: dict[str, float] | None = None,
    weather: str = "",
    limit: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Filter, score and explain candidate selection in a stable order."""

    filtered = filter_candidates(
        candidates,
        expected_city=expected_city,
        excluded_terms=excluded_terms,
        seen_keys=seen_keys,
        require_coordinates=require_coordinates,
        require_real_place=require_real_place,
        max_price=max_price,
    )
    scored: list[tuple[int, dict[str, Any]]] = []
    for index, candidate in enumerate(filtered["accepted"]):
        score, reasons = _score_candidate(
            candidate,
            preferences=preferences,
            anchor=anchor,
            max_price=max_price,
            weather=weather,
        )
        enriched = dict(candidate)
        enriched["selection"] = {
            "score": score,
            "reasons": reasons,
            "status": "selected",
        }
        scored.append((index, enriched))
    scored.sort(key=lambda pair: (-float(pair[1]["selection"]["score"]), pair[0], candidate_key(pair[1])))

    ranked = [candidate for _, candidate in scored]
    rejected = list(filtered["rejected"])
    if limit is not None and limit >= 0 and len(ranked) > limit:
        overflow = ranked[limit:]
        ranked = ranked[:limit]
        rejected.extend(
            {
                "candidate": candidate,
                "reasons": ["rank_limit"],
                "index": index,
            }
            for index, candidate in enumerate(overflow, start=limit)
        )
    return {"selected": ranked, "rejected": rejected}
