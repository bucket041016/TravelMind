from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any, Callable
from urllib.parse import quote
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek

try:
    from mcp_tools_adapter import MCPToolAdapter
except ModuleNotFoundError:
    from sync.mcp_tools_adapter import MCPToolAdapter

from .base_agent import MCPToolbox
from .constants import (
    CITY_CENTER_COORDS,
    CITY_DISTANCE_KM,
    INTERCITY_MODE_MAP,
    LOCAL_MODE_MAP,
    MODE_LABELS,
    TIME_SLOTS,
)
from .deepseek_brain import DeepSeekPlanningBrainAgent
from .text_parser import (
    _average_range_from_text,
    _clean_description,
    _compact,
    _extract_address,
    _extract_float,
    _extract_location,
    _extract_photo_url,
    _extract_poi_type,
    _extract_prefixed_line,
    _first_valid_point,
    _format_minutes,
    _make_item_id,
    _max_temperature,
    _max_wind_level,
    _normalize_point,
    _parse_date,
    _parse_local_distance_km,
    _parse_local_duration,
    _parse_local_duration_minutes,
    _parse_money,
    _parse_numbered_section,
    _section_summary,
)
from .weather_service import (
    _build_weather,
    _build_weather_advice,
)
from .transport_service import (
    _build_intercity_transport,
    _estimate_intercity_cost,
    _extract_route_endpoint,
    _flight_strategy,
    _rail_endpoint_details,
    _recommend_intercity_mode,
    _route_endpoint_details,
    _transport_duration_label,
    _transport_price_label,
)
from .hotel_service import (
    _build_hotels,
    _clean_hotel_nearby_label,
    _default_hotel_area,
    _estimate_hotel_price_ranges,
    _hotel_area_from_candidates,
    _hotel_nearby_label,
    _hotel_nearby_landmarks,
    _hotel_reference_price,
    _is_generic_hotel_area,
    _looks_like_nearby_label,
)
from .poi_service import (
    _build_pois,
    _cluster_anchor,
    _cluster_preference_order,
    _dedupe_pois,
    _enrich_place_clusters,
    _has_real_place_signal,
    _nearest_cluster,
    _poi_key,
    _take_unused_poi,
    _take_unused_poi_for_cluster,
)
from .local_transport_service import (
    _amap_local_segment,
    _annotate_route_judgement,
    _apply_local_route_judgement,
    _build_local_transport,
    _build_local_transport_segments,
    _fallback_local_duration,
    _format_local_distance,
    _impractical_local_segment,
    _itinerary_used_place_keys,
    _judge_local_segment,
    _local_duration_minutes,
    _local_route_heading,
    _local_route_query_limit,
    _local_segment_for_mode,
    _local_segment_from_summary,
    _local_segment_price,
    _normalize_route_judgement,
    _ordered_local_modes_for_preferences,
    _point_distance_km,
    _public_item_segment,
    _replace_segment_item,
    _replacement_candidates_for_segment,
    _rule_local_segment,
    _rule_route_judgement,
    _segment_place,
    _select_local_segment_mode,
    _switch_mode_from_judgement,
    _validated_replacement_candidate,
)
from .budget_calculator import (
    _activity_count,
    _average_cost,
    _average_cost_by_source,
    _build_budget,
    _category_image_url,
    _combined_segment_source,
    _combined_source,
    _estimate_itinerary_local_transport_cost,
    _estimate_local_transport_cost,
    _itinerary_items_by_category,
    _sum_itinerary_item_cost,
)
from .itinerary_builder import (
    _build_deepseek_itinerary_days,
    _build_itinerary_days,
    _cost_metadata,
    _default_return_transfer_detail,
    _display_transport_text,
    _fallback_cost_for_category,
    _find_llm_candidate,
    _is_return_transfer_raw_item,
    _llm_suggestion_item,
    _looks_like_lodging_text,
    _materialize_llm_itinerary,
    _normalize_llm_category,
    _normalize_price_confidence,
    _normalize_return_transfer_item,
    _note_item,
    _parse_price_range,
    _planning_brain_payload,
    _price_midpoint,
    _return_transfer_location,
    _timeline_item,
)
from .quality_reviewer import (
    _apply_preference_safety_to_itinerary,
    _assign_day_primary_clusters,
    _compact_itinerary_for_review,
    _normalize_quality_review,
    _repair_plan_uses_known_candidates,
    _review_and_repair_itinerary,
    _rule_quality_review,
)
from .map_builder import (
    _build_map,
    _derive_destination_center,
    _resolve_item_map_point,
)
from .markdown_writer import (
    _build_markdown,
)
from .providers import FlightProvider, HotelProvider, RailProvider




class StructuredTravelPlanner:
    def __init__(self, mcp_server_url: str):
        self.toolbox = MCPToolbox(MCPToolAdapter(mcp_server_url))
        self.rail_provider = RailProvider()
        self.flight_provider = FlightProvider()
        self.hotel_provider = HotelProvider()
        self.deepseek_brain = DeepSeekPlanningBrainAgent()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace: list[dict[str, str]] = []
        plan_id = f"tm-{uuid4().hex[:10]}"
        prefs = self._normalize_preferences(payload)

        weather = self._record(trace, "WeatherAgent 天气与出行建议", prefs, lambda: self._build_weather(prefs))
        weather_advice = self._record(
            trace,
            "WeatherAdviceAgent 穿衣防晒建议",
            prefs,
            lambda: self._build_weather_advice(weather),
        )
        routes = self._record(trace, "IntercityTransportAgent 跨城主交通", prefs, lambda: self._build_intercity_transport(prefs))
        pois = self._record(trace, "POIAgent 景点美食", prefs, lambda: self._build_pois(prefs))
        hotels = self._record(trace, "HotelAgent 住宿匹配", prefs, lambda: self._build_hotels(prefs))
        self._enrich_place_clusters(pois, hotels)
        local_transport = self._record(trace, "LocalMobilityAgent 目的地内交通", prefs, lambda: self._build_local_transport(prefs, routes, hotels))
        llm_plan = self._record(
            trace,
            "DeepSeekPlanningBrainAgent 智能规划脑",
            prefs,
            lambda: self._build_deepseek_itinerary_days(prefs, routes, local_transport, hotels, pois, weather, weather_advice),
        )
        llm_status = str(llm_plan.get("llm_status") or "fallback") if isinstance(llm_plan, dict) else "fallback"
        if isinstance(llm_plan, dict) and llm_status == "used" and llm_plan.get("itinerary_days"):
            planning_mode = "deepseek_hybrid"
            itinerary_days = llm_plan["itinerary_days"]
        else:
            planning_mode = "rule_fallback"
            itinerary_days = self._record(
                trace,
                "DayPlannerAgent 规则降级行程",
                prefs,
                lambda: self._build_itinerary_days(prefs, routes, local_transport, hotels, pois, weather),
            )
        self._apply_preference_safety_to_itinerary(prefs, itinerary_days)
        self._assign_day_primary_clusters(itinerary_days)
        review_result = self._record(
            trace,
            "ItineraryReviewAgent 智能体检",
            prefs,
            lambda: self._review_and_repair_itinerary(prefs, routes, local_transport, hotels, pois, weather, weather_advice, itinerary_days),
        )
        if isinstance(review_result, dict):
            itinerary_days = review_result.get("itinerary_days") or itinerary_days
            quality_review = review_result.get("quality_review") or self._rule_quality_review(prefs, itinerary_days)
        else:
            quality_review = self._rule_quality_review(prefs, itinerary_days)
        local_transport = self._record(
            trace,
            "LocalMobilityAgent 目的地内路线",
            prefs,
            lambda: self._build_local_transport_segments(prefs, local_transport, itinerary_days, pois, toolbox=self.toolbox, deepseek_brain=self.deepseek_brain),
        )
        map_data = self._record(
            trace,
            "MapAgent 景点地图",
            prefs,
            lambda: self._build_map(plan_id, prefs, itinerary_days, pois, hotels),
        )
        budget = self._record(
            trace,
            "BudgetAgent 高德参考预算",
            prefs,
            lambda: self._build_budget(prefs, routes, local_transport, hotels, pois, itinerary_days),
        )
        markdown = self._record(
            trace,
            "WriterAgent 行程生成",
            prefs,
            lambda: self._build_markdown(
                prefs,
                routes,
                local_transport,
                hotels,
                weather,
                weather_advice,
                pois,
                budget,
                itinerary_days,
            ),
        )

        return {
            "plan_id": plan_id,
            "preferences": prefs,
            "intercity_transport": routes,
            "local_transport": local_transport,
            "hotels": hotels,
            "weather": weather,
            "weather_advice": weather_advice,
            "map": map_data,
            "pois": pois,
            "budget": budget,
            "itinerary_days": itinerary_days,
            "quality_review": quality_review,
            "markdown": markdown,
            "trace": trace,
            "planning_mode": planning_mode,
            "llm_status": llm_status,
        }

    def _record(
        self,
        trace: list[dict[str, str]],
        name: str,
        prefs: dict[str, Any],
        action: Callable[[], Any],
    ) -> Any:
        start = perf_counter()
        status = "success"
        try:
            result = action()
        except Exception as exc:
            status = "error"
            result = self._fallback_for_agent(name, str(exc))

        trace.append(
            {
                "name": name,
                "status": status,
                "args": f"{prefs['originCity']}->{prefs['destinationCity']}, days={prefs['days']}",
                "output": self._compact(result),
                "duration_ms": str(round((perf_counter() - start) * 1000)),
            }
        )
        return result

    @staticmethod
    def _fallback_for_agent(name: str, error: str) -> Any:
        if "天气" in name:
            return {}
        if "目的地内" in name or "LocalMobility" in name:
            return {
                "recommended_modes": [],
                "notes": [f"{name} 降级：{error}"],
                "route_context": "",
                "segments": [],
            }
        if "交通" in name:
            return {"recommended": "driving", "options": [], "notes": [f"{name} 降级：{error}"]}
        if "住宿" in name:
            return {"area_recommendation": "建议选择目的地核心商圈或地铁站附近。", "candidates": [], "provider_status": "not_configured", "notes": [error]}
        if "景点" in name:
            return {"attractions": [], "foods": [], "specialty_places": [], "raw": error}
        if "地图" in name:
            return {"provider_status": "fallback", "image_url": "", "center": None, "markers": [], "path": [], "notes": [error]}
        if "预算" in name:
            return {"total": None, "breakdown": {}, "sources": {}, "basis": [error], "text": error}
        if "每日" in name:
            return []
        return f"生成失败：{error}"

    def _normalize_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        origin = self._clean_city(payload.get("originCity") or payload.get("origin") or "广州")
        destination = self._clean_city(payload.get("destinationCity") or payload.get("destination") or "深圳")
        days = self._bounded_int(payload.get("days"), 2, 1, 14)
        travelers = self._bounded_int(payload.get("travelers"), 1, 1, 20)
        budget = self._optional_int(payload.get("budget"))
        hotel_level = str(payload.get("hotelLevel") or "舒适").strip() or "舒适"
        start_date = str(payload.get("startDate") or payload.get("travelDate") or date.today().isoformat())

        intercity_modes = self._normalize_modes(
            payload.get("intercityModes") or payload.get("transportModes"),
            INTERCITY_MODE_MAP,
            ["rail", "driving"],
        )
        local_modes = self._normalize_modes(
            payload.get("localModes"),
            LOCAL_MODE_MAP,
            ["transit", "taxi", "walking"],
        )
        preference_profile = self._normalize_preference_profile(payload.get("preferenceProfile") or {})
        interests = payload.get("interests") or ["经典景点", "美食", "地方特色"]
        if isinstance(interests, str):
            interests = [item for item in re.split(r"[、,，\s]+", interests) if item]

        return {
            "originCity": origin,
            "destinationCity": destination,
            "startDate": start_date,
            "days": days,
            "travelers": travelers,
            "budget": budget,
            "hotelLevel": hotel_level,
            "intercityModes": intercity_modes,
            "localModes": local_modes,
            "interests": list(dict.fromkeys(str(item).strip() for item in interests if str(item).strip())),
            "estimatedDistanceKm": self._estimate_distance(origin, destination),
            "preferenceProfile": preference_profile,
        }

    @staticmethod
    def _normalize_preference_profile(value: Any) -> dict[str, Any]:
        raw = value if isinstance(value, dict) else {}
        pace = str(raw.get("pace") or "标准").strip()
        if pace not in {"轻松", "标准", "紧凑"}:
            pace = "标准"
        try:
            max_transfer = int(raw.get("maxTransferMinutes") or 45)
        except (TypeError, ValueError):
            max_transfer = 45
        max_transfer = max(20, min(max_transfer, 90))
        hotel_strategy = str(raw.get("hotelStrategy") or "近地铁枢纽").strip()
        if hotel_strategy not in {"近景点", "近地铁枢纽", "近商圈"}:
            hotel_strategy = "近地铁枢纽"
        learned = raw.get("learnedHints") if isinstance(raw.get("learnedHints"), list) else []
        learned_hints = [
            str(item).strip()
            for item in learned
            if str(item).strip()
        ][:12]
        return {
            "pace": pace,
            "maxTransferMinutes": max_transfer,
            "hotelStrategy": hotel_strategy,
            "learnedHints": list(dict.fromkeys(learned_hints)),
        }

    @staticmethod
    def _clean_city(value: Any) -> str:
        text = re.sub(r"\s+", "", str(value or ""))
        return text.removesuffix("市区").removesuffix("市") or "深圳"

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(number, maximum))

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _normalize_modes(value: Any, mapping: dict[str, str], defaults: list[str]) -> list[str]:
        if not value:
            return defaults
        if isinstance(value, str):
            items = [item for item in re.split(r"[、,，\s]+", value) if item]
        else:
            items = list(value)
        modes = []
        for item in items:
            text = str(item).strip()
            mode = mapping.get(text)
            if mode:
                modes.append(mode)
        return list(dict.fromkeys(modes)) or defaults

    @staticmethod
    def _estimate_distance(origin: str, destination: str) -> int | None:
        return CITY_DISTANCE_KM.get((origin, destination)) or CITY_DISTANCE_KM.get((destination, origin))

    # ------------------------------------------------------------------
    # 向后兼容：将提取到外部模块的函数重新绑定为类属性，
    # 确保 self.method() 和 StructuredTravelPlanner.method() 都能工作。
    # ------------------------------------------------------------------

    # text_parser
    _average_range_from_text = staticmethod(_average_range_from_text)
    _clean_description = staticmethod(_clean_description)
    _compact = staticmethod(_compact)
    _extract_address = staticmethod(_extract_address)
    _extract_float = staticmethod(_extract_float)
    _extract_location = staticmethod(_extract_location)
    _extract_photo_url = staticmethod(_extract_photo_url)
    _extract_poi_type = staticmethod(_extract_poi_type)
    _extract_prefixed_line = staticmethod(_extract_prefixed_line)
    _first_valid_point = staticmethod(_first_valid_point)
    _format_minutes = staticmethod(_format_minutes)
    _make_item_id = staticmethod(_make_item_id)
    _max_temperature = staticmethod(_max_temperature)
    _max_wind_level = staticmethod(_max_wind_level)
    _normalize_point = staticmethod(_normalize_point)
    _parse_date = staticmethod(_parse_date)
    _parse_local_distance_km = staticmethod(_parse_local_distance_km)
    _parse_local_duration = staticmethod(_parse_local_duration)
    _parse_local_duration_minutes = staticmethod(_parse_local_duration_minutes)
    _parse_money = staticmethod(_parse_money)
    _parse_numbered_section = staticmethod(_parse_numbered_section)
    _section_summary = staticmethod(_section_summary)

    # weather_service
    _build_weather = _build_weather
    _build_weather_advice = staticmethod(_build_weather_advice)

    # transport_service
    _build_intercity_transport = _build_intercity_transport
    _estimate_intercity_cost = staticmethod(_estimate_intercity_cost)
    _extract_route_endpoint = staticmethod(_extract_route_endpoint)
    _flight_strategy = staticmethod(_flight_strategy)
    _rail_endpoint_details = staticmethod(_rail_endpoint_details)
    _recommend_intercity_mode = staticmethod(_recommend_intercity_mode)
    _route_endpoint_details = staticmethod(_route_endpoint_details)
    _transport_duration_label = staticmethod(_transport_duration_label)
    _transport_price_label = staticmethod(_transport_price_label)

    # hotel_service
    _build_hotels = _build_hotels
    _clean_hotel_nearby_label = staticmethod(_clean_hotel_nearby_label)
    _default_hotel_area = staticmethod(_default_hotel_area)
    _estimate_hotel_price_ranges = staticmethod(_estimate_hotel_price_ranges)
    _hotel_area_from_candidates = staticmethod(_hotel_area_from_candidates)
    _hotel_nearby_label = staticmethod(_hotel_nearby_label)
    _hotel_nearby_landmarks = staticmethod(_hotel_nearby_landmarks)
    _hotel_reference_price = staticmethod(_hotel_reference_price)
    _is_generic_hotel_area = staticmethod(_is_generic_hotel_area)
    _looks_like_nearby_label = staticmethod(_looks_like_nearby_label)

    # poi_service
    _build_pois = _build_pois
    _cluster_anchor = staticmethod(_cluster_anchor)
    _cluster_preference_order = staticmethod(_cluster_preference_order)
    _dedupe_pois = staticmethod(_dedupe_pois)
    _enrich_place_clusters = staticmethod(_enrich_place_clusters)
    _has_real_place_signal = staticmethod(_has_real_place_signal)
    _nearest_cluster = staticmethod(_nearest_cluster)
    _poi_key = staticmethod(_poi_key)
    _take_unused_poi = staticmethod(_take_unused_poi)
    _take_unused_poi_for_cluster = staticmethod(_take_unused_poi_for_cluster)

    # local_transport_service
    _amap_local_segment = staticmethod(_amap_local_segment)
    _annotate_route_judgement = staticmethod(_annotate_route_judgement)
    _apply_local_route_judgement = staticmethod(_apply_local_route_judgement)
    _build_local_transport = staticmethod(_build_local_transport)
    _build_local_transport_segments = staticmethod(_build_local_transport_segments)
    _fallback_local_duration = staticmethod(_fallback_local_duration)
    _format_local_distance = staticmethod(_format_local_distance)
    _impractical_local_segment = staticmethod(_impractical_local_segment)
    _itinerary_used_place_keys = staticmethod(_itinerary_used_place_keys)
    _judge_local_segment = staticmethod(_judge_local_segment)
    _local_duration_minutes = staticmethod(_local_duration_minutes)
    _local_route_heading = staticmethod(_local_route_heading)
    _local_route_query_limit = staticmethod(_local_route_query_limit)
    _local_segment_for_mode = staticmethod(_local_segment_for_mode)
    _local_segment_from_summary = staticmethod(_local_segment_from_summary)
    _local_segment_price = staticmethod(_local_segment_price)
    _normalize_route_judgement = staticmethod(_normalize_route_judgement)
    _ordered_local_modes_for_preferences = staticmethod(_ordered_local_modes_for_preferences)
    _point_distance_km = staticmethod(_point_distance_km)
    _public_item_segment = staticmethod(_public_item_segment)
    _replace_segment_item = staticmethod(_replace_segment_item)
    _replacement_candidates_for_segment = staticmethod(_replacement_candidates_for_segment)
    _rule_local_segment = staticmethod(_rule_local_segment)
    _rule_route_judgement = staticmethod(_rule_route_judgement)
    _segment_place = staticmethod(_segment_place)
    _select_local_segment_mode = staticmethod(_select_local_segment_mode)
    _switch_mode_from_judgement = staticmethod(_switch_mode_from_judgement)
    _validated_replacement_candidate = staticmethod(_validated_replacement_candidate)

    # budget_calculator
    _activity_count = staticmethod(_activity_count)
    _average_cost = staticmethod(_average_cost)
    _average_cost_by_source = staticmethod(_average_cost_by_source)
    _build_budget = staticmethod(_build_budget)
    _category_image_url = staticmethod(_category_image_url)
    _combined_segment_source = staticmethod(_combined_segment_source)
    _combined_source = staticmethod(_combined_source)
    _estimate_itinerary_local_transport_cost = staticmethod(_estimate_itinerary_local_transport_cost)
    _estimate_local_transport_cost = staticmethod(_estimate_local_transport_cost)
    _itinerary_items_by_category = staticmethod(_itinerary_items_by_category)
    _sum_itinerary_item_cost = staticmethod(_sum_itinerary_item_cost)

    # itinerary_builder
    _build_deepseek_itinerary_days = _build_deepseek_itinerary_days
    _build_itinerary_days = staticmethod(_build_itinerary_days)
    _cost_metadata = staticmethod(_cost_metadata)
    _default_return_transfer_detail = staticmethod(_default_return_transfer_detail)
    _display_transport_text = staticmethod(_display_transport_text)
    _fallback_cost_for_category = staticmethod(_fallback_cost_for_category)
    _find_llm_candidate = staticmethod(_find_llm_candidate)
    _is_return_transfer_raw_item = staticmethod(_is_return_transfer_raw_item)
    _llm_suggestion_item = staticmethod(_llm_suggestion_item)
    _looks_like_lodging_text = staticmethod(_looks_like_lodging_text)
    _materialize_llm_itinerary = staticmethod(_materialize_llm_itinerary)
    _normalize_llm_category = staticmethod(_normalize_llm_category)
    _normalize_price_confidence = staticmethod(_normalize_price_confidence)
    _normalize_return_transfer_item = staticmethod(_normalize_return_transfer_item)
    _note_item = staticmethod(_note_item)
    _parse_price_range = staticmethod(_parse_price_range)
    _planning_brain_payload = staticmethod(_planning_brain_payload)
    _price_midpoint = staticmethod(_price_midpoint)
    _return_transfer_location = staticmethod(_return_transfer_location)
    _timeline_item = staticmethod(_timeline_item)

    # quality_reviewer
    _apply_preference_safety_to_itinerary = staticmethod(_apply_preference_safety_to_itinerary)
    _assign_day_primary_clusters = staticmethod(_assign_day_primary_clusters)
    _compact_itinerary_for_review = staticmethod(_compact_itinerary_for_review)
    _normalize_quality_review = staticmethod(_normalize_quality_review)
    _repair_plan_uses_known_candidates = staticmethod(_repair_plan_uses_known_candidates)
    _review_and_repair_itinerary = _review_and_repair_itinerary
    _rule_quality_review = staticmethod(_rule_quality_review)

    # map_builder
    _build_map = staticmethod(_build_map)
    _derive_destination_center = staticmethod(_derive_destination_center)
    _resolve_item_map_point = staticmethod(_resolve_item_map_point)

    # markdown_writer
    _build_markdown = staticmethod(_build_markdown)



