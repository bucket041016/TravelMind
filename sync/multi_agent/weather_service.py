"""TravelMind 天气查询与出行建议。"""

from __future__ import annotations

from typing import Any, Callable
import re

from .text_parser import (
    _max_temperature,
    _max_wind_level,
)
from .fact_normalizer import normalize_weather_fact


def _build_weather(self, prefs: dict[str, Any]) -> dict[str, str]:
    result = {}
    for city in dict.fromkeys([prefs["originCity"], prefs["destinationCity"]]):
        result[city] = self.toolbox.call("get_weather", city=city, date=prefs["startDate"])
    return result

def _build_weather_advice(weather: dict[str, str]) -> dict[str, str]:
    text = " ".join(weather.values())
    has_rain = bool(re.search(r"雷阵雨|阵雨|小雨|中雨|大雨|暴雨|雨", text)) and "无雨" not in text
    max_temp = _max_temperature(text)
    max_wind = _max_wind_level(text)

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


def _normalize_weather_facts(
    weather: dict[str, str],
    prefs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """将原始天气文本归一化为结构化 WeatherFact。返回 {city: WeatherFact}。"""
    result: dict[str, dict[str, Any]] = {}
    start_date = prefs.get("startDate", "")
    for city, raw_text in weather.items():
        result[city] = normalize_weather_fact(
            raw_text,
            city=city,
            date=start_date,
            source="weather",
        )
    return result
