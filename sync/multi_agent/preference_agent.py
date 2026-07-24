from __future__ import annotations

import re

from .base_agent import BaseTravelAgent
from .schemas import TravelPlanState, TravelPreferences


KNOWN_CITIES = [
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "南京",
    "成都",
    "重庆",
    "西安",
    "武汉",
    "福州",
    "厦门",
    "天津",
    "苏州",
    "长沙",
    "青岛",
    "香港",
    "澳门",
]

CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


class PreferenceAgent(BaseTravelAgent):
    name = "PreferenceAgent 需求理解"

    def run(self, state: TravelPlanState) -> str:
        text = state.raw_request.strip()
        origin, destination = self._extract_places(text)
        origin_city = self._extract_city(origin) or origin
        destination_city = self._extract_city(destination) or destination

        prefs = TravelPreferences(
            raw_request=text,
            origin=origin,
            destination=destination,
            origin_city=origin_city,
            destination_city=destination_city,
            start_date_label=self._extract_date_label(text),
            days=self._extract_int(text, r"([0-9一二两三四五六七八九十]+)\s*天", 2),
            travelers=self._extract_int(text, r"([0-9一二两三四五六七八九十]+)\s*人", 1),
            budget=self._extract_budget(text),
            hotel_level=self._extract_hotel_level(text),
            interests=self._extract_interests(text),
            require_file=bool(re.search(r"保存|导出|生成.*文件|行程文件|markdown|md", text, re.I)),
            route_modes=self._extract_route_modes(text),
        )
        state.preferences = prefs

        budget_text = f"{prefs.budget}元" if prefs.budget else "未指定"
        return (
            f"已识别：{prefs.origin} -> {prefs.destination}，"
            f"{prefs.days}天{prefs.travelers}人，预算 {budget_text}，"
            f"偏好 {', '.join(prefs.interests)}，路线模式 {prefs.route_modes}。"
        )

    def _extract_places(self, text: str) -> tuple[str, str]:
        patterns = [
            r"从(.+?)(?:到|去|前往)(.+?)(?:玩|旅游|出行|路线|周末|，|。|,|\.|$)",
            r"(.+?)(?:到|去|前往)(.+?)(?:玩|旅游|出行|路线|周末|，|。|,|\.|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                origin = self._clean_place(match.group(1))
                destination = self._clean_place(match.group(2))
                if origin and destination and origin != destination:
                    return origin, destination

        city_hits = sorted(
            (text.index(city), city)
            for city in KNOWN_CITIES
            if city in text
        )
        if len(city_hits) >= 2:
            return city_hits[0][1], city_hits[1][1]

        if len(city_hits) == 1:
            return "广州", city_hits[0][1]

        return "广州", "深圳"

    @staticmethod
    def _clean_place(value: str) -> str:
        value = value.strip()
        value = re.sub(r"^(我|我们|帮我|请帮我|计划|规划|安排|想|要|周末|明天|今天|后天)+", "", value)
        value = re.split(r"的|并|再|然后|顺便|，|。|,|\.", value)[0]
        value = re.sub(r"(多种|多个|出行|规划|方案|路线|对比|推荐)$", "", value)
        return value.strip() or "深圳"

    @staticmethod
    def _extract_city(place: str) -> str:
        for city in KNOWN_CITIES:
            if city in place:
                return city
        return place

    @staticmethod
    def _extract_date_label(text: str) -> str:
        for label in ["今天", "明天", "后天", "周末"]:
            if label in text:
                return label
        return "明天"

    def _extract_int(self, text: str, pattern: str, default: int) -> int:
        match = re.search(pattern, text)
        if not match:
            return default
        return self._to_int(match.group(1), default)

    def _extract_budget(self, text: str) -> int | None:
        budget_match = re.search(r"预算[^0-9一二两三四五六七八九十]*([0-9]+)", text)
        if budget_match:
            return int(budget_match.group(1))

        yuan_match = re.search(r"([0-9]+)\s*元", text)
        if yuan_match:
            return int(yuan_match.group(1))

        return None

    @staticmethod
    def _extract_hotel_level(text: str) -> str:
        if re.search(r"高端|豪华|五星", text):
            return "高端"
        if re.search(r"省钱|经济|便宜|学生党", text):
            return "经济"
        return "舒适"

    @staticmethod
    def _extract_interests(text: str) -> list[str]:
        mapping = [
            ("经典景点", r"经典景点|景点|景区|活动"),
            ("美食", r"美食|吃|餐厅|小吃"),
            ("地方特色", r"地方特色|当地特色|本地特色|特色美食|必吃|老字号"),
            ("亲子", r"亲子|孩子|小朋友"),
            ("拍照", r"拍照|出片|摄影"),
            ("博物馆", r"博物馆|展览|室内"),
            ("海边", r"海边|海景|沙滩"),
            ("夜景", r"夜景|夜游|酒吧"),
            ("轻松", r"轻松|不累|慢节奏"),
        ]
        interests = [label for label, pattern in mapping if re.search(pattern, text)]
        return interests or ["经典景点"]

    @staticmethod
    def _extract_route_modes(text: str) -> str:
        modes = []
        if re.search(r"高铁|火车|动车|城际|铁路", text):
            modes.append("rail")
        if re.search(r"驾车|自驾|开车", text):
            modes.append("driving")
        if re.search(r"公交|地铁|公共交通|不想开车", text):
            modes.append("transit")
        if "步行" in text:
            modes.append("walking")
        if "骑行" in text:
            modes.append("bicycling")
        if not modes or re.search(r"对比|多种|多个|多条", text):
            modes = ["rail", "driving", "transit"]
        return ",".join(dict.fromkeys(modes))

    @staticmethod
    def _to_int(value: str, default: int) -> int:
        if value.isdigit():
            return int(value)
        if value in CHINESE_NUMBERS:
            return CHINESE_NUMBERS[value]
        if value.endswith("十") and len(value) == 2:
            return CHINESE_NUMBERS.get(value[0], default) * 10
        return default
