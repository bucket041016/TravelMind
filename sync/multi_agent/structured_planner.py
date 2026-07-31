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
from .candidate_ranker import rank_candidates
from .contracts import candidate_key
from .fact_normalizer import normalize_place_candidates
from .providers import FlightProvider, HotelProvider, RailProvider


CITY_DISTANCE_KM = {
    ("广州", "深圳"): 137,
    ("福州", "厦门"): 255,
    ("北京", "天津"): 120,
    ("北京", "三亚"): 3000,
    ("上海", "成都"): 1950,
    ("北京", "上海"): 1200,
    ("广州", "北京"): 2100,
    ("深圳", "杭州"): 1250,
}

CITY_CENTER_COORDS = {
    "北京": {"lng": 116.4074, "lat": 39.9042},
    "上海": {"lng": 121.4737, "lat": 31.2304},
    "广州": {"lng": 113.2644, "lat": 23.1291},
    "深圳": {"lng": 114.0579, "lat": 22.5431},
    "杭州": {"lng": 120.1551, "lat": 30.2741},
    "南京": {"lng": 118.7969, "lat": 32.0603},
    "成都": {"lng": 104.0665, "lat": 30.5723},
    "重庆": {"lng": 106.5516, "lat": 29.5630},
    "西安": {"lng": 108.9398, "lat": 34.3416},
    "武汉": {"lng": 114.3054, "lat": 30.5931},
    "福州": {"lng": 119.2965, "lat": 26.0745},
    "厦门": {"lng": 118.0894, "lat": 24.4798},
    "三亚": {"lng": 109.5119, "lat": 18.2528},
}

INTERCITY_MODE_MAP = {
    "高铁": "rail",
    "高铁/动车/城际": "rail",
    "高铁/城际": "rail",
    "动车": "rail",
    "城际": "rail",
    "飞机": "flight",
    "飞机航班": "flight",
    "航班": "flight",
    "自驾": "driving",
    "驾车": "driving",
}

LOCAL_MODE_MAP = {
    "自驾": "driving",
    "驾车": "driving",
    "步行": "walking",
    "步行接驳": "walking",
    "骑行": "bicycling",
    "骑行接驳": "bicycling",
    "公共交通": "transit",
    "公交/地铁": "transit",
    "地铁公交": "transit",
    "打车": "taxi",
}

MODE_LABELS = {
    "rail": "高铁/动车/城际",
    "flight": "飞机航班",
    "driving": "自驾",
    "transit": "公共交通",
    "walking": "步行",
    "bicycling": "骑行",
    "taxi": "打车",
}

TIME_SLOTS = ["上午", "中午", "下午", "晚上", "夜间"]


class DeepSeekPlanningBrainAgent:
    """Use DeepSeek as the planning brain while keeping AMap as the fact source."""

    def __init__(self) -> None:
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout = float(os.getenv("DEEPSEEK_PLAN_TIMEOUT_SECONDS", "35"))
        self.model = None
        if self.api_key:
            self.model = ChatDeepSeek(
                model=self.model_name,
                temperature=0.35,
                timeout=self.timeout,
                max_retries=1,
                max_tokens=3500,
            )

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return {"llm_status": "unavailable", "reason": "DEEPSEEK_API_KEY missing", "plan": None}

        system_prompt = (
            "你是 TravelMind 的智能行程规划脑。你必须基于给定的高德候选 POI、酒店、交通、天气和用户偏好规划行程。"
            "真实地点必须引用候选中的 candidate_id；不要编造真实景点、餐厅、酒店、航班号、票价或库存。"
            "如果需要加入更人性化的体验建议但没有真实 POI，可设置 is_suggestion=true，并写清楚 validation_note。"
            "只输出 JSON，不要 Markdown，不要解释。"
        )
        user_prompt = (
            "请生成结构化行程 JSON，schema 如下：\n"
            "{\n"
            '  "days": [\n'
            '    {"day": 1, "theme": "", "items": [\n'
            '      {"title": "", "candidate_id": "", "category": "activity|food|hotel|transfer|note", '
            '"transport": "", "duration": "", "detail": "", "is_suggestion": false, "validation_note": "", '
            '"estimated_price_range": "", "price_confidence": "high|medium|low|unknown", "price_note": ""}\n'
            "    ]}\n"
            "  ]\n"
            "}\n"
            "要求：每天 3-5 个 item；优先选择真实 candidate_id；不要重复安排同一真实景点或餐厅；"
            "体现用户偏好、节奏取舍、天气和交通约束；泛化建议不得进入地图。"
            "最后一天如安排返程交通，必须写成 category=transfer，只说明从目的地车站/机场返回出发城市，不能再给目的地住宿建议。"
            "如果高德候选没有 cost，只有在常识上明确可能有门票/体验消费时才给正价 estimated_price_range，例如 30-80；"
            "开放空间、免费公共活动或无法判断是否收费时可给 0-0，price_note 必须说明需以官方/现场为准。"
            "不要编造实时票价、门票库存或可预订价格。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )

        last_error = ""
        for attempt in range(2):
            prompt = user_prompt
            if attempt:
                prompt += f"\n\n上一次输出无法解析为合法 JSON，错误：{last_error}。请只返回 JSON 对象。"
            try:
                response = self.model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
                content = self._message_content_to_text(response.content)
                parsed = self._parse_json_object(content)
                return {"llm_status": "used", "reason": "", "plan": parsed}
            except Exception as exc:  # noqa: BLE001 - caller needs fallback reason, not exception type.
                last_error = str(exc)

        return {"llm_status": "parse_failed", "reason": last_error, "plan": None}

    def estimate_hotel_prices(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return {"llm_status": "unavailable", "reason": "DEEPSEEK_API_KEY missing", "prices": []}

        system_prompt = (
            "你是 TravelMind 的酒店价格常识估算助手。你只能给非实时常识区间，"
            "不能声称这是可预订房价、库存或平台实时价。只输出 JSON。"
        )
        user_prompt = (
            "请为没有高德 cost 的酒店候选估算每晚价格区间，schema 如下：\n"
            '{"prices":[{"candidate_id":"","estimated_price_range":"300-500",'
            '"price_confidence":"low|medium|unknown","price_note":""}]}\n'
            "要求：价格单位为人民币/晚；必须写明需以酒店平台实时房价和房态为准；"
            "如果无法判断，price_confidence 用 unknown。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            response = self.model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            content = self._message_content_to_text(response.content)
            parsed = self._parse_json_object(content)
        except Exception as exc:  # noqa: BLE001 - caller needs a clean fallback path.
            return {"llm_status": "parse_failed", "reason": str(exc), "prices": []}

        prices = parsed.get("prices") if isinstance(parsed.get("prices"), list) else []
        return {"llm_status": "used", "reason": "", "prices": prices}

    def judge_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return {"llm_status": "unavailable", "reason": "DEEPSEEK_API_KEY missing", "judgement": None}

        system_prompt = (
            "你是 TravelMind 的路线体验评审。高德和后端规则负责路线事实，你只判断这段移动放在当天行程里是否合理。"
            "不要编造路线、票价、实时打车价格或不存在的地点；替换地点只能返回输入候选中的 candidate_id。"
            "只输出 JSON，不要 Markdown，不要解释。"
        )
        user_prompt = (
            "请评审这段目的地内移动，schema 如下：\n"
            '{"decision":"accept|switch_mode|replace_place|mark_impractical",'
            '"suggested_mode":"taxi|driving|transit|walking|bicycling",'
            '"replacement_candidate_id":"","risk_level":"low|medium|high",'
            '"judge_reason":"","display_summary":""}\n'
            "判断原则：如果公共交通耗时明显破坏旅行体验，可建议 switch_mode；如果同类近距离候选更合适，优先 replace_place；"
            "如果无合适交通或替换，mark_impractical。accept 只能用于轻松、可信、值得的移动。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            response = self.model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            content = self._message_content_to_text(response.content)
            parsed = self._parse_json_object(content)
        except Exception as exc:  # noqa: BLE001 - caller needs clean fallback metadata.
            return {"llm_status": "parse_failed", "reason": str(exc), "judgement": None}

        return {"llm_status": "used", "reason": "", "judgement": parsed}

    def review_itinerary(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return {"llm_status": "unavailable", "reason": "DEEPSEEK_API_KEY missing", "review": None}

        system_prompt = (
            "你是 TravelMind 的行程质量体检员。你只基于输入中的真实候选、路线事实、用户偏好检查行程质量。"
            "如果建议返工，repaired_plan 中的真实地点必须使用输入候选 candidate_id；不要编造地点、价格、车次、航班或库存。"
            "只输出 JSON，不要 Markdown，不要解释。"
        )
        user_prompt = (
            "请体检这份行程，schema 如下：\n"
            '{"overall_score":80,"route_score":80,"pace_score":80,"cluster_score":80,"logic_score":80,'
            '"issues":[{"severity":"low|medium|high","day":1,"message":"","kind":"route|pace|cluster|logic|budget"}],'
            '"fixes":[""],"needs_repair":false,"repaired_plan":{"days":[]}}\n'
            "评分 0-100。只有发现高风险跨区乱跳、超长交通、返程/住宿串台、节奏明显不符时 needs_repair=true。"
            "repaired_plan 与规划 schema 一致，最多返工一次，优先调整顺序或替换为同片区真实候选。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            response = self.model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            content = self._message_content_to_text(response.content)
            parsed = self._parse_json_object(content)
        except Exception as exc:  # noqa: BLE001 - caller needs clean fallback metadata.
            return {"llm_status": "parse_failed", "reason": str(exc), "review": None}

        return {"llm_status": "used", "reason": "", "review": parsed}

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part)
        return str(content)

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
        if fenced:
            cleaned = fenced.group(1)
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("DeepSeek output is not a JSON object")
        return data


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
        candidate_contracts = self._build_candidate_contracts(prefs, pois, hotels, weather)
        pois["candidate_contracts"] = candidate_contracts.get("pois", {})
        hotels["candidate_contracts"] = candidate_contracts.get("hotels", [])
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
            lambda: self._build_local_transport_segments(prefs, local_transport, itinerary_days, pois),
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
            "candidate_contracts": candidate_contracts,
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
        constraint_summary = self._normalize_constraint_summary(payload, preference_profile)
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
            "freeText": constraint_summary["rawText"],
            "hardConstraints": [item["text"] for item in constraint_summary["hard"]],
            "softPreferences": [item["text"] for item in constraint_summary["soft"]],
            "constraintSummary": constraint_summary,
        }

    @classmethod
    def _normalize_constraint_summary(
        cls,
        payload: dict[str, Any],
        preference_profile: dict[str, Any],
    ) -> dict[str, Any]:
        raw_text = cls._clean_constraint_text(payload.get("freeText") or payload.get("free_text"))[:1200]
        hard = cls._constraint_entries(payload.get("hardConstraints") or payload.get("hard_constraints"), "hard", "explicit")
        soft = cls._constraint_entries(payload.get("softPreferences") or payload.get("soft_preferences"), "soft", "explicit")
        inferred_hard, inferred_soft, unknown = cls._infer_constraint_entries(raw_text)
        hard.extend(inferred_hard)
        soft.extend(inferred_soft)

        max_transfer = preference_profile.get("maxTransferMinutes", 45)
        hard.insert(
            0,
            {
                "kind": "hard",
                "text": f"单段交通尽量控制在 {max_transfer} 分钟内",
                "source": "profile",
                "field": "maxTransferMinutes",
            },
        )
        soft.extend(
            [
                {
                    "kind": "soft",
                    "text": f"旅行节奏：{preference_profile.get('pace', '标准')}",
                    "source": "profile",
                    "field": "pace",
                },
                {
                    "kind": "soft",
                    "text": f"住宿策略：{preference_profile.get('hotelStrategy', '近地铁枢纽')}",
                    "source": "profile",
                    "field": "hotelStrategy",
                },
            ]
        )
        return {
            "rawText": raw_text,
            "hard": cls._dedupe_constraint_entries(hard),
            "soft": cls._dedupe_constraint_entries(soft),
            "unknown": cls._dedupe_constraint_entries(unknown),
        }

    @staticmethod
    def _clean_constraint_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def _constraint_entries(cls, value: Any, default_kind: str, source: str) -> list[dict[str, str]]:
        if isinstance(value, (str, dict)):
            values = [value]
        elif isinstance(value, list):
            values = value
        else:
            values = []

        entries: list[dict[str, str]] = []
        for raw in values:
            if isinstance(raw, dict):
                text = raw.get("text") or raw.get("value") or raw.get("description")
                kind = str(raw.get("kind") or default_kind).strip().lower()
            else:
                text = raw
                kind = default_kind
            if kind not in {"hard", "soft", "unknown"}:
                kind = default_kind
            for part in cls._split_constraint_text(text):
                entries.append({"kind": kind, "text": part, "source": source})
        return entries

    @staticmethod
    def _split_constraint_text(value: Any) -> list[str]:
        text = StructuredTravelPlanner._clean_constraint_text(value)
        return [part for part in re.split(r"[\r\n；;。！？!?]+", text) if part]

    @classmethod
    def _infer_constraint_entries(cls, raw_text: str) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        hard_markers = ("必须", "务必", "不要", "不安排", "避免", "只安排", "仅安排", "最多", "至少", "不超过", "不去", "不坐", "不住", "固定")
        soft_markers = ("希望", "想要", "喜欢", "优先", "尽量", "轻松", "慢一点", "少")
        hard: list[dict[str, str]] = []
        soft: list[dict[str, str]] = []
        unknown: list[dict[str, str]] = []
        for part in cls._split_constraint_text(raw_text):
            if any(marker in part for marker in hard_markers):
                hard.append({"kind": "hard", "text": part, "source": "inferred"})
            elif any(marker in part for marker in soft_markers):
                soft.append({"kind": "soft", "text": part, "source": "inferred"})
            else:
                unknown.append({"kind": "unknown", "text": part, "source": "inferred"})
        return hard, soft, unknown

    @staticmethod
    def _dedupe_constraint_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in entries:
            kind = str(entry.get("kind") or "unknown")
            text = StructuredTravelPlanner._clean_constraint_text(entry.get("text"))
            if not text or (kind, text) in seen:
                continue
            seen.add((kind, text))
            result.append(
                {
                    **entry,
                    "id": f"{kind}-{len(result) + 1}",
                    "kind": kind,
                    "text": text,
                    "source": str(entry.get("source") or "unknown"),
                }
            )
        return result

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

    def _build_weather(self, prefs: dict[str, Any]) -> dict[str, str]:
        result = {}
        for city in dict.fromkeys([prefs["originCity"], prefs["destinationCity"]]):
            result[city] = self.toolbox.call("get_weather", city=city, date=prefs["startDate"])
        return result

    def _build_weather_advice(self, weather: dict[str, str]) -> dict[str, str]:
        text = " ".join(weather.values())
        has_rain = bool(re.search(r"雷阵雨|阵雨|小雨|中雨|大雨|暴雨|雨", text)) and "无雨" not in text
        max_temp = self._max_temperature(text)
        max_wind = self._max_wind_level(text)

        if max_temp and max_temp >= 32:
            sun = "白天温度偏高，建议带防晒霜、帽子或墨镜，户外活动安排在上午或傍晚。"
            clothing = "穿轻薄透气衣物，准备补水；午后减少长时间暴晒。"
        elif max_temp and max_temp >= 28:
            sun = "紫外线和体感热度可能偏高，建议基础防晒并注意补水。"
            clothing = "短袖或轻薄衣物为主，室内空调环境可备一件薄外套。"
        else:
            sun = "常规防晒即可，按当天实际体感调整户外停留时间。"
            clothing = "穿舒适便于步行的衣物和鞋，早晚可按气温加减外套。"

        if has_rain:
            umbrella = "建议带伞或轻便雨衣；遇到阵雨时优先调整为室内景点、商场或餐厅休整。"
            schedule = "雨天不建议强行安排骑行或长距离步行，打车/地铁接驳更稳。"
        else:
            umbrella = "暂无明显降雨提示，可按需带轻便伞兼顾遮阳。"
            schedule = "天气总体可正常安排户外活动，保留 30-60 分钟机动时间即可。"

        if max_wind and max_wind >= 4:
            schedule += " 风力偏大时注意帽子、雨伞稳定性，滨水或高处停留时间可适当缩短。"

        return {
            "sun_protection": sun,
            "clothing": clothing,
            "umbrella": umbrella,
            "schedule_note": schedule,
        }

    def _build_intercity_transport(self, prefs: dict[str, Any]) -> dict[str, Any]:
        origin = prefs["originCity"]
        destination = prefs["destinationCity"]
        modes = prefs["intercityModes"]
        amap_modes = [mode for mode in modes if mode in {"rail", "driving"}]
        route_text = ""
        if amap_modes:
            route_text = self.toolbox.call(
                "amap_plan_routes",
                origin=origin,
                destination=destination,
                origin_city=origin,
                destination_city=destination,
                modes=",".join(amap_modes),
                max_routes=2,
            )

        options = []
        rail_payload = self.rail_provider.query(origin, destination, prefs["startDate"])
        flight_payload = self.flight_provider.query(origin, destination, prefs["startDate"])
        route_origin_detail, route_destination_detail = self._route_endpoint_details(route_text, origin, destination)

        if "rail" in modes:
            rail_summary = self._section_summary(route_text, "高铁/城际铁路") or rail_payload.message
            rail_origin_detail, rail_destination_detail = self._rail_endpoint_details(rail_summary, origin, destination)
            options.append(
                {
                    "mode": "rail",
                    "title": MODE_LABELS["rail"],
                    "status": "fallback",
                    "summary": rail_summary,
                    "origin": origin,
                    "destination": destination,
                    "origin_city": origin,
                    "destination_city": destination,
                    "origin_detail": rail_origin_detail,
                    "destination_detail": rail_destination_detail,
                    "duration": self._transport_duration_label("rail", prefs, rail_summary),
                    "price": self._transport_price_label("rail", prefs, rail_summary),
                    "price_source": "rule_fallback",
                    "distance_km": prefs.get("estimatedDistanceKm"),
                    "provider_status": rail_payload.status,
                    "warning": rail_payload.message,
                }
            )
        if "flight" in modes:
            flight_summary = self._flight_strategy(prefs)
            options.append(
                {
                    "mode": "flight",
                    "title": MODE_LABELS["flight"],
                    "status": flight_payload.status,
                    "summary": flight_summary,
                    "origin": origin,
                    "destination": destination,
                    "origin_city": origin,
                    "destination_city": destination,
                    "origin_detail": f"{origin}机场待确认",
                    "destination_detail": f"{destination}机场待确认",
                    "duration": self._transport_duration_label("flight", prefs, flight_summary),
                    "price": "航班实时价格未接入",
                    "price_source": "unknown_price",
                    "distance_km": prefs.get("estimatedDistanceKm"),
                    "provider_status": flight_payload.status,
                    "warning": flight_payload.message,
                }
            )
        if "driving" in modes:
            driving_summary = self._section_summary(route_text, "驾车") or "适合多人同行、行李较多或目的地分散；需关注停车和拥堵。"
            options.append(
                {
                    "mode": "driving",
                    "title": MODE_LABELS["driving"],
                    "status": "amap_fallback" if route_text else "not_configured",
                    "summary": driving_summary,
                    "origin": origin,
                    "destination": destination,
                    "origin_city": origin,
                    "destination_city": destination,
                    "origin_detail": route_origin_detail,
                    "destination_detail": route_destination_detail,
                    "duration": self._transport_duration_label("driving", prefs, driving_summary),
                    "price": self._transport_price_label("driving", prefs, driving_summary),
                    "price_source": "amap_route" if "过路费约" in driving_summary else "rule_fallback",
                    "distance_km": prefs.get("estimatedDistanceKm"),
                    "provider_status": "amap_fallback",
                    "warning": "驾车路线来自高德路线规划，建议出发前再次查看实时路况。",
                }
            )

        recommended = self._recommend_intercity_mode(prefs, options)
        notes = [
            "先确定跨城主交通，再安排目的地内交通和酒店位置。",
            "实时票价、余票和航班库存需要接入正式供应商后展示。",
        ]
        if route_text:
            notes.append("高德路线摘要已用于高铁/自驾候选的说明。")

        return {
            "recommended": recommended,
            "options": options,
            "notes": notes,
            "raw": route_text,
        }

    @staticmethod
    def _route_endpoint_details(route_text: str, origin: str, destination: str) -> tuple[str, str]:
        origin_detail = StructuredTravelPlanner._extract_route_endpoint(route_text, "出发地") or f"{origin}市中心"
        destination_detail = StructuredTravelPlanner._extract_route_endpoint(route_text, "目的地") or f"{destination}市中心"
        return origin_detail, destination_detail

    @staticmethod
    def _extract_route_endpoint(route_text: str, label: str) -> str:
        if not route_text:
            return ""
        match = re.search(rf"{re.escape(label)}：(.+?)(?:（[^）]*）)?(?:\n|$)", route_text)
        if not match:
            return ""
        value = match.group(1).strip()
        value = re.sub(r"（[^）]*）", "", value).strip()
        return value

    @staticmethod
    def _rail_endpoint_details(summary: str, origin: str, destination: str) -> tuple[str, str]:
        if summary:
            match = re.search(r"(?:高铁/城际铁路|高铁/城际铁路建议)：\s*(.+?)(?:，|。|$)", summary)
            route_text = match.group(1).strip() if match else summary
            route_match = re.search(r"(.+?)\s*(?:->|→|到|至)\s*(.+?)(?:，|。|$)", route_text)
            if route_match:
                return route_match.group(1).strip(), route_match.group(2).strip()
        return f"{origin}主要高铁站待确认", f"{destination}主要高铁站待确认"

    @staticmethod
    def _transport_duration_label(mode: str, prefs: dict[str, Any], text: str) -> str:
        if mode == "rail":
            match = re.search(r"车程\s*([^。；，]+)", text)
            if match:
                return match.group(1).strip()
            distance = prefs.get("estimatedDistanceKm") or 160
            return f"约 {max(30, round(distance / 3))} 分钟"
        if mode == "driving":
            match = re.search(r"(约\s*\d+(?:\.\d+)?\s*(?:小时|分钟)(?:\s*\d+\s*分钟)?)", text)
            if match:
                return match.group(1).strip()
            distance = prefs.get("estimatedDistanceKm") or 180
            return f"约 {round(distance / 75, 1)} 小时"
        if mode == "flight":
            distance = prefs.get("estimatedDistanceKm") or 1000
            return "约 3-5 小时（含机场接驳）" if distance >= 800 else "约 2-4 小时（含机场接驳）"
        return "待校准"

    @staticmethod
    def _transport_price_label(mode: str, prefs: dict[str, Any], text: str) -> str:
        if mode == "rail":
            match = re.search(r"约\s*([0-9.]+)\s*[~\-～]\s*([0-9.]+)\s*元", text)
            if match:
                return f"二等座约 {match.group(1)}-{match.group(2)} 元/人，需以 12306 为准"
            distance = prefs.get("estimatedDistanceKm") or 180
            low = round(distance * 0.45)
            high = round(distance * 0.7)
            return f"二等座约 {low}-{high} 元/人，规则估算，需以 12306 为准"
        if mode == "driving":
            tolls = re.findall(r"过路费约\s*([0-9.]+)\s*元", text)
            if tolls:
                return f"过路费约 {tolls[0]} 元，油电费另计"
            distance = prefs.get("estimatedDistanceKm") or 180
            return f"油电费约 {round(distance * 0.6)}-{round(distance * 1.0)} 元，规则估算"
        return "价格待核实"

    @staticmethod
    def _flight_strategy(prefs: dict[str, Any]) -> str:
        distance = prefs.get("estimatedDistanceKm")
        if distance and distance >= 800:
            return "两地距离较远，飞机适合作为省时主交通；需接入航班供应商后展示具体班次和价格。"
        return "两地距离不算远时，飞机通常不如高铁/自驾顺滑；仅在有直飞且机场接驳方便时考虑。"

    @staticmethod
    def _recommend_intercity_mode(prefs: dict[str, Any], options: list[dict[str, Any]]) -> str:
        available = {option["mode"] for option in options}
        distance = prefs.get("estimatedDistanceKm")
        if "flight" in available and distance and distance >= 800:
            return "flight"
        if "rail" in available:
            return "rail"
        if "driving" in available:
            return "driving"
        return options[0]["mode"] if options else "driving"

    def _build_pois(self, prefs: dict[str, Any]) -> dict[str, Any]:
        raw = self.toolbox.call(
            "search_poi",
            city=prefs["destinationCity"],
            preference="、".join(prefs["interests"]),
        )
        attractions = self._parse_numbered_section(raw, "景点/活动") or self._parse_numbered_section(raw, "经典景点")
        real_foods = self._parse_numbered_section(raw, "美食/餐厅")
        specialty_places = self._parse_numbered_section(raw, "特色店铺参考")
        generic_foods = self._parse_numbered_section(raw, "地方特色美食")
        return {
            "attractions": attractions,
            "foods": real_foods or specialty_places or generic_foods,
            "specialty_places": specialty_places,
            "raw": raw,
        }

    def _build_hotels(self, prefs: dict[str, Any]) -> dict[str, Any]:
        provider_message = self.hotel_provider.message()
        raw = self.toolbox.call(
            "search_hotels",
            city=prefs["destinationCity"],
            hotel_level=prefs["hotelLevel"],
            limit=6,
        )
        candidates = self._parse_numbered_section(raw, "酒店候选")
        fallback_price = self._hotel_reference_price(prefs["hotelLevel"])
        ai_price_estimates = self._estimate_hotel_price_ranges(prefs, candidates)
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
                candidate["cost_estimate"] = self._price_midpoint(price_range) or fallback_price
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
                f"{self._hotel_nearby_label(candidate)}，{prefs['hotelLevel']}档住宿，"
                "便于换乘、晚间返程和寄存行李。"
            )
        status = "amap_fallback" if "provider_status=amap_fallback" in raw else self.hotel_provider.status()
        if status == "live":
            status = "amap_fallback"
        area_recommendation = self._extract_prefixed_line(raw, "住宿区域建议")
        if self._is_generic_hotel_area(area_recommendation):
            area_recommendation = self._hotel_area_from_candidates(prefs, candidates)
        return {
            "area_recommendation": area_recommendation or self._hotel_area_from_candidates(prefs, candidates),
            "candidates": candidates,
            "provider_status": status,
            "notes": [provider_message, "酒店候选来自 POI 搜索，不代表实时房态或可预订价格。"],
            "raw": raw,
        }

    def _estimate_hotel_price_ranges(
        self,
        prefs: dict[str, Any],
        candidates: list[dict[str, Any]],
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
        result = self.deepseek_brain.estimate_hotel_prices(payload)
        if result.get("llm_status") != "used":
            return {}

        estimates: dict[str, dict[str, Any]] = {}
        for raw in result.get("prices", []):
            if not isinstance(raw, dict):
                continue
            candidate_id = str(raw.get("candidate_id") or "").strip()
            price_range = self._parse_price_range(raw.get("estimated_price_range"))
            if not candidate_id or not price_range:
                continue
            price_range = {**price_range, "unit": "night"}
            note = str(raw.get("price_note") or "").strip()
            if "实时" not in note and "房态" not in note:
                note = f"{note} 需以酒店平台实时房价和房态为准。".strip()
            estimates[candidate_id] = {
                "price_range": price_range,
                "price_confidence": self._normalize_price_confidence(raw.get("price_confidence"), "low"),
                "price_note": note or "AI 常识估算，需以酒店平台实时房价和房态为准。",
            }
        return estimates

    @staticmethod
    def _default_hotel_area(prefs: dict[str, Any]) -> str:
        return f"建议住在{prefs['destinationCity']}核心商圈、地铁枢纽或第一天重点景点附近，减少换乘和搬运行李。"

    @staticmethod
    def _is_generic_hotel_area(value: Any) -> bool:
        text = str(value or "")
        generic_markers = ["核心商圈", "地铁枢纽", "第一天重点景点", "交通枢纽"]
        return any(marker in text for marker in generic_markers)

    @classmethod
    def _hotel_area_from_candidates(cls, prefs: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
        landmarks: list[str] = []
        for candidate in candidates[:4]:
            for landmark in cls._hotel_nearby_landmarks(candidate):
                if landmark not in landmarks:
                    landmarks.append(landmark)
                if len(landmarks) >= 3:
                    break
            if len(landmarks) >= 3:
                break
        if landmarks:
            return f"建议优先住在{'、'.join(landmarks)}周边，减少换乘和搬运行李。"
        return cls._default_hotel_area(prefs)

    @classmethod
    def _hotel_nearby_label(cls, candidate: dict[str, Any]) -> str:
        landmarks = cls._hotel_nearby_landmarks(candidate)
        if landmarks:
            return f"近{'/'.join(landmarks[:2])}"
        address = str(candidate.get("address") or "").strip()
        if address:
            return f"位于{address}"
        return "位于候选酒店所在片区"

    @classmethod
    def _hotel_nearby_landmarks(cls, candidate: dict[str, Any]) -> list[str]:
        labels: list[str] = []

        def add(value: Any) -> None:
            label = cls._clean_hotel_nearby_label(value)
            if label and label not in labels and cls._looks_like_nearby_label(label):
                labels.append(label)

        address = str(candidate.get("address") or "")
        for piece in re.findall(r"[（(]([^（）()]+)[）)]", address):
            add(piece)

        for source in [candidate.get("type"), candidate.get("name")]:
            text = cls._clean_hotel_nearby_label(source)
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

    @staticmethod
    def _clean_hotel_nearby_label(value: Any) -> str:
        text = str(value or "").strip(" \t\r\n，,；;。()（）")
        text = re.sub(r"^(近|靠近|毗邻|位于|距离)", "", text)
        text = re.sub(r"(酒店|宾馆|公寓)?店$", "", text)
        return text.strip(" \t\r\n，,；;。()（）")

    @staticmethod
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

    @staticmethod
    def _hotel_reference_price(hotel_level: str) -> int:
        return {"经济": 220, "舒适": 380, "高端": 680}.get(hotel_level, 380)

    @staticmethod
    def _extract_prefixed_line(text: str, prefix: str) -> str:
        for line in text.splitlines():
            clean = line.strip()
            if clean.startswith(prefix):
                return clean.split("：", 1)[-1].strip()
        return ""

    def _enrich_place_clusters(self, pois: dict[str, Any], hotels: dict[str, Any]) -> None:
        cluster_items: list[dict[str, Any]] = []
        for group_name in ["attractions", "specialty_places", "foods"]:
            for item in pois.get(group_name) or []:
                point = self._normalize_point(item.get("location"))
                if point:
                    cluster_items.append({"item": item, "point": point})
        for item in hotels.get("candidates") or []:
            point = self._normalize_point(item.get("location"))
            if point:
                cluster_items.append({"item": item, "point": point})

        clusters: list[dict[str, Any]] = []
        for entry in cluster_items:
            nearest = self._nearest_cluster(entry["point"], clusters)
            cluster = nearest["cluster"] if nearest else None
            if not nearest or nearest["distance_km"] > 8:
                cluster = {
                    "id": f"cluster-{len(clusters) + 1}",
                    "items": [],
                    "center": dict(entry["point"]),
                    "anchor": self._cluster_anchor(entry["item"]),
                }
                clusters.append(cluster)
            cluster["items"].append(entry)
            count = len(cluster["items"])
            cluster["center"] = {
                "lng": (cluster["center"]["lng"] * (count - 1) + entry["point"]["lng"]) / count,
                "lat": (cluster["center"]["lat"] * (count - 1) + entry["point"]["lat"]) / count,
            }
            if not cluster.get("anchor"):
                cluster["anchor"] = self._cluster_anchor(entry["item"])

        for cluster in clusters:
            anchor = cluster.get("anchor") or f"片区{cluster['id'].split('-')[-1]}"
            cluster_name = f"{anchor}片区"
            for entry in cluster["items"]:
                item = entry["item"]
                item["cluster_id"] = cluster["id"]
                item["cluster_name"] = cluster_name
                item["nearby_anchor"] = anchor

    def _nearest_cluster(self, point: dict[str, float], clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
        nearest = None
        for cluster in clusters:
            distance = self._point_distance_km(point, cluster["center"])
            if nearest is None or distance < nearest["distance_km"]:
                nearest = {"cluster": cluster, "distance_km": distance}
        return nearest

    @staticmethod
    def _cluster_anchor(item: dict[str, Any]) -> str:
        for source in [item.get("type"), item.get("address"), item.get("name")]:
            text = str(source or "").strip()
            if not text:
                continue
            match = re.search(
                r"([\u4e00-\u9fffA-Za-z0-9]+?(?:地铁站|会展中心|商业中心|购物中心|公园|广场|海滩|海边|博物馆|美术馆|景区|老街|口岸|机场|火车站|高铁站|北站|南站|东站|西站))",
                text,
            )
            if match:
                return match.group(1).strip()
            piece = re.split(r"[，,；;()（）]", text)[0].strip()
            if 2 <= len(piece) <= 12:
                return piece
        return ""

    def _build_local_transport(self, prefs: dict[str, Any], routes: dict[str, Any], hotels: dict[str, Any]) -> dict[str, Any]:
        modes = prefs["localModes"]
        recommended = self._ordered_local_modes_for_preferences(modes, prefs)
        notes = []
        if "transit" in modes:
            notes.append("公共交通适合覆盖主城区景点，优先选择地铁可达的酒店和景点组合。")
        if "taxi" in modes:
            notes.append("打车适合车站/机场到酒店、夜间返程和跨区移动，预算需预留弹性。")
        if "walking" in modes:
            notes.append("步行适合商圈、老街和相邻景点之间的短距离接驳。")
        if "bicycling" in modes:
            notes.append("骑行适合滨水、绿道和景区外围路线，雨天或高温时不建议强行安排。")
        if "driving" in modes:
            notes.append("目的地自驾适合郊区景点和多人同行，但要提前确认停车条件。")
        notes.append(f"住宿建议参考：{hotels.get('area_recommendation', self._default_hotel_area(prefs))}")
        return {
            "recommended_modes": recommended,
            "notes": notes,
            "route_context": routes.get("recommended", "rail"),
        }

    @staticmethod
    def _ordered_local_modes_for_preferences(modes: list[str], prefs: dict[str, Any]) -> list[str]:
        available = list(dict.fromkeys(modes or []))
        profile = prefs.get("preferenceProfile") or {}
        hints = " ".join(profile.get("learnedHints") or [])
        prefer_less_transit = profile.get("pace") == "轻松" or any(keyword in hints for keyword in ["少公交", "别太赶", "轻松", "不去太远"])
        if prefer_less_transit:
            order = ["walking", "taxi", "driving", "transit", "bicycling"]
        else:
            order = ["walking", "bicycling", "transit", "taxi", "driving"]
        ordered = [mode for mode in order if mode in available]
        return ordered or available

    def _build_local_transport_segments(
        self,
        prefs: dict[str, Any],
        local_transport: dict[str, Any],
        itinerary_days: list[dict[str, Any]],
        pois: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enriched = {
            "recommended_modes": list(local_transport.get("recommended_modes") or prefs.get("localModes") or []),
            "notes": list(local_transport.get("notes") or []),
            "route_context": local_transport.get("route_context", ""),
            "segments": [],
        }
        query_limit = self._local_route_query_limit()
        route_queries = 0
        used_place_keys = self._itinerary_used_place_keys(itinerary_days)

        for day in itinerary_days:
            for item in day.get("items", []):
                item.pop("arrival_transport_segment", None)

            places = [place for place in (self._segment_place(item) for item in day.get("items", [])) if place]
            for previous, current in zip(places, places[1:]):
                distance_km = self._point_distance_km(previous["point"], current["point"])
                mode = self._select_local_segment_mode(enriched["recommended_modes"], distance_km)
                segment, route_queries = self._local_segment_for_mode(
                    prefs,
                    day.get("day"),
                    previous,
                    current,
                    mode,
                    distance_km,
                    route_queries,
                    query_limit,
                )
                replacement_candidates = self._replacement_candidates_for_segment(
                    pois or {},
                    current["item"],
                    used_place_keys,
                    previous["point"],
                )
                judgement = self._judge_local_segment(
                    prefs,
                    day,
                    previous,
                    current,
                    segment,
                    enriched["recommended_modes"],
                    replacement_candidates,
                )
                segment, route_queries = self._apply_local_route_judgement(
                    prefs,
                    day.get("day"),
                    previous,
                    current,
                    segment,
                    judgement,
                    replacement_candidates,
                    enriched["recommended_modes"],
                    used_place_keys,
                    route_queries,
                    query_limit,
                )

                enriched["segments"].append(segment)
                current["item"]["arrival_transport_segment"] = self._public_item_segment(segment)

        if enriched["segments"]:
            enriched["notes"].append("目的地内路线按最终每日行程相邻真实地点生成；打车费用为距离规则估算，不代表实时叫车价格。")
        else:
            enriched["notes"].append("当前真实可定位相邻地点不足，目的地内路线将在重新规划后补充。")
        return enriched

    @staticmethod
    def _local_route_query_limit() -> int:
        try:
            return max(0, min(int(os.getenv("TRAVELMIND_LOCAL_ROUTE_QUERY_LIMIT", "8")), 20))
        except ValueError:
            return 8

    def _local_segment_for_mode(
        self,
        prefs: dict[str, Any],
        day_number: Any,
        previous: dict[str, Any],
        current: dict[str, Any],
        mode: str,
        distance_km: float,
        route_queries: int,
        query_limit: int,
    ) -> tuple[dict[str, Any], int]:
        if mode == "taxi":
            return self._rule_local_segment(day_number, previous, current, mode, distance_km, "estimated"), route_queries
        if route_queries < query_limit:
            return self._amap_local_segment(prefs, day_number, previous, current, mode, distance_km), route_queries + 1
        return self._rule_local_segment(day_number, previous, current, mode, distance_km, "limited"), route_queries

    def _judge_local_segment(
        self,
        prefs: dict[str, Any],
        day: dict[str, Any],
        previous: dict[str, Any],
        current: dict[str, Any],
        segment: dict[str, Any],
        modes: list[str],
        replacement_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rule_judgement = self._rule_route_judgement(segment, modes)
        payload = {
            "preferences": {
                "destination_city": prefs.get("destinationCity"),
                "travelers": prefs.get("travelers"),
                "budget": prefs.get("budget"),
                "local_modes": modes,
                "interests": prefs.get("interests", []),
            },
            "day": {"day": day.get("day"), "theme": day.get("theme", "")},
            "from": {
                "title": previous["item"].get("title", ""),
                "detail": previous["detail"],
                "category": previous["item"].get("category", ""),
            },
            "to": {
                "title": current["item"].get("title", ""),
                "detail": current["detail"],
                "category": current["item"].get("category", ""),
            },
            "route_fact": {
                "mode": segment.get("mode"),
                "duration": segment.get("duration"),
                "duration_minutes": self._local_duration_minutes(segment),
                "distance": segment.get("distance"),
                "distance_km": segment.get("distance_km"),
                "price": segment.get("price"),
                "summary": self._compact(segment.get("summary", ""), 420),
                "source": segment.get("source"),
                "status": segment.get("status"),
            },
            "replacement_candidates": [
                {
                    "candidate_id": item["candidate_id"],
                    "name": item["name"],
                    "category": item["category"],
                    "address": item.get("address", ""),
                    "distance_from_previous_km": item.get("distance_from_previous_km"),
                    "type": item.get("type", ""),
                }
                for item in replacement_candidates[:6]
            ],
            "constraints": [
                "只基于 route_fact 和 replacement_candidates 判断，不编造路线事实",
                "replacement_candidate_id 必须来自 replacement_candidates",
                "打车价格不是实时价格，只能作为距离规则估算展示",
            ],
        }
        result = self.deepseek_brain.judge_route(payload)
        if result.get("llm_status") != "used":
            return rule_judgement

        judgement = self._normalize_route_judgement(result.get("judgement"), "deepseek")
        if judgement["decision"] == "accept" and rule_judgement["decision"] != "accept":
            rule_judgement["judge_reason"] = f"安全兜底：{rule_judgement['judge_reason']}"
            return rule_judgement
        return judgement

    def _apply_local_route_judgement(
        self,
        prefs: dict[str, Any],
        day_number: Any,
        previous: dict[str, Any],
        current: dict[str, Any],
        segment: dict[str, Any],
        judgement: dict[str, Any],
        replacement_candidates: list[dict[str, Any]],
        modes: list[str],
        used_place_keys: set[str],
        route_queries: int,
        query_limit: int,
    ) -> tuple[dict[str, Any], int]:
        decision = judgement.get("decision")
        if decision == "replace_place":
            replacement = self._validated_replacement_candidate(judgement, replacement_candidates, current, previous, used_place_keys)
            if replacement:
                self._replace_segment_item(day_number, current, replacement)
                replacement_key = self._poi_key(replacement)
                if replacement_key:
                    used_place_keys.add(replacement_key)
                replacement_id = str(replacement.get("id") or "")
                if replacement_id:
                    used_place_keys.add(replacement_id)
                distance_km = self._point_distance_km(previous["point"], current["point"])
                mode = self._select_local_segment_mode(modes, distance_km)
                segment, route_queries = self._local_segment_for_mode(
                    prefs,
                    day_number,
                    previous,
                    current,
                    mode,
                    distance_km,
                    route_queries,
                    query_limit,
                )
                return self._annotate_route_judgement(segment, judgement), route_queries
            judgement = {
                **judgement,
                "decision": "mark_impractical",
                "risk_level": "high",
                "judge_reason": judgement.get("judge_reason") or "建议替换景点，但未找到可验证的同类近距离候选。",
            }

        if decision == "switch_mode":
            switch_mode = self._switch_mode_from_judgement(judgement, modes)
            distance_km = self._point_distance_km(previous["point"], current["point"])
            switched, route_queries = self._local_segment_for_mode(
                prefs,
                day_number,
                previous,
                current,
                switch_mode,
                distance_km,
                route_queries,
                query_limit,
            )
            switched["status"] = "mode_switched"
            switched["warning"] = judgement.get("judge_reason") or f"原路线体验不佳，已改为{MODE_LABELS.get(switch_mode, switch_mode)}估算。"
            return self._annotate_route_judgement(switched, judgement), route_queries

        if decision == "mark_impractical":
            return self._impractical_local_segment(day_number, previous, current, segment, judgement), route_queries

        return self._annotate_route_judgement(segment, judgement), route_queries

    def _rule_route_judgement(self, segment: dict[str, Any], modes: list[str]) -> dict[str, Any]:
        mode = str(segment.get("mode") or "")
        distance_km = float(segment.get("distance_km") or 0)
        duration_minutes = self._local_duration_minutes(segment)
        has_private_mode = "taxi" in modes or "driving" in modes
        too_long_transit = mode == "transit" and (duration_minutes > 90 or distance_km > 35)
        very_far = distance_km > 60
        if too_long_transit or very_far:
            reason_parts = []
            if duration_minutes:
                reason_parts.append(f"耗时约 {self._format_minutes(duration_minutes)}")
            if distance_km:
                reason_parts.append(f"距离约 {self._format_local_distance(distance_km)}")
            reason = "、".join(reason_parts) or "距离/耗时过长"
            if has_private_mode and not very_far:
                return {
                    "decision": "switch_mode",
                    "suggested_mode": "taxi" if "taxi" in modes else "driving",
                    "replacement_candidate_id": "",
                    "risk_level": "medium",
                    "judge_reason": f"规则兜底：公共交通{reason}，不适合作为旅行中相邻移动，已改用更省时方式估算。",
                    "display_summary": "",
                    "judge_source": "rule_fallback",
                }
            return {
                "decision": "mark_impractical",
                "suggested_mode": "",
                "replacement_candidate_id": "",
                "risk_level": "high",
                "judge_reason": f"规则兜底：该段{reason}，不建议作为同一天相邻行程，建议替换或重排景点。",
                "display_summary": "",
                "judge_source": "rule_fallback",
            }
        return {
            "decision": "accept",
            "suggested_mode": mode,
            "replacement_candidate_id": "",
            "risk_level": "low",
            "judge_reason": "路线距离和耗时在可接受范围内。",
            "display_summary": "",
            "judge_source": "rule_fallback",
        }

    @staticmethod
    def _normalize_route_judgement(value: Any, source: str) -> dict[str, Any]:
        raw = value if isinstance(value, dict) else {}
        decision = str(raw.get("decision") or "accept").strip()
        if decision not in {"accept", "switch_mode", "replace_place", "mark_impractical"}:
            decision = "accept"
        suggested_mode = str(raw.get("suggested_mode") or "").strip()
        if suggested_mode not in {"taxi", "driving", "transit", "walking", "bicycling"}:
            suggested_mode = ""
        risk = str(raw.get("risk_level") or "medium").strip().lower()
        if risk not in {"low", "medium", "high"}:
            risk = "medium"
        return {
            "decision": decision,
            "suggested_mode": suggested_mode,
            "replacement_candidate_id": str(raw.get("replacement_candidate_id") or "").strip(),
            "risk_level": risk,
            "judge_reason": str(raw.get("judge_reason") or raw.get("reason") or "").strip(),
            "display_summary": str(raw.get("display_summary") or "").strip(),
            "judge_source": source,
        }

    def _annotate_route_judgement(self, segment: dict[str, Any], judgement: dict[str, Any]) -> dict[str, Any]:
        annotated = dict(segment)
        annotated["judge_source"] = judgement.get("judge_source", "rule_fallback")
        annotated["judge_decision"] = judgement.get("decision", "accept")
        annotated["risk_level"] = judgement.get("risk_level", "low")
        annotated["judge_reason"] = judgement.get("judge_reason", "")
        annotated["replacement_candidate_id"] = judgement.get("replacement_candidate_id", "")
        if judgement.get("display_summary"):
            annotated["summary"] = judgement["display_summary"]
        return annotated

    def _impractical_local_segment(
        self,
        day_number: Any,
        previous: dict[str, Any],
        current: dict[str, Any],
        base_segment: dict[str, Any],
        judgement: dict[str, Any],
    ) -> dict[str, Any]:
        reason = judgement.get("judge_reason") or "路线距离或耗时过长，建议替换或重排景点。"
        segment = {
            **base_segment,
            "day": day_number,
            "from_detail": previous["detail"],
            "to_detail": current["detail"],
            "from_item_id": previous["item"].get("id", ""),
            "to_item_id": current["item"].get("id", ""),
            "price": "建议重排，不估算",
            "cost_estimate": 0,
            "cost_unit": "party",
            "status": "impractical",
            "warning": reason,
            "summary": f"路线待重新规划：{reason}",
        }
        return self._annotate_route_judgement(segment, {**judgement, "decision": "mark_impractical", "risk_level": "high"})

    @staticmethod
    def _switch_mode_from_judgement(judgement: dict[str, Any], modes: list[str]) -> str:
        suggested = str(judgement.get("suggested_mode") or "")
        if suggested in {"taxi", "driving"}:
            return suggested
        if "taxi" in modes:
            return "taxi"
        if "driving" in modes:
            return "driving"
        return "taxi"

    def _replacement_candidates_for_segment(
        self,
        pois: dict[str, Any],
        current_item: dict[str, Any],
        used_place_keys: set[str],
        previous_point: dict[str, float],
    ) -> list[dict[str, Any]]:
        category = current_item.get("category")
        if category == "activity":
            pool = self._dedupe_pois([*(pois.get("attractions") or []), *(pois.get("specialty_places") or [])])
        elif category == "food":
            pool = self._dedupe_pois(pois.get("foods"))
        else:
            return []

        candidates = []
        current_id = str(current_item.get("poi_id") or "")
        for poi in pool:
            poi_id = str(poi.get("id") or "")
            key = self._poi_key(poi)
            if poi_id == current_id or poi_id in used_place_keys or key in used_place_keys:
                continue
            point = self._normalize_point(poi.get("location"))
            if not point:
                continue
            distance = self._point_distance_km(previous_point, point)
            candidates.append(
                {
                    **poi,
                    "candidate_id": poi_id,
                    "category": category,
                    "distance_from_previous_km": round(distance, 2),
                }
            )
        candidates.sort(key=lambda item: item.get("distance_from_previous_km", 9999))
        return candidates[:8]

    def _validated_replacement_candidate(
        self,
        judgement: dict[str, Any],
        replacement_candidates: list[dict[str, Any]],
        current: dict[str, Any],
        previous: dict[str, Any],
        used_place_keys: set[str],
    ) -> dict[str, Any] | None:
        for candidate in replacement_candidates:
            candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "")
            if candidate_id and candidate_id == judgement.get("replacement_candidate_id"):
                current_distance = self._point_distance_km(previous["point"], current["point"])
                candidate_point = self._normalize_point(candidate.get("location"))
                if candidate_point and self._point_distance_km(previous["point"], candidate_point) < current_distance:
                    return candidate
        return None

    def _replace_segment_item(self, day_number: Any, current: dict[str, Any], candidate: dict[str, Any]) -> None:
        item = current["item"]
        category = item.get("category") if item.get("category") in {"activity", "food"} else "activity"
        if category == "food":
            suffix = "用餐"
        else:
            suffix = "游览"
        replacement_item = self._timeline_item(
            int(day_number or item.get("day") or 1),
            str(item.get("time") or ""),
            f"{candidate.get('name', '替换地点')}{suffix}",
            str(candidate.get("name") or ""),
            str(item.get("transport") or "打车/公共交通/步行"),
            str(item.get("duration") or "1-2 小时"),
            str(candidate.get("description") or "DeepSeek 路线体验评审建议替换为同片区真实地点，减少长距离折返。"),
            category,
            candidate,
            self._fallback_cost_for_category(category),
            place_source=candidate.get("_place_source") or "amap_poi",
            is_real_place=True,
        )
        replacement_item["validation_note"] = "DeepSeek 路线体验评审建议替换为更顺路的真实地点。"
        item.clear()
        item.update(replacement_item)
        new_place = self._segment_place(item)
        if new_place:
            current.update(new_place)

    @staticmethod
    def _itinerary_used_place_keys(itinerary_days: list[dict[str, Any]]) -> set[str]:
        used: set[str] = set()
        for day in itinerary_days:
            for item in day.get("items", []):
                poi_id = str(item.get("poi_id") or "")
                if poi_id:
                    used.add(poi_id)
                key = "|".join(str(item.get(field) or "").strip() for field in ["location", "address"])
                if key.strip("|"):
                    used.add(key)
        return used

    @staticmethod
    def _segment_place(item: dict[str, Any]) -> dict[str, Any] | None:
        if item.get("is_real_place") is False:
            return None
        if item.get("place_source") in {"planning_note", "transport_note", "llm_suggestion"}:
            return None
        point = StructuredTravelPlanner._normalize_point(item.get("location_point"))
        if not point:
            return None
        detail = str(item.get("address") or item.get("location") or item.get("title") or "").strip()
        if not detail:
            return None
        return {"item": item, "point": point, "detail": detail, "title": item.get("title", "")}

    @staticmethod
    def _select_local_segment_mode(modes: list[str], distance_km: float) -> str:
        available = list(dict.fromkeys(modes or []))
        if "walking" in available and distance_km <= 1.2:
            return "walking"
        if "bicycling" in available and distance_km <= 5:
            return "bicycling"
        for mode in ["transit", "driving", "taxi", "walking", "bicycling"]:
            if mode in available:
                return mode
        return "taxi"

    def _amap_local_segment(
        self,
        prefs: dict[str, Any],
        day_number: Any,
        previous: dict[str, Any],
        current: dict[str, Any],
        mode: str,
        distance_km: float,
    ) -> dict[str, Any]:
        try:
            raw = self.toolbox.call(
                "amap_plan_routes",
                origin=previous["detail"],
                destination=current["detail"],
                origin_city=prefs["destinationCity"],
                destination_city=prefs["destinationCity"],
                modes=mode,
                max_routes=1,
            )
            summary = self._section_summary(raw, self._local_route_heading(mode)) or raw
            if "查询失败" in summary or "高德路线规划失败" in summary or "高德未返回可用路线" in summary:
                return self._rule_local_segment(day_number, previous, current, mode, distance_km, "fallback", summary)
            return self._local_segment_from_summary(day_number, previous, current, mode, distance_km, summary)
        except Exception as exc:  # noqa: BLE001 - route fallback should keep the plan usable.
            return self._rule_local_segment(day_number, previous, current, mode, distance_km, "fallback", str(exc))

    @staticmethod
    def _local_route_heading(mode: str) -> str:
        return {
            "transit": "公交/地铁",
            "walking": "步行",
            "bicycling": "骑行",
            "driving": "驾车",
        }.get(mode, MODE_LABELS.get(mode, mode))

    def _local_segment_from_summary(
        self,
        day_number: Any,
        previous: dict[str, Any],
        current: dict[str, Any],
        mode: str,
        distance_km: float,
        summary: str,
    ) -> dict[str, Any]:
        parsed_distance = self._parse_local_distance_km(summary) or distance_km
        amount, price, cost_unit = self._local_segment_price(mode, parsed_distance, summary, "amap_route")
        return {
            "day": day_number,
            "from_detail": previous["detail"],
            "to_detail": current["detail"],
            "from_item_id": previous["item"].get("id", ""),
            "to_item_id": current["item"].get("id", ""),
            "mode": mode,
            "mode_label": MODE_LABELS.get(mode, mode),
            "duration": self._parse_local_duration(summary) or self._fallback_local_duration(mode, parsed_distance),
            "distance": self._format_local_distance(parsed_distance),
            "distance_km": round(parsed_distance, 2),
            "price": price,
            "cost_estimate": amount,
            "cost_unit": cost_unit,
            "summary": summary,
            "source": "amap_route",
            "status": "success",
            "warning": "路线来自高德规划摘要；出发前仍需结合实时路况和运营时间确认。",
        }

    def _rule_local_segment(
        self,
        day_number: Any,
        previous: dict[str, Any],
        current: dict[str, Any],
        mode: str,
        distance_km: float,
        status: str,
        reason: str = "",
    ) -> dict[str, Any]:
        amount, price, cost_unit = self._local_segment_price(mode, distance_km, reason, "rule_fallback")
        if status == "limited":
            warning = "为避免高德 QPS 过高，超出上限的市内路线使用距离规则估算。"
        elif mode == "taxi":
            warning = "打车价格为距离规则估算，不代表实时叫车价格。"
        else:
            warning = f"高德路线暂不可用，已降级为距离规则估算。{reason}".strip()
        return {
            "day": day_number,
            "from_detail": previous["detail"],
            "to_detail": current["detail"],
            "from_item_id": previous["item"].get("id", ""),
            "to_item_id": current["item"].get("id", ""),
            "mode": mode,
            "mode_label": MODE_LABELS.get(mode, mode),
            "duration": self._fallback_local_duration(mode, distance_km),
            "distance": self._format_local_distance(distance_km),
            "distance_km": round(distance_km, 2),
            "price": price,
            "cost_estimate": amount,
            "cost_unit": cost_unit,
            "summary": f"{MODE_LABELS.get(mode, mode)}：{previous['detail']} -> {current['detail']}，约 {self._format_local_distance(distance_km)}。",
            "source": "rule_fallback",
            "status": status,
            "warning": warning,
        }

    @staticmethod
    def _public_item_segment(segment: dict[str, Any]) -> dict[str, Any]:
        return {
            key: segment.get(key)
            for key in [
                "from_detail",
                "to_detail",
                "mode",
                "mode_label",
                "duration",
                "distance",
                "price",
                "summary",
                "source",
                "status",
                "warning",
                "judge_source",
                "judge_decision",
                "risk_level",
                "judge_reason",
                "replacement_candidate_id",
            ]
        }

    @staticmethod
    def _point_distance_km(start: dict[str, float], end: dict[str, float]) -> float:
        lat1 = math.radians(float(start["lat"]))
        lat2 = math.radians(float(end["lat"]))
        delta_lat = lat2 - lat1
        delta_lng = math.radians(float(end["lng"]) - float(start["lng"]))
        haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
        return max(0.05, 6371.0 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine)))

    @staticmethod
    def _format_local_distance(distance_km: float) -> str:
        if distance_km < 1:
            return f"{round(distance_km * 1000)} m"
        return f"{distance_km:.1f} km"

    @staticmethod
    def _parse_local_distance_km(text: str) -> float | None:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*km", text, re.I)
        if match:
            return float(match.group(1))
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*m\b", text, re.I)
        if match:
            return float(match.group(1)) / 1000
        return None

    @staticmethod
    def _parse_local_duration(text: str) -> str:
        match = re.search(r"(\d+\s*小时\s*\d+\s*分钟|\d+\s*小时|\d+\s*分钟)", text)
        return match.group(1).replace(" ", "") if match else ""

    @staticmethod
    def _parse_local_duration_minutes(text: str) -> int:
        clean = str(text or "").replace(" ", "")
        match = re.search(r"(?:(\d+)小时)?(?:(\d+)分钟)?", clean)
        if not match or not (match.group(1) or match.group(2)):
            return 0
        return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)

    @classmethod
    def _local_duration_minutes(cls, segment: dict[str, Any]) -> int:
        return cls._parse_local_duration_minutes(segment.get("duration") or segment.get("summary") or "")

    @staticmethod
    def _format_minutes(minutes: int) -> str:
        if minutes < 60:
            return f"{minutes} 分钟"
        hours, rest = divmod(minutes, 60)
        return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"

    @staticmethod
    def _fallback_local_duration(mode: str, distance_km: float) -> str:
        speed = {"walking": 4.5, "bicycling": 12, "transit": 18, "driving": 25, "taxi": 25}.get(mode, 18)
        buffer = {"transit": 8, "driving": 8, "taxi": 5}.get(mode, 0)
        minutes = max(3, round(distance_km / speed * 60 + buffer))
        if minutes < 60:
            return f"{minutes} 分钟"
        hours, rest = divmod(minutes, 60)
        return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"

    @staticmethod
    def _local_segment_price(mode: str, distance_km: float, text: str, source: str) -> tuple[int, str, str]:
        if mode == "taxi":
            amount = round(max(12, 8 + distance_km * 2.8))
            return amount, f"约 ¥{amount}/车，距离规则估算", "party"
        if mode == "transit":
            match = re.search(r"票价约\s*([0-9.]+)\s*元", text)
            amount = round(float(match.group(1))) if match else round(max(2, min(12, distance_km * 1.2 + 2)))
            label = "高德票价参考" if source == "amap_route" and match else "规则估算"
            return amount, f"约 ¥{amount}/人，{label}", "person"
        if mode == "driving":
            toll_match = re.search(r"过路费约\s*([0-9.]+)\s*元", text)
            amount = round(float(toll_match.group(1))) if toll_match else round(max(3, distance_km * 0.9))
            label = "高德过路费参考" if source == "amap_route" and toll_match else "油电规则估算"
            return amount, f"约 ¥{amount}/车，{label}，停车另计", "party"
        if mode in {"walking", "bicycling"}:
            return 0, "¥0，慢行接驳", "person"
        return 0, "价格待核实", "person"

    def _build_budget(
        self,
        prefs: dict[str, Any],
        routes: dict[str, Any],
        local_transport: dict[str, Any],
        hotels: dict[str, Any],
        pois: dict[str, Any],
        itinerary_days: list[dict[str, Any]],
    ) -> dict[str, Any]:
        travelers = prefs["travelers"]
        days = prefs["days"]
        nights = max(days - 1, 1)
        rooms = max(1, (travelers + 1) // 2)

        route_total, route_source = self._estimate_intercity_cost(prefs, routes)
        hotel_unit, hotel_source = self._average_cost_by_source(hotels.get("candidates", []))
        if hotel_unit:
            hotel_total = round(hotel_unit * nights * rooms)
        else:
            hotel_total = self._hotel_reference_price(prefs["hotelLevel"]) * nights * rooms
            hotel_source = "category_rule"

        food_items = self._itinerary_items_by_category(itinerary_days, {"food"})
        activity_items = self._itinerary_items_by_category(itinerary_days, {"activity"})
        food_total = self._sum_itinerary_item_cost(food_items, travelers)
        food_source = self._combined_source(food_items)
        ticket_total = self._sum_itinerary_item_cost(activity_items, travelers)
        ticket_source = self._combined_source(activity_items)
        local_total, local_source, movement_count = self._estimate_itinerary_local_transport_cost(
            local_transport,
            itinerary_days,
            travelers,
        )

        breakdown = {
            "intercity_transport": route_total,
            "hotel": hotel_total,
            "food": food_total,
            "tickets": ticket_total,
            "local_transport": local_total,
        }
        total = sum(value for value in breakdown.values() if isinstance(value, int))
        sources = {
            "intercity_transport": route_source,
            "hotel": hotel_source,
            "food": food_source,
            "tickets": ticket_source,
            "local_transport": local_source,
        }
        basis = [
            f"跨城交通按推荐方案「{MODE_LABELS.get(routes.get('recommended'), routes.get('recommended', ''))}」估算。",
            f"住宿按 {nights} 晚、{rooms} 间房估算，优先使用高德酒店 POI 参考消费。",
            f"餐饮按最终行程中的 {len(food_items)} 个餐饮项目估算，优先使用高德餐厅/特色店铺人均。",
            f"门票/体验按最终行程中的 {len(activity_items)} 个活动项目估算；有高德参考消费或 AI 正价区间时计入，缺少可靠门票价时按无门票/免费项目默认 0 元。",
            f"市内交通按每日活动之间约 {movement_count} 次移动估算，结合推荐交通方式计算。",
            "高德 cost、AI 常识区间和类型规则都不是实时库存价、实时门票价或可预订价；活动 0 元默认值仍需出行前核实。",
        ]
        target = prefs.get("budget")
        if target and total:
            verdict = "within_budget" if total <= target else "over_budget"
            advice = f"预计总花费约 {total} 元，{'低于' if total <= target else '高于'}预算 {target} 元。"
        else:
            verdict = "unknown"
            advice = "用户预算或估算总额不完整，建议按高德参考消费和出行当天价格再校准。"
        return {
            "total": total,
            "target": target,
            "verdict": verdict,
            "breakdown": breakdown,
            "sources": sources,
            "basis": basis,
            "advice": advice,
            "text": "按最终每日行程项目、住宿晚数、推荐交通方式和高德参考消费估算。",
        }

    @staticmethod
    def _itinerary_items_by_category(itinerary_days: list[dict[str, Any]], categories: set[str]) -> list[dict[str, Any]]:
        items = []
        for day in itinerary_days:
            for item in day.get("items", []):
                if item.get("category") in categories:
                    items.append(item)
        return items

    @staticmethod
    def _sum_itinerary_item_cost(items: list[dict[str, Any]], travelers: int) -> int:
        total = 0
        for item in items:
            total += round(float(item.get("cost_estimate") or 0)) * travelers
        return total

    @staticmethod
    def _combined_source(items: list[dict[str, Any]]) -> str:
        if any(item.get("cost_source") == "amap_cost" for item in items):
            return "amap_cost"
        if any(item.get("cost_source") == "amap_route" for item in items):
            return "amap_route"
        if any(item.get("cost_source") == "ai_price_range" for item in items):
            return "ai_price_range"
        if any(item.get("cost_source") in {"category_rule", "rule_fallback"} for item in items):
            return "category_rule"
        if any(item.get("cost_source") == "free_or_no_ticket_default" for item in items):
            return "free_or_no_ticket_default"
        return "unknown_price"

    @staticmethod
    def _estimate_itinerary_local_transport_cost(
        local_transport: dict[str, Any],
        itinerary_days: list[dict[str, Any]],
        travelers: int,
    ) -> tuple[int, str, int]:
        segments = local_transport.get("segments") or []
        if segments:
            total = 0
            for segment in segments:
                amount = round(float(segment.get("cost_estimate") or 0))
                if segment.get("cost_unit") == "party":
                    total += amount
                else:
                    total += amount * travelers
            return total, StructuredTravelPlanner._combined_segment_source(segments), len(segments)

        movement_count = 0
        for day in itinerary_days:
            movable_items = [
                item
                for item in day.get("items", [])
                if item.get("category") in {"activity", "food", "hotel"}
                and item.get("place_source") not in {"planning_note", "transport_note"}
            ]
            movement_count += max(0, len(movable_items) - 1)

        modes = set(local_transport.get("recommended_modes") or [])
        if "taxi" in modes and "transit" in modes:
            unit = 22
        elif "taxi" in modes:
            unit = 45
        elif "transit" in modes:
            unit = 7
        elif "driving" in modes:
            unit = 28
        elif "bicycling" in modes:
            unit = 5
        else:
            unit = 0

        daily_buffer = 12 if {"transit", "taxi"} & modes else 0
        total = (movement_count * unit + len(itinerary_days) * daily_buffer) * travelers
        return round(total), "category_rule", movement_count

    @staticmethod
    def _combined_segment_source(segments: list[dict[str, Any]]) -> str:
        if any(segment.get("source") == "amap_route" for segment in segments):
            return "amap_route"
        if any(segment.get("source") in {"category_rule", "rule_fallback"} for segment in segments):
            return "category_rule"
        return "unknown_price"

    @staticmethod
    def _average_cost(items: list[dict[str, Any]]) -> float | None:
        costs = []
        for item in items:
            cost = item.get("cost")
            if isinstance(cost, (int, float)) and cost > 0:
                costs.append(float(cost))
        if not costs:
            return None
        return sum(costs) / len(costs)

    @staticmethod
    def _average_cost_by_source(items: list[dict[str, Any]]) -> tuple[float | None, str]:
        for source in ["amap_cost", "ai_price_range", "category_rule", "rule_fallback"]:
            costs = []
            for item in items:
                if item.get("cost_source") != source:
                    continue
                raw_cost = item.get("cost") if source == "amap_cost" else item.get("cost_estimate")
                if isinstance(raw_cost, (int, float)) and raw_cost > 0:
                    costs.append(float(raw_cost))
            if costs:
                return sum(costs) / len(costs), ("category_rule" if source == "rule_fallback" else source)
        return None, "unknown_price"

    @staticmethod
    def _activity_count(itinerary_days: list[dict[str, Any]]) -> int:
        count = 0
        for day in itinerary_days:
            for item in day.get("items", []):
                title = str(item.get("title", ""))
                if any(keyword in title for keyword in ["午餐", "晚餐", "酒店", "抵达", "出发"]):
                    continue
                count += 1
        return max(count, len(itinerary_days))

    def _estimate_intercity_cost(self, prefs: dict[str, Any], routes: dict[str, Any]) -> tuple[int, str]:
        travelers = prefs["travelers"]
        recommended = routes.get("recommended")
        route_text = str(routes.get("raw") or "")

        if recommended == "driving":
            toll_values = [float(value) for value in re.findall(r"过路费约\s*([0-9.]+)\s*元", route_text)]
            if toll_values:
                return round(min(toll_values) * 2), "amap_route"
            distance = prefs.get("estimatedDistanceKm") or 180
            return round(distance * 1.2), "rule_fallback"

        if recommended == "rail":
            ticket = self._average_range_from_text(route_text)
            if ticket:
                return round(ticket * 2 * travelers), "rule_fallback"
            distance = prefs.get("estimatedDistanceKm") or 180
            return round(distance * 0.6 * 2 * travelers), "rule_fallback"

        if recommended == "flight":
            distance = prefs.get("estimatedDistanceKm") or 1000
            one_way = max(450, min(1800, distance * 0.45))
            return round(one_way * 2 * travelers), "rule_fallback"

        return 160 * travelers, "rule_fallback"

    @staticmethod
    def _estimate_local_transport_cost(local_transport: dict[str, Any], days: int, travelers: int) -> tuple[int, str]:
        modes = set(local_transport.get("recommended_modes") or [])
        daily = 40
        if "taxi" in modes and "transit" in modes:
            daily = 80
        elif "taxi" in modes:
            daily = 110
        elif "transit" in modes:
            daily = 35
        elif "driving" in modes:
            daily = 90
        elif modes <= {"walking", "bicycling"}:
            daily = 20
        return daily * days * travelers, "rule_fallback"

    @staticmethod
    def _average_range_from_text(text: str) -> float | None:
        match = re.search(r"约\s*([0-9.]+)\s*[~\-～]\s*([0-9.]+)\s*元", text)
        if match:
            return (float(match.group(1)) + float(match.group(2))) / 2
        match = re.search(r"约\s*([0-9.]+)\s*元", text)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _max_temperature(text: str) -> int | None:
        values = []
        for low, high in re.findall(r"(-?\d+)\s*[~\-～]\s*(-?\d+)\s*°?\s*C", text, re.I):
            values.extend([int(low), int(high)])
        return max(values) if values else None

    @staticmethod
    def _max_wind_level(text: str) -> int | None:
        values = []
        for low, high in re.findall(r"(\d+)\s*[~\-～]\s*(\d+)\s*级", text):
            values.extend([int(low), int(high)])
        for single in re.findall(r"(?<![\d~\-～])([4-9])\s*级", text):
            values.append(int(single))
        return max(values) if values else None

    @staticmethod
    def _parse_money(text: str, pattern: str) -> int | None:
        match = re.search(pattern, text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _category_image_url(category: str, title: str = "") -> str:
        title_text = str(title or "")
        if category == "food":
            label, start, end = "美食", "#f8efe0", "#f7c66b"
        elif category == "transfer":
            label, start, end = "交通", "#e8f2fb", "#75b8e7"
        elif category == "hotel":
            label, start, end = "住宿", "#edf7ef", "#83d2a0"
        elif "夜" in title_text or "晚上" in title_text:
            label, start, end = "夜游", "#e8e7fb", "#9085df"
        else:
            label, start, end = "景点", "#eaf4ee", "#71c49d"
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="{start}"/>
      <stop offset="1" stop-color="{end}"/>
    </linearGradient>
  </defs>
  <rect width="640" height="360" rx="18" fill="url(#bg)"/>
  <circle cx="510" cy="82" r="58" fill="#ffffff" opacity=".28"/>
  <circle cx="118" cy="276" r="82" fill="#ffffff" opacity=".18"/>
  <path d="M80 260 C170 175 240 205 318 128 S470 92 560 172" fill="none" stroke="#ffffff" stroke-width="16" opacity=".42" stroke-linecap="round"/>
  <rect x="48" y="48" width="132" height="48" rx="12" fill="#ffffff" opacity=".88"/>
  <text x="114" y="80" text-anchor="middle" font-family="Microsoft YaHei, Arial, sans-serif" font-size="24" font-weight="700" fill="#185577">{label}</text>
  <text x="48" y="302" font-family="Microsoft YaHei, Arial, sans-serif" font-size="26" font-weight="700" fill="#263241" opacity=".82">TravelMind</text>
</svg>"""
        return "data:image/svg+xml;charset=utf-8," + quote(svg)

    @staticmethod
    def _parse_price_range(value: Any) -> dict[str, Any] | None:
        text = str(value or "").strip()
        if not text:
            return None
        numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text)]
        if not numbers:
            return None
        if len(numbers) == 1:
            low = high = numbers[0]
        else:
            low, high = numbers[0], numbers[1]
            if low > high:
                low, high = high, low
        return {
            "min": round(low),
            "max": round(high),
            "currency": "CNY",
            "unit": "person",
        }

    @staticmethod
    def _price_midpoint(price_range: dict[str, Any] | None) -> int | None:
        if not price_range:
            return None
        try:
            low = float(price_range.get("min"))
            high = float(price_range.get("max"))
        except (TypeError, ValueError):
            return None
        if low < 0 or high < 0:
            return None
        return round((low + high) / 2)

    @staticmethod
    def _normalize_price_confidence(value: Any, default: str = "unknown") -> str:
        text = str(value or "").strip().lower()
        return text if text in {"high", "medium", "low", "unknown"} else default

    @staticmethod
    def _cost_metadata(
        *,
        category: str,
        poi_cost: Any = None,
        fallback_cost: int = 0,
        use_poi_cost: bool = True,
        ai_price_range: dict[str, Any] | None = None,
        ai_price_note: str = "",
        ai_price_confidence: str = "medium",
    ) -> dict[str, Any]:
        has_amap_cost = use_poi_cost and isinstance(poi_cost, (int, float)) and poi_cost > 0
        if has_amap_cost:
            amount = round(float(poi_cost))
            return {
                "cost_estimate": amount,
                "cost_source": "amap_cost",
                "price_range": {"min": amount, "max": amount, "currency": "CNY", "unit": "person"},
                "price_confidence": "high",
                "cost_note": "高德 POI 参考消费，不代表实时票价、库存或可预订价格。",
            }

        ai_midpoint = StructuredTravelPlanner._price_midpoint(ai_price_range)
        if ai_midpoint is not None and ai_midpoint > 0:
            return {
                "cost_estimate": ai_midpoint,
                "cost_source": "ai_price_range",
                "price_range": ai_price_range,
                "price_confidence": StructuredTravelPlanner._normalize_price_confidence(ai_price_confidence, "medium"),
                "cost_note": ai_price_note or "AI 常识估算，需以官方/现场为准。",
            }

        if fallback_cost > 0 and category != "activity":
            return {
                "cost_estimate": fallback_cost,
                "cost_source": "category_rule",
                "price_range": {
                    "min": round(fallback_cost * 0.7),
                    "max": round(fallback_cost * 1.3),
                    "currency": "CNY",
                    "unit": "person" if category != "hotel" else "night",
                },
                "price_confidence": "low",
                "cost_note": "按地点类型规则估算，需以官方/现场为准。",
            }

        if category == "activity":
            return {
                "cost_estimate": 0,
                "cost_source": "free_or_no_ticket_default",
                "price_range": {"min": 0, "max": 0, "currency": "CNY", "unit": "person"},
                "price_confidence": "low",
                "cost_note": "未获取门票价，按无门票/免费项目默认 0 元；出行前仍建议核实官方信息。",
            }

        return {
            "cost_estimate": 0,
            "cost_source": "unknown_price",
            "price_range": None,
            "price_confidence": "unknown",
            "cost_note": "价格待核实，暂无可靠参考。",
        }

    @staticmethod
    def _timeline_item(
        day_number: int,
        slot: str,
        title: str,
        location_name: str,
        transport: str,
        duration: str,
        detail: str,
        category: str,
        poi: dict[str, Any] | None = None,
        fallback_cost: int = 0,
        *,
        place_source: str | None = None,
        is_real_place: bool | None = None,
        use_poi_cost: bool = True,
        validation_note: str = "",
        ai_price_range: dict[str, Any] | None = None,
        ai_price_note: str = "",
        ai_price_confidence: str = "medium",
    ) -> dict[str, Any]:
        poi = poi or {}
        poi_cost = poi.get("cost")
        cost_meta = StructuredTravelPlanner._cost_metadata(
            category=category,
            poi_cost=poi_cost,
            fallback_cost=fallback_cost,
            use_poi_cost=use_poi_cost,
            ai_price_range=ai_price_range,
            ai_price_note=ai_price_note,
            ai_price_confidence=ai_price_confidence,
        )
        item_id = StructuredTravelPlanner._make_item_id(f"day{day_number}-{slot}", 1, title)
        photo_url = str(poi.get("photo_url") or "").strip()
        has_poi = bool(poi.get("name") or poi.get("id"))
        source = place_source or ("amap_poi" if has_poi else "planning_note")
        real_place = bool(has_poi) if is_real_place is None else bool(is_real_place)
        location_source = "missing"
        if poi.get("location"):
            location_source = source if source in {"hotel_poi", "transport_hub"} else "amap_poi"
        return {
            "id": item_id,
            "poi_id": poi.get("id", ""),
            "time": slot,
            "title": title,
            "location": location_name or poi.get("name", ""),
            "address": poi.get("address", ""),
            "transport": transport,
            "duration": duration,
            "detail": detail,
            "category": category,
            "rating": poi.get("rating"),
            "cost": poi_cost,
            "cost_estimate": cost_meta["cost_estimate"],
            "cost_source": cost_meta["cost_source"],
            "price_range": cost_meta["price_range"],
            "price_confidence": cost_meta["price_confidence"],
            "cost_note": cost_meta["cost_note"],
            "type": poi.get("type", ""),
            "cluster_id": poi.get("cluster_id", ""),
            "cluster_name": poi.get("cluster_name", ""),
            "nearby_anchor": poi.get("nearby_anchor", ""),
            "location_point": poi.get("location"),
            "location_source": location_source,
            "map_label": "",
            "map_included": False,
            "photo_url": photo_url or StructuredTravelPlanner._category_image_url(category, title),
            "image_source": "amap_photo" if photo_url else "category_fallback",
            "is_real_place": real_place,
            "place_source": source,
            "validation_note": validation_note,
        }

    @staticmethod
    def _note_item(day_number: int, slot: str, title: str, detail: str) -> dict[str, Any]:
        item_id = StructuredTravelPlanner._make_item_id(f"day{day_number}-{slot}", 1, title)
        return {
            "id": item_id,
            "poi_id": "",
            "time": slot,
            "title": title,
            "location": "",
            "address": "",
            "transport": "",
            "duration": "",
            "detail": detail,
            "category": "note",
            "rating": None,
            "cost": None,
            "cost_estimate": 0,
            "cost_source": "unknown_price",
            "price_range": None,
            "price_confidence": "unknown",
            "cost_note": "说明项不计入预算，具体消费待现场核实。",
            "type": "",
            "location_point": None,
            "location_source": "missing",
            "map_label": "",
            "map_included": False,
            "photo_url": StructuredTravelPlanner._category_image_url("activity", title),
            "image_source": "category_fallback",
            "is_real_place": False,
            "place_source": "planning_note",
            "validation_note": "",
        }

    @staticmethod
    def _poi_key(poi: dict[str, Any]) -> str:
        name = str(poi.get("name") or "").strip()
        key = re.sub(r"[\s·,，:：；;（）()]+", "", name)
        for suffix in ["体育公园", "森林公园", "湿地公园", "风景名胜区", "风景区", "景区", "公园"]:
            if len(key) > len(suffix) + 1 and key.endswith(suffix):
                key = key[: -len(suffix)]
                break
        return key or str(poi.get("id") or "").strip()

    @staticmethod
    def _dedupe_pois(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        deduped = []
        seen = set()
        for item in items or []:
            if not item.get("name"):
                continue
            if not StructuredTravelPlanner._has_real_place_signal(item):
                continue
            key = StructuredTravelPlanner._poi_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _has_real_place_signal(poi: dict[str, Any]) -> bool:
        return bool(
            poi.get("location")
            or poi.get("address")
            or poi.get("rating")
            or poi.get("type")
            or poi.get("photo_url")
        )

    @staticmethod
    def _take_unused_poi(candidates: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
        for poi in candidates:
            key = StructuredTravelPlanner._poi_key(poi)
            poi_id = str(poi.get("id") or "")
            if not key or key in used or (poi_id and poi_id in used):
                continue
            used.add(key)
            if poi_id:
                used.add(poi_id)
            return poi
        return None

    @staticmethod
    def _take_unused_poi_for_cluster(
        candidates: list[dict[str, Any]],
        used: set[str],
        cluster_id: str | None = None,
    ) -> dict[str, Any] | None:
        target = str(cluster_id or "")
        if not target:
            return StructuredTravelPlanner._take_unused_poi(candidates, used)

        same_cluster = [poi for poi in candidates if str(poi.get("cluster_id") or "") == target]
        missing_cluster = [poi for poi in candidates if not poi.get("cluster_id")]
        other_cluster = [
            poi
            for poi in candidates
            if str(poi.get("cluster_id") or "") not in {"", target}
        ]
        return StructuredTravelPlanner._take_unused_poi([*same_cluster, *missing_cluster, *other_cluster], used)

    @staticmethod
    def _cluster_preference_order(
        activity_candidates: list[dict[str, Any]],
        foods: list[dict[str, Any]],
        hotel_poi: dict[str, Any] | None,
    ) -> list[str]:
        scores: dict[str, float] = {}

        def add(item: dict[str, Any] | None, weight: float) -> None:
            cluster_id = str((item or {}).get("cluster_id") or "")
            if cluster_id:
                scores[cluster_id] = scores.get(cluster_id, 0) + weight

        add(hotel_poi, 2.0)
        for item in activity_candidates:
            add(item, 3.0)
        for item in foods:
            add(item, 1.0)
        return [cluster_id for cluster_id, _ in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)]

    def _build_deepseek_itinerary_days(
        self,
        prefs: dict[str, Any],
        routes: dict[str, Any],
        local_transport: dict[str, Any],
        hotels: dict[str, Any],
        pois: dict[str, Any],
        weather: dict[str, str],
        weather_advice: dict[str, str],
    ) -> dict[str, Any]:
        payload, lookup = self._planning_brain_payload(prefs, routes, local_transport, hotels, pois, weather, weather_advice)
        brain_result = self.deepseek_brain.plan(payload)
        if brain_result.get("llm_status") != "used":
            return {
                "llm_status": brain_result.get("llm_status", "fallback"),
                "planning_mode": "rule_fallback",
                "reason": brain_result.get("reason", "DeepSeek unavailable"),
                "itinerary_days": [],
            }

        itinerary_days = self._materialize_llm_itinerary(
            brain_result.get("plan") or {},
            prefs,
            routes,
            local_transport,
            hotels,
            lookup,
        )
        item_count = sum(len(day.get("items", [])) for day in itinerary_days)
        if item_count < max(2, prefs["days"] * 2):
            return {
                "llm_status": "parse_failed",
                "planning_mode": "rule_fallback",
                "reason": "DeepSeek itinerary did not contain enough usable items",
                "itinerary_days": [],
            }

        return {
            "llm_status": "used",
            "planning_mode": "deepseek_hybrid",
            "reason": "DeepSeek generated itinerary from AMap candidates",
            "itinerary_days": itinerary_days,
        }

    def _review_and_repair_itinerary(
        self,
        prefs: dict[str, Any],
        routes: dict[str, Any],
        local_transport: dict[str, Any],
        hotels: dict[str, Any],
        pois: dict[str, Any],
        weather: dict[str, str],
        weather_advice: dict[str, str],
        itinerary_days: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload, lookup = self._planning_brain_payload(prefs, routes, local_transport, hotels, pois, weather, weather_advice)
        payload["current_itinerary"] = self._compact_itinerary_for_review(itinerary_days)
        payload["quality_targets"] = {
            "pace": (prefs.get("preferenceProfile") or {}).get("pace"),
            "max_transfer_minutes": (prefs.get("preferenceProfile") or {}).get("maxTransferMinutes"),
            "hotel_strategy": (prefs.get("preferenceProfile") or {}).get("hotelStrategy"),
            "learned_hints": (prefs.get("preferenceProfile") or {}).get("learnedHints", []),
        }

        result = self.deepseek_brain.review_itinerary(payload)
        if result.get("llm_status") != "used":
            return {"itinerary_days": itinerary_days, "quality_review": self._rule_quality_review(prefs, itinerary_days)}

        review = self._normalize_quality_review(result.get("review"), "deepseek")
        repaired_days = itinerary_days
        raw_review = result.get("review") if isinstance(result.get("review"), dict) else {}
        repaired_plan = raw_review.get("repaired_plan") if isinstance(raw_review.get("repaired_plan"), dict) else None
        if raw_review.get("needs_repair") and repaired_plan:
            if self._repair_plan_uses_known_candidates(repaired_plan, lookup):
                candidate_days = self._materialize_llm_itinerary(
                    repaired_plan,
                    prefs,
                    routes,
                    local_transport,
                    hotels,
                    lookup,
                )
                if sum(len(day.get("items", [])) for day in candidate_days) >= max(2, prefs["days"] * 2):
                    repaired_days = candidate_days
                    self._apply_preference_safety_to_itinerary(prefs, repaired_days)
                    review["fixes"].append("已按智能体检结果完成一次受控返工。")
                    review["repaired"] = True
                else:
                    review["issues"].append(
                        {
                            "severity": "medium",
                            "day": None,
                            "message": "DeepSeek 建议返工，但返工结果可用项目不足，已保留原行程。",
                            "kind": "logic",
                        }
                    )
            else:
                review["issues"].append(
                    {
                        "severity": "medium",
                        "day": None,
                        "message": "DeepSeek 建议返工，但包含未授权或不存在的候选地点，已拒绝本次返工。",
                        "kind": "logic",
                    }
                )
        self._assign_day_primary_clusters(repaired_days)
        if not review["issues"]:
            rule_review = self._rule_quality_review(prefs, repaired_days)
            review["issues"] = rule_review.get("issues", [])
        review["constraints"] = self._evaluate_constraint_results(prefs, repaired_days)
        return {"itinerary_days": repaired_days, "quality_review": review}

    @staticmethod
    def _repair_plan_uses_known_candidates(plan: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> bool:
        raw_days = plan.get("days") if isinstance(plan.get("days"), list) else []
        for raw_day in raw_days:
            if not isinstance(raw_day, dict):
                continue
            raw_items = raw_day.get("items") if isinstance(raw_day.get("items"), list) else []
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                category = StructuredTravelPlanner._normalize_llm_category(raw_item.get("category"))
                if category in {"activity", "food", "hotel"}:
                    candidate_id = str(raw_item.get("candidate_id") or raw_item.get("poi_id") or "").strip()
                    if not candidate_id or candidate_id not in lookup:
                        return False
        return True

    @staticmethod
    def _compact_itinerary_for_review(itinerary_days: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact_days = []
        for day in itinerary_days:
            compact_days.append(
                {
                    "day": day.get("day"),
                    "theme": day.get("theme"),
                    "primary_cluster": day.get("primary_cluster"),
                    "items": [
                        {
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "category": item.get("category"),
                            "location": item.get("location"),
                            "transport": item.get("transport"),
                            "duration": item.get("duration"),
                            "cluster_id": item.get("cluster_id"),
                            "cluster_name": item.get("cluster_name"),
                            "place_source": item.get("place_source"),
                            "detail": str(item.get("detail") or "")[:120],
                        }
                        for item in day.get("items", [])
                    ],
                }
            )
        return compact_days

    @staticmethod
    def _normalize_quality_review(value: Any, source: str) -> dict[str, Any]:
        raw = value if isinstance(value, dict) else {}

        def score(key: str, default: int = 80) -> int:
            try:
                return max(0, min(int(raw.get(key, default)), 100))
            except (TypeError, ValueError):
                return default

        issues = raw.get("issues") if isinstance(raw.get("issues"), list) else []
        normalized_issues = []
        for issue in issues[:8]:
            if not isinstance(issue, dict):
                continue
            severity = str(issue.get("severity") or "medium")
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            normalized_issues.append(
                {
                    "severity": severity,
                    "day": issue.get("day"),
                    "message": str(issue.get("message") or issue.get("reason") or "").strip(),
                    "kind": str(issue.get("kind") or "logic"),
                }
            )
        fixes = [str(item).strip() for item in raw.get("fixes", []) if str(item).strip()] if isinstance(raw.get("fixes"), list) else []
        return {
            "overall_score": score("overall_score"),
            "route_score": score("route_score"),
            "pace_score": score("pace_score"),
            "cluster_score": score("cluster_score"),
            "logic_score": score("logic_score"),
            "issues": normalized_issues,
            "fixes": fixes[:8],
            "source": source,
            "repaired": False,
        }

    @classmethod
    def _evaluate_constraint_results(
        cls,
        prefs: dict[str, Any],
        itinerary_days: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        summary = prefs.get("constraintSummary") or {}
        results: list[dict[str, Any]] = []
        for group in ["hard", "soft", "unknown"]:
            for constraint in summary.get(group, []):
                text = str(constraint.get("text") or "").strip()
                if not text:
                    continue
                kind = str(constraint.get("kind") or group)
                status = "unknown"
                evidence = "约束已记录，当前结构化事实不足以完成验证。"

                if constraint.get("field") == "pace":
                    status = "satisfied"
                    evidence = f"已使用旅行节奏：{(prefs.get('preferenceProfile') or {}).get('pace', '标准')}。"
                elif constraint.get("field") == "hotelStrategy":
                    status = "satisfied"
                    evidence = f"已使用住宿策略：{(prefs.get('preferenceProfile') or {}).get('hotelStrategy', '近地铁枢纽')}。"
                elif any(marker in text for marker in ["夜间", "晚上"]):
                    night_activities = [
                        item
                        for day in itinerary_days
                        for item in day.get("items", [])
                        if item.get("time") == "夜间" and item.get("category") == "activity"
                    ]
                    if any(marker in text for marker in ["不要", "不安排", "避免", "仅"]):
                        status = "violated" if night_activities else "satisfied"
                        evidence = f"夜间活动项目数：{len(night_activities)}。"
                else:
                    count_match = re.search(r"最多\s*(\d+)\s*(?:个)?(?:真实)?(?:地点|景点|活动)", text)
                    if count_match:
                        limit = int(count_match.group(1))
                        counts = [
                            sum(
                                1
                                for item in day.get("items", [])
                                if item.get("category") in {"activity", "food", "hotel"}
                                and item.get("is_real_place")
                            )
                            for day in itinerary_days
                        ]
                        status = "satisfied" if all(count <= limit for count in counts) else "violated"
                        evidence = f"每日真实地点数：{counts}；上限：{limit}。"
                    else:
                        minute_match = re.search(r"(\d+)\s*分钟", text)
                        segments = [
                            item.get("arrival_transport_segment")
                            for day in itinerary_days
                            for item in day.get("items", [])
                            if isinstance(item.get("arrival_transport_segment"), dict)
                        ]
                        if minute_match and segments:
                            limit = int(minute_match.group(1))
                            durations = [cls._local_duration_minutes(segment) for segment in segments]
                            durations = [duration for duration in durations if duration > 0]
                            if durations:
                                status = "satisfied" if max(durations) <= limit else "violated"
                                evidence = f"已观测路线耗时：{durations} 分钟；上限：{limit} 分钟。"
                        elif "室内" in text and any(marker in text for marker in ["只", "仅", "不要", "避免"]):
                            activity_items = [
                                item
                                for day in itinerary_days
                                for item in day.get("items", [])
                                if item.get("category") == "activity"
                            ]
                            outdoor_items = [
                                item
                                for item in activity_items
                                if any(marker in " ".join(str(item.get(key) or "") for key in ["title", "location", "detail"]) for marker in ["公园", "海边", "滨水", "骑行", "户外"])
                            ]
                            if activity_items:
                                status = "violated" if outdoor_items else "satisfied"
                                evidence = f"活动项目数：{len(activity_items)}；识别为室外的项目数：{len(outdoor_items)}。"

                results.append(
                    {
                        "id": str(constraint.get("id") or f"{kind}-{len(results) + 1}"),
                        "kind": kind,
                        "text": text,
                        "source": str(constraint.get("source") or "unknown"),
                        "status": status,
                        "evidence": evidence,
                    }
                )
        return results

    def _rule_quality_review(self, prefs: dict[str, Any], itinerary_days: list[dict[str, Any]]) -> dict[str, Any]:
        issues = []
        max_transfer = int((prefs.get("preferenceProfile") or {}).get("maxTransferMinutes") or 45)
        for day in itinerary_days:
            clusters = [item.get("cluster_id") for item in day.get("items", []) if item.get("cluster_id")]
            if len(set(clusters)) > 2:
                issues.append(
                    {
                        "severity": "medium",
                        "day": day.get("day"),
                        "message": "当天跨越多个片区，建议压缩到一个主片区和一个相邻片区。",
                        "kind": "cluster",
                    }
                )
            places = [self._segment_place(item) for item in day.get("items", [])]
            places = [place for place in places if place]
            for previous, current in zip(places, places[1:]):
                distance = self._point_distance_km(previous["point"], current["point"])
                if distance > max(12, max_transfer * 0.7):
                    issues.append(
                        {
                            "severity": "high" if distance > 35 else "medium",
                            "day": day.get("day"),
                            "message": f"{previous['detail']} 到 {current['detail']} 距离约 {self._format_local_distance(distance)}，需重点校验交通体验。",
                            "kind": "route",
                        }
                    )
        route_score = 92 - 12 * sum(1 for item in issues if item["kind"] == "route")
        cluster_score = 92 - 10 * sum(1 for item in issues if item["kind"] == "cluster")
        logic_score = 88
        pace_score = 88 if (prefs.get("preferenceProfile") or {}).get("pace") != "轻松" else 92
        scores = [route_score, cluster_score, logic_score, pace_score]
        return {
            "overall_score": max(0, min(round(sum(scores) / len(scores)), 100)),
            "route_score": max(0, min(route_score, 100)),
            "pace_score": max(0, min(pace_score, 100)),
            "cluster_score": max(0, min(cluster_score, 100)),
            "logic_score": logic_score,
            "issues": issues[:8],
            "fixes": [],
            "constraints": self._evaluate_constraint_results(prefs, itinerary_days),
            "source": "rule_fallback",
            "repaired": False,
        }

    @staticmethod
    def _apply_preference_safety_to_itinerary(prefs: dict[str, Any], itinerary_days: list[dict[str, Any]]) -> None:
        profile = prefs.get("preferenceProfile") or {}
        hints = " ".join(profile.get("learnedHints") or [])
        relaxed = profile.get("pace") == "轻松" or any(keyword in hints for keyword in ["别太赶", "轻松"])
        if not relaxed:
            return

        for day in itinerary_days:
            items = day.get("items")
            if not isinstance(items, list):
                continue
            while len(items) > 4:
                removable_index = None
                for index in range(len(items) - 1, -1, -1):
                    item = items[index]
                    if item.get("category") in {"transfer", "hotel"}:
                        continue
                    if item.get("time") == "夜间" or item.get("category") in {"note", "activity"}:
                        removable_index = index
                        break
                if removable_index is None:
                    for index in range(len(items) - 1, -1, -1):
                        if items[index].get("category") != "transfer":
                            removable_index = index
                            break
                if removable_index is None:
                    break
                items.pop(removable_index)

    @staticmethod
    def _assign_day_primary_clusters(itinerary_days: list[dict[str, Any]]) -> None:
        for day in itinerary_days:
            counts: dict[str, dict[str, Any]] = {}
            for item in day.get("items", []):
                cluster_id = str(item.get("cluster_id") or "")
                if not cluster_id:
                    continue
                if cluster_id not in counts:
                    counts[cluster_id] = {
                        "cluster_id": cluster_id,
                        "cluster_name": item.get("cluster_name") or cluster_id,
                        "nearby_anchor": item.get("nearby_anchor") or "",
                        "count": 0,
                    }
                counts[cluster_id]["count"] += 1
            if counts:
                primary = max(counts.values(), key=lambda item: item["count"])
                day["primary_cluster"] = {
                    "cluster_id": primary["cluster_id"],
                    "cluster_name": primary["cluster_name"],
                    "nearby_anchor": primary["nearby_anchor"],
                }
            else:
                day["primary_cluster"] = None

    @staticmethod
    def _candidate_exclusion_terms(prefs: dict[str, Any]) -> list[str]:
        terms: list[str] = []
        summary = prefs.get("constraintSummary") or {}
        raw_values = [entry.get("text") for entry in summary.get("hard", []) if isinstance(entry, dict)]
        for value in raw_values:
            for part in re.split(r"[，,；;。！？!?]+", str(value or "")):
                text = part.strip()
                if not text or not re.search(r"不要|不安排|避免|不去|不住|不坐|排除|禁止", text):
                    continue
                text = re.sub(r"^(?:不要|不安排|避免|不去|不住|不坐|排除|禁止)", "", text).strip()
                text = re.sub(r"^(?:安排|选择|前往|住在|乘坐)", "", text).strip()
                if text:
                    terms.append(text)
        return list(dict.fromkeys(terms))

    @staticmethod
    def _legacy_fact_status(value: Any, default: str = "unknown") -> str:
        text = str(value or "")
        if "fixture" in text.lower():
            return "fixture"
        if "失败" in text or "降级" in text or "fallback" in text.lower():
            return "amap_fallback"
        return "live" if text.strip() else default

    def _build_candidate_contracts(
        self,
        prefs: dict[str, Any],
        pois: dict[str, Any],
        hotels: dict[str, Any],
        weather: dict[str, str],
    ) -> dict[str, Any]:
        """Build ranked candidates while leaving legacy output fields untouched."""

        city = prefs["destinationCity"]
        exclusions = self._candidate_exclusion_terms(prefs)
        weather_text = " ".join(str(value or "") for value in (weather or {}).values())
        seen_keys: set[str] = set()

        hotel_raw = normalize_place_candidates(
            hotels.get("candidates"),
            city=city,
            category="hotel",
            source="hotel_poi",
            provider_status=str(hotels.get("provider_status") or self._legacy_fact_status(hotels.get("raw"))),
        )
        hotel_result = rank_candidates(
            hotel_raw,
            expected_city=city,
            preferences=prefs,
            excluded_terms=exclusions,
            seen_keys=seen_keys,
            require_coordinates=True,
            require_real_place=True,
            limit=6,
        )
        hotels_selected = hotel_result["selected"]
        for candidate in hotels_selected:
            key = candidate_key(candidate)
            if key:
                seen_keys.add(key)
        hotel_anchor = hotels_selected[0].get("location") if hotels_selected else None

        rejected: dict[str, list[dict[str, Any]]] = {}

        def rank_group(group_name: str, raw_items: list[dict[str, Any]] | None, limit: int) -> list[dict[str, Any]]:
            normalized = normalize_place_candidates(
                raw_items,
                city=city,
                category="food" if group_name == "foods" else "activity",
                source="amap_poi",
                provider_status=self._legacy_fact_status(pois.get("raw")),
            )
            result = rank_candidates(
                normalized,
                expected_city=city,
                preferences=prefs,
                excluded_terms=exclusions,
                seen_keys=seen_keys,
                require_coordinates=True,
                require_real_place=True,
                anchor=hotel_anchor,
                weather=weather_text,
                limit=limit,
            )
            rejected[group_name] = result["rejected"]
            for candidate in result["selected"]:
                key = candidate_key(candidate)
                if key:
                    seen_keys.add(key)
            return result["selected"]

        return {
            "version": "travelmind-candidate-v1",
            "source_mode": "legacy_text_compatible",
            "pois": {
                "attractions": rank_group("attractions", pois.get("attractions"), 12),
                "specialty_places": rank_group("specialty_places", pois.get("specialty_places"), 8),
                "foods": rank_group("foods", pois.get("foods"), 12),
            },
            "hotels": hotels_selected,
            "rejected": {
                **rejected,
                "hotels": hotel_result["rejected"],
            },
            "notes": [
                "候选由旧文本事实归一化而来；结构化 MCP 返回仍未切换。",
                "无有效坐标或非真实地点候选不会进入规划脑候选集合。",
            ],
        }

    def _planning_brain_payload(
        self,
        prefs: dict[str, Any],
        routes: dict[str, Any],
        local_transport: dict[str, Any],
        hotels: dict[str, Any],
        pois: dict[str, Any],
        weather: dict[str, str],
        weather_advice: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        candidates = []
        lookup: dict[str, dict[str, Any]] = {}
        contract_pois = pois.get("candidate_contracts") if isinstance(pois.get("candidate_contracts"), dict) else {}
        contract_hotels = hotels.get("candidate_contracts") if isinstance(hotels.get("candidate_contracts"), list) else None

        def candidate_group(group_name: str, fallback: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
            if group_name in contract_pois:
                return list(contract_pois.get(group_name) or [])
            return self._dedupe_pois(fallback)

        groups = [
            ("activity", "amap_poi", candidate_group("attractions", pois.get("attractions"))[:12]),
            ("activity", "amap_poi", candidate_group("specialty_places", pois.get("specialty_places"))[:8]),
            ("food", "amap_poi", candidate_group("foods", pois.get("foods"))[:12]),
            ("hotel", "hotel_poi", (contract_hotels if contract_hotels is not None else self._dedupe_pois(hotels.get("candidates")))[:6]),
        ]
        for category, place_source, items in groups:
            for item in items:
                if not item.get("id") or not item.get("name"):
                    continue
                enriched = dict(item)
                enriched["_candidate_category"] = category
                enriched["_place_source"] = place_source
                lookup[str(item["id"])] = enriched
                candidates.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "category": category,
                        "address": item.get("address", ""),
                        "rating": item.get("rating"),
                        "cost": item.get("cost") if item.get("cost_source") == "amap_cost" else None,
                        "cost_source": item.get("cost_source") or "unknown_price",
                        "price_range": item.get("price_range"),
                        "price_note": item.get("cost_note") or "",
                        "type": item.get("type", ""),
                        "location": item.get("location"),
                        "source": item.get("source") or place_source,
                        "source_meta": item.get("source_meta") or {},
                        "is_real_place": bool(item.get("is_real_place")),
                        "is_suggestion": bool(item.get("is_suggestion")),
                        "validation": item.get("validation") or {},
                        "selection": item.get("selection") or {},
                        "description": str(item.get("description") or "")[:160],
                        "cluster_id": item.get("cluster_id", ""),
                        "cluster_name": item.get("cluster_name", ""),
                        "nearby_anchor": item.get("nearby_anchor", ""),
                    }
                )

        constraint_summary = prefs.get("constraintSummary") or {}
        constraint_lines = [
            f"{entry.get('kind', 'unknown')}: {entry.get('text', '')}"
            for group in ["hard", "soft", "unknown"]
            for entry in constraint_summary.get(group, [])
            if entry.get("text")
        ]
        payload = {
            "preferences": prefs,
            "intercity_transport": {
                "recommended": routes.get("recommended"),
                "options": [
                    {
                        "mode": option.get("mode"),
                        "title": option.get("title"),
                        "summary": option.get("summary"),
                        "warning": option.get("warning"),
                    }
                    for option in routes.get("options", [])
                ],
            },
            "local_transport": local_transport,
            "hotel_area": hotels.get("area_recommendation", ""),
            "weather": weather,
            "weather_advice": weather_advice,
            "candidates": candidates,
            "constraint_summary": constraint_summary,
            "cluster_guidance": [
                "每天优先围绕 1 个 primary_cluster 安排活动，最多补充 1 个相邻片区",
                "不要把相距很远的 cluster 硬排在同一天相邻时段",
                "餐饮优先匹配当天主片区或酒店片区",
            ],
            "constraints": [
                "真实地点必须使用 candidate_id",
                "可以给少量泛化体验建议，但 is_suggestion 必须为 true",
                "不要编造航班号、车次、实时票价、余票、酒店库存或门票库存",
                "最后一天返程交通只作为 transfer，不要把住宿区域建议写进返程 item 的 location 或 detail",
                "高德没有 cost 的景点/活动，只有明确可能收费时才输出正价 estimated_price_range；免费开放或无法判断收费时输出 0-0，并标注需核实",
                *constraint_lines,
            ],
        }
        return payload, lookup

    def _materialize_llm_itinerary(
        self,
        plan: dict[str, Any],
        prefs: dict[str, Any],
        routes: dict[str, Any],
        local_transport: dict[str, Any],
        hotels: dict[str, Any],
        lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raw_days = plan.get("days") if isinstance(plan.get("days"), list) else []
        day_lookup = {}
        for raw_day in raw_days:
            if isinstance(raw_day, dict):
                day_number = self._bounded_int(raw_day.get("day"), len(day_lookup) + 1, 1, prefs["days"])
                day_lookup[day_number] = raw_day

        current_date = self._parse_date(prefs["startDate"])
        recommended_local = "、".join(MODE_LABELS.get(mode, mode) for mode in local_transport.get("recommended_modes", []))
        hotel_area = hotels.get("area_recommendation") or self._default_hotel_area(prefs)
        used_real: set[str] = set()
        materialized_days = []

        for day_number in range(1, prefs["days"] + 1):
            raw_day = day_lookup.get(day_number, {})
            date_text = (current_date + timedelta(days=day_number - 1)).isoformat() if current_date else ""
            theme = str(raw_day.get("theme") or ("抵达适应 + 城市体验" if day_number == 1 else f"{prefs['destinationCity']}深度体验"))
            raw_items = raw_day.get("items") if isinstance(raw_day.get("items"), list) else []
            items = []

            for index, raw_item in enumerate(raw_items[: len(TIME_SLOTS)]):
                if not isinstance(raw_item, dict):
                    continue
                slot = TIME_SLOTS[index] if index < len(TIME_SLOTS) else f"第 {index + 1} 段"
                category = self._normalize_llm_category(raw_item.get("category"))
                is_return_transfer = self._is_return_transfer_raw_item(raw_item, category, prefs, day_number)
                candidate = self._find_llm_candidate(raw_item, lookup)
                is_suggestion = bool(raw_item.get("is_suggestion")) or candidate is None
                if candidate and category in {"activity", "food"}:
                    key = self._poi_key(candidate)
                    candidate_id = str(candidate.get("id") or "")
                    if key in used_real or (candidate_id and candidate_id in used_real):
                        candidate = None
                        is_suggestion = True
                    else:
                        used_real.add(key)
                        if candidate_id:
                            used_real.add(candidate_id)

                if candidate and not is_suggestion:
                    candidate_category = candidate.get("_candidate_category") or category
                    item_category = category if category in {"transfer", "hotel"} else candidate_category
                    if item_category not in {"activity", "food", "hotel", "transfer"}:
                        item_category = candidate_category
                    title = str(raw_item.get("title") or f"{candidate['name']}体验")
                    detail = str(raw_item.get("detail") or candidate.get("description") or "根据 DeepSeek 智能规划，从高德候选中选择的真实地点。")
                    ai_price_range = self._parse_price_range(raw_item.get("estimated_price_range"))
                    item = self._timeline_item(
                        day_number,
                        slot,
                        title,
                        candidate.get("name", ""),
                        self._display_transport_text(raw_item.get("transport") or recommended_local or "步行/打车"),
                        str(raw_item.get("duration") or "1-2 小时"),
                        detail,
                        item_category,
                        candidate,
                        self._fallback_cost_for_category(item_category),
                        place_source=candidate.get("_place_source") or "amap_poi",
                        is_real_place=True,
                        use_poi_cost=item_category not in {"hotel", "transfer"},
                        validation_note="DeepSeek 已从高德候选中绑定真实地点。",
                        ai_price_range=ai_price_range,
                        ai_price_note=str(raw_item.get("price_note") or ""),
                        ai_price_confidence=str(raw_item.get("price_confidence") or "medium"),
                    )
                else:
                    item = self._llm_suggestion_item(
                        day_number,
                        slot,
                        raw_item,
                        category,
                        hotel_area,
                        prefs,
                    )
                if is_return_transfer:
                    self._normalize_return_transfer_item(item, raw_item, prefs, routes)
                items.append(item)

            materialized_days.append(
                {
                    "day": day_number,
                    "date": date_text,
                    "theme": theme,
                    "weather_note": "",
                    "items": items,
                }
            )
        return materialized_days

    @staticmethod
    def _normalize_llm_category(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"food", "restaurant", "meal", "lunch", "dinner"}:
            return "food"
        if text in {"hotel", "stay"}:
            return "hotel"
        if text in {"transfer", "transport"}:
            return "transfer"
        if text in {"note", "suggestion"}:
            return "activity"
        return "activity"

    @staticmethod
    def _display_transport_text(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        lowered = raw.lower()
        if lowered in MODE_LABELS:
            return MODE_LABELS[lowered]
        if raw in INTERCITY_MODE_MAP:
            return MODE_LABELS.get(INTERCITY_MODE_MAP[raw], raw)
        if raw in LOCAL_MODE_MAP:
            return MODE_LABELS.get(LOCAL_MODE_MAP[raw], raw)
        return raw

    @staticmethod
    def _is_return_transfer_raw_item(raw_item: dict[str, Any], category: str, prefs: dict[str, Any], day_number: int) -> bool:
        if category != "transfer":
            return False
        text = " ".join(str(raw_item.get(key) or "") for key in ["title", "location", "transport", "duration", "detail"])
        origin = str(prefs.get("originCity") or "")
        if origin and origin in text:
            return True
        return day_number == prefs.get("days") and any(keyword in text for keyword in ["返程", "返回", "回程", "回到", "返家", "回家"])

    @classmethod
    def _normalize_return_transfer_item(
        cls,
        item: dict[str, Any],
        raw_item: dict[str, Any],
        prefs: dict[str, Any],
        routes: dict[str, Any],
    ) -> None:
        title = str(item.get("title") or raw_item.get("title") or "")
        route_location = cls._return_transfer_location(title, raw_item, prefs, routes)
        item["category"] = "transfer"
        item["location"] = route_location
        item["address"] = ""
        item["transport"] = cls._display_transport_text(raw_item.get("transport") or routes.get("recommended") or item.get("transport"))
        if cls._looks_like_lodging_text(item.get("detail")):
            item["detail"] = cls._default_return_transfer_detail(raw_item, prefs, routes)
        item["place_source"] = "transport_note"
        item["location_source"] = "missing"
        item["location_point"] = None
        item["map_included"] = False
        item["is_real_place"] = False
        item["validation_note"] = "返程交通说明，不作为目的地住宿或景点安排。"

    @classmethod
    def _return_transfer_location(
        cls,
        title: str,
        raw_item: dict[str, Any],
        prefs: dict[str, Any],
        routes: dict[str, Any],
    ) -> str:
        text = str(raw_item.get("location") or title or "").strip()
        if cls._looks_like_lodging_text(text):
            text = title
        route_match = re.search(r"(.+?)\s*(?:->|→|到|至)\s*(.+?)(?:（|\(|，|,|。|$)", text)
        if route_match:
            return f"{route_match.group(1).strip()} → {route_match.group(2).strip()}"
        for option in routes.get("options", []):
            if option.get("mode") == routes.get("recommended"):
                origin_detail = option.get("destination_detail") or f"{prefs.get('destinationCity', '')}车站"
                destination_detail = option.get("origin_detail") or f"{prefs.get('originCity', '')}车站"
                return f"{origin_detail} → {destination_detail}"
        return f"{prefs.get('destinationCity', '')} → {prefs.get('originCity', '')}"

    @staticmethod
    def _looks_like_lodging_text(value: Any) -> bool:
        text = str(value or "")
        lodging_markers = ["建议优先住在", "住宿区域", "住宿参考", "酒店", "周边，减少换乘", "寄存行李"]
        return any(marker in text for marker in lodging_markers)

    @classmethod
    def _default_return_transfer_detail(cls, raw_item: dict[str, Any], prefs: dict[str, Any], routes: dict[str, Any]) -> str:
        detail = str(raw_item.get("detail") or "").strip()
        if detail and not cls._looks_like_lodging_text(detail):
            return detail
        mode_label = MODE_LABELS.get(routes.get("recommended"), routes.get("recommended", "高铁/动车/城际"))
        return f"按{mode_label}返回{prefs.get('originCity', '出发城市')}，这是返程交通安排，不需要再安排目的地住宿。"

    @staticmethod
    def _fallback_cost_for_category(category: str) -> int:
        return {"food": 80, "activity": 0, "hotel": 0, "transfer": 0}.get(category, 0)

    @staticmethod
    def _find_llm_candidate(raw_item: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        candidate_id = str(raw_item.get("candidate_id") or raw_item.get("poi_id") or "").strip()
        if candidate_id and candidate_id in lookup:
            return lookup[candidate_id]
        candidate_name = str(raw_item.get("candidate_name") or raw_item.get("location") or raw_item.get("title") or "").strip()
        normalized_name = re.sub(r"\s+", "", candidate_name)
        if not normalized_name:
            return None
        for item in lookup.values():
            name = re.sub(r"\s+", "", str(item.get("name") or ""))
            if name and (name in normalized_name or normalized_name in name):
                return item
        return None

    def _llm_suggestion_item(
        self,
        day_number: int,
        slot: str,
        raw_item: dict[str, Any],
        category: str,
        hotel_area: str,
        prefs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = str(raw_item.get("title") or "DeepSeek 待确认建议")
        detail = str(raw_item.get("detail") or "这是 DeepSeek 根据偏好给出的泛化体验建议，需结合现场位置和营业情况确认。")
        note = str(raw_item.get("validation_note") or "DeepSeek 建议，未绑定高德真实 POI，需现场确认。")
        item_id = self._make_item_id(f"day{day_number}-{slot}", 1, title)
        item_category = category if category in {"activity", "food", "hotel", "transfer"} else "activity"
        if item_category == "transfer":
            location = str(raw_item.get("location") or title or "")
        else:
            location = str(raw_item.get("location") or hotel_area or "")
        cost_meta = self._cost_metadata(
            category=item_category,
            fallback_cost=self._fallback_cost_for_category(item_category),
            use_poi_cost=False,
            ai_price_range=self._parse_price_range(raw_item.get("estimated_price_range")),
            ai_price_note=str(raw_item.get("price_note") or "AI 常识估算，需以官方/现场为准。"),
            ai_price_confidence=str(raw_item.get("price_confidence") or "low"),
        )
        return {
            "id": item_id,
            "poi_id": "",
            "time": slot,
            "title": title,
            "location": location,
            "address": "",
            "transport": self._display_transport_text(raw_item.get("transport") or "就近步行/打车"),
            "duration": str(raw_item.get("duration") or "0.5-1.5 小时"),
            "detail": detail,
            "category": item_category,
            "rating": None,
            "cost": None,
            "cost_estimate": cost_meta["cost_estimate"],
            "cost_source": cost_meta["cost_source"],
            "price_range": cost_meta["price_range"],
            "price_confidence": cost_meta["price_confidence"],
            "cost_note": cost_meta["cost_note"],
            "type": "待确认建议",
            "location_point": None,
            "location_source": "missing",
            "map_label": "",
            "map_included": False,
            "photo_url": self._category_image_url(item_category, title),
            "image_source": "category_fallback",
            "is_real_place": False,
            "place_source": "llm_suggestion",
            "validation_note": note,
        }

    def _build_itinerary_days(
        self,
        prefs: dict[str, Any],
        routes: dict[str, Any],
        local_transport: dict[str, Any],
        hotels: dict[str, Any],
        pois: dict[str, Any],
        weather: dict[str, str],
    ) -> list[dict[str, Any]]:
        days = []
        attractions = self._dedupe_pois(pois.get("attractions"))
        specialty_places = self._dedupe_pois(pois.get("specialty_places"))
        foods = self._dedupe_pois(pois.get("foods"))
        hotels_candidates = self._dedupe_pois(hotels.get("candidates"))
        activity_candidates = self._dedupe_pois([*attractions, *specialty_places])
        night_candidates = self._dedupe_pois(attractions)
        used_places: set[str] = set()
        hotel_area = hotels.get("area_recommendation") or self._default_hotel_area(prefs)
        recommended_local = "、".join(MODE_LABELS.get(mode, mode) for mode in local_transport.get("recommended_modes", []))
        current_date = self._parse_date(prefs["startDate"])
        hotel_poi = hotels_candidates[0] if hotels_candidates else None
        cluster_order = self._cluster_preference_order(activity_candidates, foods, hotel_poi)
        hotel_cluster = str((hotel_poi or {}).get("cluster_id") or "")
        profile = prefs.get("preferenceProfile") or {}
        learned_hints = " ".join(profile.get("learnedHints") or [])
        relaxed_pace = profile.get("pace") == "轻松" or any(
            keyword in learned_hints for keyword in ["别太赶", "轻松"]
        )

        for day_number in range(1, prefs["days"] + 1):
            date_text = (current_date + timedelta(days=day_number - 1)).isoformat() if current_date else ""
            theme = "抵达入住 + 城市初印象" if day_number == 1 else f"{prefs['destinationCity']}深度体验"
            if day_number == prefs["days"]:
                theme = "轻松收尾 + 返程预留"
            if day_number == 1 and hotel_cluster:
                day_cluster = hotel_cluster
            elif cluster_order:
                day_cluster = cluster_order[(day_number - 1) % len(cluster_order)]
            else:
                day_cluster = ""

            items = []
            if day_number == 1:
                if hotel_poi:
                    items.append(
                        self._timeline_item(
                            day_number,
                            "上午",
                            f"抵达后前往住宿：{hotel_poi['name']}",
                            hotel_poi["name"],
                            MODE_LABELS.get(routes.get("recommended"), routes.get("recommended", "rail")),
                            "2-4 小时",
                            f"优先按推荐主交通抵达目的地，之后前往真实酒店 POI 办理入住或寄存行李。住宿参考：{hotel_area}",
                            "transfer",
                            hotel_poi,
                            0,
                            place_source="hotel_poi",
                            is_real_place=True,
                            use_poi_cost=False,
                        )
                    )
                else:
                    items.append(
                        self._note_item(
                            day_number,
                            "上午",
                            "交通抵达说明",
                            "优先按推荐主交通抵达目的地；当前未获取到可定位交通枢纽或酒店 POI，因此不把泛化城市名作为真实地点展示。",
                        )
                    )
            else:
                morning_poi = self._take_unused_poi_for_cluster(activity_candidates, used_places, day_cluster)
                if morning_poi:
                    items.append(
                        self._timeline_item(
                            day_number,
                            "上午",
                            f"{morning_poi['name']}游览",
                            morning_poi["name"],
                            recommended_local,
                            "2 小时",
                            morning_poi.get("description", "安排真实景点 POI 游览。"),
                            "activity",
                            morning_poi,
                            80,
                            place_source="amap_poi",
                            is_real_place=True,
                        )
                    )
                else:
                    items.append(
                        self._note_item(
                            day_number,
                            "上午",
                            "真实景点候选不足",
                            "高德返回的未使用景点不足，已避免重复安排同一地点；建议将这一时段留作休整或按现场情况补充。",
                        )
                    )

            lunch_poi = self._take_unused_poi_for_cluster(foods, used_places, day_cluster)
            if lunch_poi:
                items.append(
                    self._timeline_item(
                        day_number,
                        "中午",
                        f"{lunch_poi['name']}午餐",
                        lunch_poi["name"],
                        recommended_local,
                        "1 小时",
                        lunch_poi.get("description", "选择靠近上午景点或酒店的真实餐厅 POI。"),
                        "food",
                        lunch_poi,
                        70,
                        place_source="amap_poi",
                        is_real_place=True,
                    )
                )
            else:
                items.append(
                    self._note_item(
                        day_number,
                        "中午",
                        "真实餐厅候选不足",
                        "高德返回的未使用餐厅不足，未编造餐厅名称；可在当前景点或酒店周边现场选择。",
                    )
                )

            afternoon_poi = self._take_unused_poi_for_cluster(activity_candidates, used_places, day_cluster)
            if afternoon_poi:
                items.append(
                    self._timeline_item(
                        day_number,
                        "下午",
                        f"{afternoon_poi['name']}游览",
                        afternoon_poi["name"],
                        recommended_local,
                        "2-3 小时",
                        f"{afternoon_poi.get('description', '安排真实景点 POI 游览。')} 结束后回到住宿区域休整。",
                        "activity",
                        afternoon_poi,
                        80,
                        place_source="amap_poi",
                        is_real_place=True,
                    )
                )
            elif hotel_poi:
                items.append(
                    self._timeline_item(
                        day_number,
                        "下午",
                        f"{hotel_poi['name']}休整",
                        hotel_poi["name"],
                        recommended_local,
                        "1.5-2 小时",
                        "真实景点候选不足时，安排回到推荐住宿点休整，避免重复塞入同一景点。",
                        "hotel",
                        hotel_poi,
                        0,
                        place_source="hotel_poi",
                        is_real_place=True,
                        use_poi_cost=False,
                    )
                )
            else:
                items.append(
                    self._note_item(
                        day_number,
                        "下午",
                        "真实景点候选不足",
                        "高德返回的未使用景点不足，已减少活动密度，不编造景点。",
                    )
                )

            dinner_poi = self._take_unused_poi_for_cluster(foods, used_places, day_cluster)
            if dinner_poi:
                dinner_detail = dinner_poi.get("description", "选择真实餐厅 POI 安排晚餐。")
                if day_number == prefs["days"]:
                    dinner_detail += " 最后一晚或返程前减少远距离移动，预留取行李和交通缓冲。"
                items.append(
                    self._timeline_item(
                        day_number,
                        "晚上",
                        f"{dinner_poi['name']}晚餐",
                        dinner_poi["name"],
                        "打车/公共交通/步行",
                        "1-1.5 小时",
                        dinner_detail,
                        "food",
                        dinner_poi,
                        70,
                        place_source="amap_poi",
                        is_real_place=True,
                    )
                )
            else:
                items.append(
                    self._note_item(
                        day_number,
                        "晚上",
                        "真实晚餐候选不足",
                        "高德返回的未使用餐厅不足，未编造晚餐地点；建议就近在酒店或当天最后一个景点周边选择。",
                    )
                )

            night_poi = None if relaxed_pace else self._take_unused_poi_for_cluster(night_candidates, used_places, day_cluster)
            if night_poi:
                items.append(
                    self._timeline_item(
                        day_number,
                        "夜间",
                        f"{night_poi['name']}轻量散步",
                        night_poi["name"],
                        "打车/公共交通/步行",
                        "0.5-1 小时",
                        night_poi.get("description", "选择真实 POI 作为夜间轻量散步点，避免使用泛化商圈或城市名。"),
                        "activity",
                        night_poi,
                        30,
                        place_source="amap_poi",
                        is_real_place=True,
                    )
                )
            elif day_number == prefs["days"] and not relaxed_pace:
                items.append(
                    self._note_item(
                        day_number,
                        "夜间",
                        "返程缓冲",
                        "未使用的真实夜游候选不足，最后一晚保留取行李和交通缓冲，不额外编造夜游地点。",
                    )
                )

            days.append(
                {
                    "day": day_number,
                    "date": date_text,
                    "theme": theme,
                    "weather_note": weather.get(prefs["destinationCity"], ""),
                    "items": items,
                }
            )
        return days

    @staticmethod
    def _build_map(
        plan_id: str,
        prefs: dict[str, Any],
        itinerary_days: list[dict[str, Any]],
        pois: dict[str, Any],
        hotels: dict[str, Any],
    ) -> dict[str, Any]:
        markers = []
        static_marker_limit = 10
        destination_center = StructuredTravelPlanner._derive_destination_center(prefs, itinerary_days, pois, hotels)
        hotel_point = StructuredTravelPlanner._first_valid_point(hotels.get("candidates", [])) or destination_center
        last_point = destination_center

        for day in itinerary_days:
            for item in day.get("items", []):
                point, source = StructuredTravelPlanner._resolve_item_map_point(
                    item,
                    destination_center,
                    hotel_point,
                    last_point,
                )
                if not point:
                    item["location_source"] = "missing"
                    item["map_label"] = ""
                    item["map_included"] = False
                    continue

                key = {
                    "lng": round(float(point["lng"]), 6),
                    "lat": round(float(point["lat"]), 6),
                }
                label = str(len(markers) + 1)
                item["location_point"] = key
                item["location_source"] = source
                item["map_label"] = label
                item["map_included"] = True
                last_point = key
                markers.append(
                    {
                        "id": item.get("id", ""),
                        "label": label,
                        "title": item.get("location") or item.get("title", ""),
                        "day": day.get("day"),
                        "time": item.get("time", ""),
                        "lng": key["lng"],
                        "lat": key["lat"],
                        "category": item.get("category", "activity"),
                        "location_source": source,
                        "place_source": item.get("place_source", source),
                        "is_real_place": item.get("is_real_place", False),
                    }
                )

        if not markers:
            fallback_titles = []
            for group in [pois.get("attractions", []), pois.get("foods", []), hotels.get("candidates", [])]:
                fallback_titles.extend(item.get("name", "") for item in group[:3])
            return {
                "provider_status": "fallback",
                "image_url": "",
                "center": None,
                "markers": [],
                "path": [],
                "static_marker_limit": static_marker_limit,
                "fallback_points": [title for title in fallback_titles if title],
                "notes": ["高德 POI 未返回可用坐标，暂以点位顺序列表展示。"],
            }

        center = {
            "lng": round(sum(marker["lng"] for marker in markers) / len(markers), 6),
            "lat": round(sum(marker["lat"] for marker in markers) / len(markers), 6),
        }
        static_markers = markers[:static_marker_limit]
        marker_param = ";".join(f"{marker['lng']},{marker['lat']},{marker['label']}" for marker in static_markers)
        path_param = ";".join(f"{marker['lng']},{marker['lat']}" for marker in static_markers)
        image_url = (
            f"/api/map-static?plan_id={quote(plan_id)}"
            f"&markers={quote(marker_param)}"
            f"&path={quote(path_param)}"
            f"&title={quote(str(prefs.get('destinationCity', '')))}"
        )
        return {
            "provider_status": "amap_static",
            "image_url": image_url,
            "center": center,
            "markers": markers,
            "path": [{"lng": marker["lng"], "lat": marker["lat"]} for marker in markers],
            "static_marker_limit": static_marker_limit,
            "notes": ["地图按每日行程顺序标记；兜底点位用于展示规划顺序，不等同实时导航路线。"],
        }

    @staticmethod
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

    @staticmethod
    def _first_valid_point(items: list[dict[str, Any]]) -> dict[str, float] | None:
        for item in items or []:
            point = StructuredTravelPlanner._normalize_point(item.get("location") or item.get("location_point"))
            if point:
                return point
        return None

    @staticmethod
    def _derive_destination_center(
        prefs: dict[str, Any],
        itinerary_days: list[dict[str, Any]],
        pois: dict[str, Any],
        hotels: dict[str, Any],
    ) -> dict[str, float] | None:
        city_center = CITY_CENTER_COORDS.get(str(prefs.get("destinationCity", "")).removesuffix("市"))
        if city_center:
            return city_center

        points = []
        for day in itinerary_days:
            for item in day.get("items", []):
                point = StructuredTravelPlanner._normalize_point(item.get("location_point"))
                if point:
                    points.append(point)
        for group in [
            pois.get("attractions", []),
            pois.get("foods", []),
            pois.get("specialty_places", []),
            hotels.get("candidates", []),
        ]:
            for item in group or []:
                point = StructuredTravelPlanner._normalize_point(item.get("location"))
                if point:
                    points.append(point)
        if points:
            return {
                "lng": sum(point["lng"] for point in points) / len(points),
                "lat": sum(point["lat"] for point in points) / len(points),
            }
        return None

    @staticmethod
    def _resolve_item_map_point(
        item: dict[str, Any],
        destination_center: dict[str, float] | None,
        hotel_point: dict[str, float] | None,
        last_point: dict[str, float] | None,
    ) -> tuple[dict[str, float] | None, str]:
        point = StructuredTravelPlanner._normalize_point(item.get("location_point"))
        if point:
            source = item.get("location_source") or item.get("place_source") or "amap_poi"
            if source == "missing":
                source = item.get("place_source") or "amap_poi"
            return point, source

        title = f"{item.get('title', '')}{item.get('location', '')}"
        category = item.get("category")
        place_source = item.get("place_source")
        if place_source in {"planning_note", "transport_note"} or item.get("is_real_place") is False:
            return None, "missing"
        if category == "transfer" and destination_center and place_source == "transport_hub":
            return destination_center, "city_center"
        if ("酒店" in title or "休整" in title or category == "hotel" or place_source == "hotel_poi") and hotel_point:
            return hotel_point, "hotel_area"
        if item.get("is_real_place") and last_point:
            return last_point, "derived"
        if item.get("is_real_place") and destination_center:
            return destination_center, "city_center"
        return None, "missing"

    @staticmethod
    def _parse_date(value: str) -> date | None:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

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

    @staticmethod
    def _section_summary(text: str, heading: str) -> str:
        if not text:
            return ""
        pattern = rf"【{re.escape(heading)}】(?P<body>.*?)(?:\n【|\n出行建议：|\Z)"
        match = re.search(pattern, text, re.S)
        body = match.group("body") if match else ""
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        return " ".join(lines[:3])

    @staticmethod
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
            cost = StructuredTravelPlanner._extract_float(value, r"人均约\s*([0-9.]+)\s*元")
            cost_estimate = round(float(cost)) if cost else 0
            item = {
                "id": StructuredTravelPlanner._make_item_id(heading, len(items) + 1, name),
                "name": name,
                "description": StructuredTravelPlanner._clean_description(description or value),
                "rating": StructuredTravelPlanner._extract_float(value, r"评分\s*([0-9.]+)"),
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
                "address": StructuredTravelPlanner._extract_address(value),
                "type": StructuredTravelPlanner._extract_poi_type(value),
                "location": StructuredTravelPlanner._extract_location(value),
                "photo_url": StructuredTravelPlanner._extract_photo_url(value),
                "raw": value,
            }
            items.append(item)
        return items

    @staticmethod
    def _make_item_id(prefix: str, index: int, name: str) -> str:
        safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", name).strip("-")
        safe_prefix = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", prefix).strip("-")
        return f"{safe_prefix or 'poi'}-{index}-{safe_name or 'item'}"

    @staticmethod
    def _clean_description(text: str) -> str:
        clean = re.sub(r"；坐标：[^；]+", "", text)
        clean = re.sub(r"；图片：\S+", "", clean)
        return clean.strip(" ：；") or "暂无补充信息"

    @staticmethod
    def _extract_float(text: str, pattern: str) -> float | None:
        match = re.search(pattern, text)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _extract_address(text: str) -> str:
        match = re.search(r"地址：(.+?)(?:；坐标：|；图片：|$)", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_location(text: str) -> dict[str, float] | None:
        match = re.search(r"坐标：\s*([0-9.-]+)\s*,\s*([0-9.-]+)", text)
        if not match:
            return None
        try:
            return {"lng": float(match.group(1)), "lat": float(match.group(2))}
        except ValueError:
            return None

    @staticmethod
    def _extract_photo_url(text: str) -> str:
        match = re.search(r"图片：(\S+)", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_poi_type(text: str) -> str:
        match = re.search(r"[（(](.*?)[）)]", text)
        if not match:
            return ""
        parts = [part.strip() for part in re.split(r"，|,", match.group(1)) if part.strip()]
        for part in reversed(parts):
            if not part.startswith("评分") and not part.startswith("人均约"):
                return part
        return ""

    @staticmethod
    def _compact(value: Any, limit: int = 900) -> str:
        text = str(value).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."
