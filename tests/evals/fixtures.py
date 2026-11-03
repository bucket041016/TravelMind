from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from sync.mcp_tools_adapter import MCPToolResult
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from mcp_tools_adapter import MCPToolResult


@dataclass(frozen=True)
class EvalScenario:
    """A deterministic input and dependency fixture for one baseline case."""

    name: str
    payload: dict[str, Any]
    weather: str = "晴，24-30°C，风力 2 级"
    route_distance_km: float = 3.2
    route_duration_minutes: int = 18
    hotel_cost: int | None = 420
    fail_tools: tuple[str, ...] = ()
    llm_status: str = "used"
    review_status: str = "used"
    route_judge_status: str = "used"
    duplicate_activity: bool = False
    contaminated_return: bool = False
    far_points: bool = False
    kb_covered: bool = True
    expected: dict[str, Any] = field(default_factory=dict)


class FixtureToolbox:
    """MCP-shaped fake that returns stable text in the current MCP contract."""

    def __init__(self, scenario: EvalScenario):
        self.scenario = scenario
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failures: list[str] = []

    def call(self, tool_name: str, **kwargs: Any) -> str:
        self.calls.append((tool_name, dict(kwargs)))
        if tool_name in self.scenario.fail_tools:
            self.failures.append(tool_name)
            raise RuntimeError(f"fixture failure: {tool_name}")
        if tool_name == "get_weather":
            city = str(kwargs.get("city") or "")
            if city == self.scenario.payload.get("destinationCity"):
                return f"{city}：{self.scenario.weather}"
            return f"{city}：晴，23-29°C，风力 2 级"
        if tool_name == "search_poi":
            return self._poi_response()
        if tool_name == "search_hotels":
            return self._hotel_response()
        if tool_name == "amap_plan_routes":
            modes = str(kwargs.get("modes") or "")
            if "," in modes or modes in {"rail", "driving"} and kwargs.get("origin_city") != kwargs.get("destination_city"):
                return self._intercity_route_response()
            return self._local_route_response(modes)
        if tool_name == "estimate_budget":
            return "预算参考：按高德候选和规则估算。"
        if tool_name == "kb_retrieve":
            return self._kb_response()
        return "fixture response"

    def call_text(self, tool_name: str, **kwargs: Any) -> str:
        return self.call(tool_name, **kwargs)

    def call_structured(self, tool_name: str, **kwargs: Any) -> MCPToolResult:
        return MCPToolResult.from_value(tool_name, self.call(tool_name, **kwargs))

    def _kb_response(self) -> dict[str, Any]:
        """知识库检索的罐头返回：与 kb_retrieve 工具契约同形，覆盖 fixture 里的景点名。"""
        city = str(self.scenario.payload.get("destinationCity") or "深圳")
        if not self.scenario.kb_covered:
            return {
                "provider_status": "not_covered",
                "city": city,
                "query": "",
                "city_guide": None,
                "entries": [],
                "coverage": "none",
                "note": "本地知识库暂未覆盖该目的地，已跳过知识检索；行程事实仍以高德候选为准。",
            }

        def entry(name: str, **overrides: Any) -> dict[str, Any]:
            base = {
                "name": name,
                "aliases": [],
                "district": "南山区",
                "highlights": [f"{name}的核心看点一", f"{name}的核心看点二"],
                "suggested_duration": "2-3 小时",
                "best_time": "傍晚",
                "booking": "免预约，免费开放",
                "ticket": "免费",
                "indoor": False,
                "rainy_alternative": False,
                "keywords": ["海滨", "免费"],
                "note": f"{name}的人工策展备注。",
            }
            base.update(overrides)
            return base

        return {
            "provider_status": "knowledge_base",
            "city": city,
            "query": "",
            "city_guide": {
                "city": city,
                "summary": f"{city}是带状沿海城市，核心游览区集中在福田-罗湖老城、南山科技园-深圳湾和盐田-东部海滨三条线上。",
                "districts": [
                    {"name": "南山区", "character": "深圳湾海滨与文创园集中。", "best_for": ["海滨", "文创园"]},
                    {"name": "福田区", "character": "市中心与地铁枢纽密集。", "best_for": ["博物馆", "住宿"]},
                ],
                "practical_tips": ["跨区优先地铁而非打车。", "多数博物馆周一闭馆，需提前预约。"],
                "seasonal": [{"months": "6-9", "advice": "午后多雷雨，户外安排在上午或傍晚。"}],
            },
            "entries": [
                entry("深圳湾公园"),
                entry("世界之窗", indoor=False, booking="需提前购票", ticket="分日场与夜场售票"),
                entry("华侨城创意园", indoor=True, rainy_alternative=True, suggested_duration="1.5-2.5 小时"),
                entry("莲花山公园"),
                entry("海上世界文化艺术中心", indoor=True, rainy_alternative=True, booking="展览需预约，周一闭馆"),
            ],
            "coverage": "full",
            "note": "知识库为人工策展的背景知识，仅用于补充景点详情与本地规则。",
        }

    def _poi_response(self) -> str:
        city = str(self.scenario.payload.get("destinationCity") or "深圳")
        base_lng = 114.0579 if not self.scenario.far_points else 114.60
        base_lat = 22.5431 if not self.scenario.far_points else 22.95
        attractions = [
            ("深圳湾公园", "公园", 0.0000, 0.0000, 0),
            ("世界之窗", "主题公园", 0.0180, 0.0040, 120),
            ("华侨城创意园", "文创园", 0.0300, 0.0080, 0),
            ("莲花山公园", "公园", 0.0500, 0.0150, 0),
            ("海上世界文化艺术中心", "博物馆", 0.0700, 0.0200, 80),
        ]
        foods = [
            ("潮汕牛肉店", "餐厅", 0.0040, 0.0020, 90),
            ("盐田海鲜酒楼", "海鲜餐厅", 0.0240, 0.0070, 160),
            ("南头古城小吃店", "小吃店", 0.0440, 0.0120, 55),
            ("湾区茶餐厅", "茶餐厅", 0.0640, 0.0170, 65),
        ]

        def line(index: int, item: tuple[str, str, float, float, int]) -> str:
            name, kind, lng_offset, lat_offset, cost = item
            details = [
                kind,
                "评分 4.6",
                f"地址：{city}{'南山区' if index % 2 else '福田区'}{name}附近",
                f"坐标：{base_lng + lng_offset:.6f},{base_lat + lat_offset:.6f}",
            ]
            if cost:
                details.append(f"人均约 {cost} 元")
            return f"{index}. {name}（{'；'.join(details)}）"

        attraction_lines = [line(index, item) for index, item in enumerate(attractions, 1)]
        food_lines = [line(index, item) for index, item in enumerate(foods, 1)]
        specialty_lines = [line(index, item) for index, item in enumerate(foods[2:], 1)]
        return "\n".join(
            [
                "【景点/活动】",
                *attraction_lines,
                "【美食/餐厅】",
                *food_lines,
                "【特色店铺参考】",
                *specialty_lines,
                "出行提示：以上为离线高德样例候选，坐标和消费仅用于稳定评测。",
            ]
        )

    def _hotel_response(self) -> str:
        city = str(self.scenario.payload.get("destinationCity") or "深圳")
        hotels = [
            ("后海地铁站智选酒店", 114.0585, 22.5440, self.scenario.hotel_cost),
            ("深圳湾公园假日酒店", 114.0630, 22.5460, 520 if self.scenario.hotel_cost else None),
        ]
        lines = ["【酒店候选】"]
        for index, (name, lng, lat, cost) in enumerate(hotels, 1):
            details = [
                "舒适型",
                "评分 4.4",
                f"地址：{city}南山区{name}（后海地铁站附近）",
                f"坐标：{lng:.6f},{lat:.6f}",
            ]
            if cost is not None:
                details.append(f"人均约 {cost} 元")
            lines.append(f"{index}. {name}（{'；'.join(details)}）")
        lines.extend(
            [
                "住宿区域建议：后海地铁站、深圳湾公园周边，便于换乘和晚间返程。",
                "provider_status=amap_poi_fixture",
            ]
        )
        return "\n".join(lines)

    def _intercity_route_response(self) -> str:
        origin = str(self.scenario.payload.get("originCity") or "广州")
        destination = str(self.scenario.payload.get("destinationCity") or "深圳")
        return "\n".join(
            [
                "高德路线规划结果",
                f"出发地：{origin}南站（113.264400,23.129100）",
                f"目的地：{destination}北站（114.057900,22.543100）",
                "【高铁/城际铁路】",
                "1. 广州南站 -> 深圳北站，车程约 35 分钟，票价约 75-120 元。",
                "【驾车】",
                "1. 约 1 小时 50 分钟，距离约 137 km，过路费约 70 元。",
            ]
        )

    def _local_route_response(self, mode: str) -> str:
        heading = {
            "transit": "公交/地铁",
            "walking": "步行",
            "bicycling": "骑行",
            "driving": "驾车",
        }.get(mode, "公交/地铁")
        return "\n".join(
            [
                "高德路线规划结果",
                f"【{heading}】",
                f"1. 约 {self.scenario.route_distance_km:.1f} km，{self.scenario.route_duration_minutes} 分钟，票价约 4 元；沿途接驳清晰。",
            ]
        )


class FixtureDeepSeekBrain:
    """DeepSeek-shaped fake with call accounting and controlled edge cases."""

    def __init__(self, scenario: EvalScenario):
        self.scenario = scenario
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("plan", payload))
        if self.scenario.llm_status != "used":
            return {"llm_status": self.scenario.llm_status, "reason": "fixture configured unavailable", "plan": None}

        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        activities = [item for item in candidates if item.get("category") == "activity"]
        foods = [item for item in candidates if item.get("category") == "food"]
        hotels = [item for item in candidates if item.get("category") == "hotel"]

        def candidate_id(items: list[dict[str, Any]], index: int) -> str:
            if not items:
                return ""
            return str(items[index % len(items)].get("id") or "")

        def activity_item(index: int, title: str | None = None) -> dict[str, Any]:
            item_id = candidate_id(activities, index)
            return {
                "title": title or "真实候选活动",
                "candidate_id": item_id,
                "category": "activity",
                "transport": "公共交通",
                "duration": "2 小时",
                "detail": "从离线候选中选择的活动，按片区安排。",
                "is_suggestion": not bool(item_id),
                "validation_note": "fixture candidate",
                "estimated_price_range": "",
                "price_confidence": "unknown",
                "price_note": "",
            }

        def food_item(index: int) -> dict[str, Any]:
            item_id = candidate_id(foods, index)
            return {
                "title": "真实候选餐饮",
                "candidate_id": item_id,
                "category": "food",
                "transport": "步行",
                "duration": "1 小时",
                "detail": "从离线候选中选择的餐饮地点。",
                "is_suggestion": not bool(item_id),
                "validation_note": "fixture candidate",
                "estimated_price_range": "",
                "price_confidence": "unknown",
                "price_note": "",
            }

        def hotel_transfer() -> dict[str, Any]:
            return {
                "title": "抵达后前往酒店",
                "candidate_id": candidate_id(hotels, 0),
                "category": "transfer",
                "transport": "高铁/动车/城际",
                "duration": "1 小时",
                "detail": "抵达后办理入住或寄存行李。",
                "is_suggestion": False,
                "validation_note": "fixture candidate",
            }

        def return_transfer() -> dict[str, Any]:
            detail = "返程交通后入住目的地酒店" if self.scenario.contaminated_return else "从目的地车站返回广州"
            return {
                "title": "返程交通",
                "candidate_id": "",
                "category": "transfer",
                "location": "深圳北站 -> 广州南站",
                "transport": "高铁/动车/城际",
                "duration": "35 分钟",
                "detail": detail,
                "is_suggestion": True,
                "validation_note": "fixture return transfer",
            }

        days = []
        total_days = int(payload.get("preferences", {}).get("days") or self.scenario.payload.get("days") or 2)
        for day_number in range(1, total_days + 1):
            items: list[dict[str, Any]] = []
            if day_number == 1:
                items.append(hotel_transfer())
            first_activity = 0 if self.scenario.duplicate_activity else day_number - 1
            items.extend(
                [
                    activity_item(first_activity, "片区活动候选"),
                    food_item(day_number - 1),
                    activity_item(first_activity if self.scenario.duplicate_activity else day_number, "第二个活动候选"),
                    food_item(day_number),
                ]
            )
            if day_number == total_days:
                items[-1] = return_transfer()
            days.append({"day": day_number, "theme": f"fixture 第 {day_number} 天", "items": items})
        return {"llm_status": "used", "reason": "fixture", "plan": {"days": days}}

    def estimate_hotel_prices(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("estimate_hotel_prices", payload))
        if self.scenario.llm_status != "used":
            return {"llm_status": self.scenario.llm_status, "reason": "fixture configured unavailable", "prices": []}
        prices = []
        for candidate in payload.get("candidates", [])[:6]:
            prices.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "estimated_price_range": "360-480",
                    "price_confidence": "low",
                    "price_note": "AI 常识估算，需以酒店平台实时房价和房态为准。",
                }
            )
        return {"llm_status": "used", "reason": "fixture", "prices": prices}

    def judge_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("judge_route", payload))
        if self.scenario.route_judge_status != "used":
            return {"llm_status": self.scenario.route_judge_status, "reason": "fixture configured unavailable", "judgement": None}
        return {
            "llm_status": "used",
            "reason": "fixture",
            "judgement": {"decision": "accept", "risk_level": "low", "judge_reason": "fixture route accepted"},
        }

    def review_itinerary(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("review_itinerary", payload))
        if self.scenario.review_status != "used":
            return {"llm_status": self.scenario.review_status, "reason": "fixture configured unavailable", "review": None}
        return {
            "llm_status": "used",
            "reason": "fixture",
            "review": {
                "overall_score": 82,
                "route_score": 80,
                "pace_score": 84,
                "cluster_score": 82,
                "logic_score": 82,
                "issues": [],
                "fixes": [],
                "needs_repair": False,
                "repaired_plan": {"days": []},
            },
        }


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "originCity": "广州",
        "destinationCity": "深圳",
        "startDate": "2026-08-08",
        "days": 2,
        "travelers": 1,
        "budget": 1800,
        "intercityModes": ["高铁/动车/城际", "自驾"],
        "localModes": ["公共交通", "打车", "步行"],
        "hotelLevel": "舒适",
        "interests": ["经典景点", "美食", "地方特色"],
        "preferenceProfile": {
            "pace": "标准",
            "maxTransferMinutes": 45,
            "hotelStrategy": "近地铁枢纽",
            "learnedHints": [],
        },
    }
    payload.update(overrides)
    return payload


def build_scenarios() -> list[EvalScenario]:
    return [
        EvalScenario("standard_weekend", _payload(), expected={"max_transfer_minutes": 45}),
        EvalScenario(
            "family_budget",
            _payload(days=3, travelers=4, budget=1800),
            hotel_cost=520,
            expected={"max_transfer_minutes": 45, "budget_must_be_within": True},
        ),
        EvalScenario(
            "rainy_indoor_preference",
            _payload(
                freeText="下雨时只安排室内展馆和餐厅，避免长距离步行。",
                interests=["室内展馆", "美食"],
                preferenceProfile={"pace": "标准", "maxTransferMinutes": 35, "hotelStrategy": "近地铁枢纽", "learnedHints": []},
            ),
            weather="小雨，24-27°C，风力 3 级",
            expected={"free_text_preserved": True, "max_transfer_minutes": 35},
        ),
        EvalScenario(
            "low_budget",
            _payload(budget=500, hotelLevel="经济"),
            hotel_cost=620,
            expected={"budget_must_be_within": True},
        ),
        EvalScenario(
            "slow_pace",
            _payload(
                freeText="每天最多安排三个真实地点，晚上不要再加活动。",
                preferenceProfile={"pace": "轻松", "maxTransferMinutes": 45, "hotelStrategy": "近景点", "learnedHints": []},
            ),
            expected={"max_real_places_per_day": 3, "free_text_preserved": True},
        ),
        EvalScenario(
            "tight_transfer_tolerance",
            _payload(
                preferenceProfile={"pace": "标准", "maxTransferMinutes": 20, "hotelStrategy": "近地铁枢纽", "learnedHints": []}
            ),
            route_distance_km=38.0,
            route_duration_minutes=135,
            far_points=True,
            expected={"max_transfer_minutes": 20},
        ),
        EvalScenario(
            "return_transfer_isolation",
            _payload(days=3, freeText="最后一天只保留返程交通，不要把目的地住宿写进返程说明。"),
            contaminated_return=True,
            expected={"no_return_lodging_contamination": True},
        ),
        EvalScenario(
            "duplicate_candidate",
            _payload(days=2),
            duplicate_activity=True,
            expected={"duplicate_rate": 0.0},
        ),
        EvalScenario(
            "dependency_fallback",
            _payload(days=2, budget=1200),
            weather="",
            hotel_cost=None,
            fail_tools=("get_weather", "search_poi", "search_hotels", "amap_plan_routes"),
            llm_status="unavailable",
            review_status="unavailable",
            route_judge_status="unavailable",
            expected={"fallback_rate_observable": True},
        ),
        EvalScenario(
            "free_text_hard_constraint",
            _payload(
                freeText="不要安排夜间活动，晚上十点前回到酒店。",
                preferenceProfile={"pace": "标准", "maxTransferMinutes": 45, "hotelStrategy": "近商圈", "learnedHints": []},
            ),
            expected={"free_text_preserved": True, "no_night_activity": True},
        ),
    ]


def build_knowledge_scenarios() -> list[EvalScenario]:
    """知识库检索专用场景：与 build_scenarios() 分开，避免改动已定基线的 10 场景与调用数。

    这些场景由 tests/evals/test_knowledge_eval.py 驱动，运行前会显式设置
    TRAVELMIND_KNOWLEDGE；知识库只做背景补充，不引入地点、坐标、票价或库存。
    """
    return [
        EvalScenario(
            "knowledge_rainy_indoor",
            _payload(
                freeText="下雨时只安排室内展馆和餐厅，避免长距离步行。",
                interests=["室内展馆", "美食"],
                preferenceProfile={"pace": "标准", "maxTransferMinutes": 35, "hotelStrategy": "近地铁枢纽", "learnedHints": []},
            ),
            weather="小雨，24-27°C，风力 3 级",
            expected={"knowledge_matched": True, "knowledge_indoor_available": True},
        ),
        EvalScenario(
            "knowledge_booking_rules",
            _payload(days=2),
            expected={"knowledge_matched": True, "knowledge_booking_present": True},
        ),
        EvalScenario(
            "knowledge_not_covered",
            _payload(days=2),
            kb_covered=False,
            expected={"knowledge_not_covered": True},
        ),
        EvalScenario(
            "knowledge_flag_off",
            _payload(days=2),
            expected={"knowledge_flag_off": True},
        ),
    ]
