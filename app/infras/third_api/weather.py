import httpx
from datetime import datetime, timedelta

# --- 辅助函数：将天气代码转换为文字 ---


def get_weather_description(code: int) -> str:
    """WMO Weather interpretation codes (WW)"""
    codes = {
        0: "Clear sky",
        1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog",
        51: "Drizzle: Light", 53: "Drizzle: Moderate", 55: "Drizzle: Dense",
        51: "Drizzle: Light", 53: "Drizzle: Moderate", 55: "Drizzle: Dense",
        61: "Rain: Slight", 63: "Rain: Moderate", 65: "Rain: Heavy",
        71: "Snow fall: Slight", 73: "Snow fall: Moderate", 75: "Snow fall: Heavy",
        80: "Rain showers: Slight", 81: "Rain showers: Moderate", 82: "Rain showers: Violent",
        95: "Thunderstorm: Slight or moderate",
        96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
    }
    return codes.get(code, "Unknown weather status")


async def fetch_weather_report(location: str, date: str = None) -> str:
    """
    调用 Open-Meteo API 获取天气报告的具体实现。

    Args:
        location: 城市名称
        date: 可选，具体日期 (YYYY-MM-DD)。如果不传，默认返回当前及未来预报。
    """
    async with httpx.AsyncClient() as client:
        try:
            # 1. 地理编码：将城市名转换为经纬度
            geo_url = "https://geocoding-api.open-meteo.com/v1/search"
            geo_params = {"name": location, "count": 1,
                          "language": "en", "format": "json"}

            geo_resp = await client.get(geo_url, params=geo_params)
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                return f"Error: Could not find location '{location}'. Please check the spelling."

            lat = geo_data["results"][0]["latitude"]
            lon = geo_data["results"][0]["longitude"]
            city_name = geo_data["results"][0]["name"]
            country = geo_data["results"][0]["country"]

            # 2. 获取天气
            weather_url = "https://api.open-meteo.com/v1/forecast"
            weather_params = {
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true",
                "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "auto"
            }

            # 如果指定了日期，添加 start_date 和 end_date 参数
            if date:
                # 简单校验一下格式，虽然 LLM 通常很靠谱
                try:
                    datetime.strptime(date, "%Y-%m-%d")
                    weather_params["start_date"] = date
                    weather_params["end_date"] = date
                except ValueError:
                    return f"Error: Date format must be YYYY-MM-DD. Got: {date}"

            weather_resp = await client.get(weather_url, params=weather_params)
            # 处理 API 错误（例如日期超出范围）
            if weather_resp.status_code != 200:
                return f"Error from Weather API: {weather_resp.text}"

            weather_data = weather_resp.json()

            # 3. 格式化输出
            report = f"Weather Report for {city_name}, {country}:\n"

            # 只有在没有指定特定日期，或者指定的日期就是今天时，才显示 "Current"
            # (简单的判断逻辑：如果不传 date，API 默认返回当前天气)
            if not date:
                current = weather_data.get("current_weather", {})
                current_temp = current.get("temperature")
                current_desc = get_weather_description(
                    current.get("weathercode"))
                report += f"- Current: {current_desc}, {current_temp}°C\n"

            report += "- Forecast:\n"
            daily = weather_data.get("daily", {})
            times = daily.get("time", [])
            codes = daily.get("weathercode", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])

            # 如果指定了日期，times 里通常只有 1 天的数据
            days_to_show = min(5, len(times))
            if len(times) == 0:
                return f"No weather data found for {city_name} on {date}."

            for i in range(days_to_show):
                day_desc = get_weather_description(codes[i])
                report += f"  {times[i]}: {day_desc}, High {max_temps[i]}°C / Low {min_temps[i]}°C\n"

            return report

        except Exception as e:
            return f"Error fetching weather data: {str(e)}"
