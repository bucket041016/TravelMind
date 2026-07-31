"""TravelMind 全局常量和映射表。

从 structured_planner.py 中提取，避免巨型文件中嵌入大量数据字典。
"""

from __future__ import annotations

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
