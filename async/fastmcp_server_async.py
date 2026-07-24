# conda env mcp_env ,Python版本 3.10.18
# 关闭 proxy
# 使用方法：用python 把server启动

import asyncio
from datetime import datetime
import aiohttp
from fastmcp import FastMCP

mcp = FastMCP(name="travel-agent-mcp-async")

CITY_ALIASES = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "成都": "Chengdu",
    "重庆": "Chongqing",
    "西安": "Xian",
    "武汉": "Wuhan",
    "福州": "Fuzhou",
    "厦门": "Xiamen",
    "香港": "Hong Kong",
}

@mcp.tool()
async def calculate_bmi(weight_kg: float, height_m: float) -> float:
    """通过给定的体重和身高计算BMI指数。

    Args:
        weight_kg (float): 用户的体重，单位为公斤(kg)。
        height_m (float): 用户的身高，单位为米(m)。

    Returns:
        float: 计算得出的BMI指数值。
    """
    # 模拟一些异步处理
    await asyncio.sleep(0.01)  # 模拟轻微延迟
    return weight_kg / (height_m ** 2)

@mcp.tool()
async def get_current_time() -> str:
    """获取当前时间

    Returns:
        str: 当前时间的字符串表示
    """
    # 模拟一些异步处理
    await asyncio.sleep(0.01)  # 模拟轻微延迟
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@mcp.tool()
async def get_weather(city: str, date: str):
    """获取指定城市在特定日期的天气情况。

    Args:
        city (str): 需要查询天气的城市名称，例如 "北京" 或 "London"。
        date (str): 需要查询的日期，可以使用 "今天"、"明天" 等相对描述，或 "2023.10.27" 这样的具体日期。

    Returns:
        str: 包含该城市天气情况描述的原始文本。
    """
    endpoint = "https://wttr.in"
    query_city = CITY_ALIASES.get(city.strip(), city.strip())

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{endpoint}/{query_city}",
                params={"format": "j1", "lang": "zh"},
                timeout=15,
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)

        target_index = 1 if "明天" in date or "tomorrow" in date.lower() else 0
        forecast_days = data.get("weather", [])
        current = data.get("current_condition", [{}])[0]

        if target_index < len(forecast_days):
            day = forecast_days[target_index]
            astronomy = day.get("astronomy", [{}])[0]
            hourly = day.get("hourly", [{}])
            noon = hourly[min(4, len(hourly) - 1)] if hourly else {}
            desc = noon.get("lang_zh", [{}])[0].get("value") or noon.get("weatherDesc", [{}])[0].get("value", "未知")
            return (
                f"{city}（{query_city}）{date}天气：{desc}。"
                f"气温 {day.get('mintempC', '未知')}~{day.get('maxtempC', '未知')}°C，"
                f"降水概率 {noon.get('chanceofrain', '未知')}%，"
                f"风速 {noon.get('windspeedKmph', '未知')} km/h，"
                f"日出 {astronomy.get('sunrise', '未知')}，日落 {astronomy.get('sunset', '未知')}。"
            )

        desc = current.get("lang_zh", [{}])[0].get("value") or current.get("weatherDesc", [{}])[0].get("value", "未知")
        return (
            f"{city}（{query_city}）当前天气：{desc}，"
            f"气温 {current.get('temp_C', '未知')}°C，"
            f"体感 {current.get('FeelsLikeC', '未知')}°C，"
            f"湿度 {current.get('humidity', '未知')}%。"
        )
    except Exception as e:
        return f"天气查询失败：{e}"

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8084,  # 使用不同的端口，避免与同步版本冲突
        path="/my-custom-path",
        log_level="debug",
    )
