import os
import json
from app.infras.db import AsyncDatabaseManager, async_insert_flight, async_insert_hotel, async_get_flights, async_get_hotels
from langchain.tools import tool
from app.infras.third_api import fetch_weather_report
from datetime import datetime
from app.infras.third_api.tavily import tavily_search

# 尝试导入依赖，如果未安装则设置为空，防止报错但会提示用户安装
try:
    from serpapi import GoogleSearch
except ImportError:
    GoogleSearch = None

# --- 引入新拆分的专业航班工具 ---

# =============================================================================
# 数据库交互 Tools (保持不变)
# =============================================================================


@tool
async def book_hotel(hotel_name: str):
    """预订酒店"""
    print(f"调用预订酒店: hotel_name={hotel_name}")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    hotel_data = {
        "name": hotel_name,
        "location": "New York",
        "check_in": "2025-11-01",
        "check_out": "2025-11-03",
        "guest": "John Doe"
    }
    await async_insert_hotel(db, hotel_data)
    await db_manager.close()
    return f"Successfully booked a stay at {hotel_name}."


@tool
async def book_flight(from_airport: str, to_airport: str):
    """预订机票"""
    print(f"调用预订机票: from={from_airport}, to={to_airport}")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    flight_data = {
        "from": from_airport,
        "to": to_airport,
        "date": "2025-11-01",
        "passenger": "John Doe"
    }
    await async_insert_flight(db, flight_data)
    await db_manager.close()
    return f"Successfully booked a flight from {from_airport} to {to_airport}."


@tool
async def query_booked_flights():
    """查询所有已预订的机票"""
    print("调用查询所有已预订的机票")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    flights = await async_get_flights(db)
    await db_manager.close()
    flight_list = [
        f"From {f.get('from', '')} to {f.get('to', '')} on {f.get('date', '')}" for f in flights]
    return f"Found {len(flights)} flights: {flight_list}"


@tool
async def query_booked_hotels():
    """查询所有已预订的酒店"""
    print("调用查询所有已预订的酒店")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    hotels = await async_get_hotels(db)
    await db_manager.close()
    hotel_list = [
        f"{h.get('name', '')} in {h.get('location', '')} from {h.get('check_in', '')} to {h.get('check_out', '')}" for h in hotels]
    return f"Found {len(hotels)} hotels: {hotel_list}"


@tool
async def book_ticket(attraction_name: str, date: str):
    """预订景点门票"""
    # 模拟实现
    print(f"调用预订景点门票: attraction_name={attraction_name}, date={date}")
    return f"Successfully booked a ticket for {attraction_name} on {date}."


# =============================================================================
# 第三方 API Tools (天气 & 通用搜索)
# =============================================================================

@tool
async def get_weather(location: str, date: str = None):
    """
    获取指定位置的天气预报。

    Args:
        location: 城市名称 (例如: "Shanghai", "Beijing", "Tokyo")
        date: 可选，日期字符串 (如果不提供，默认返回当前天气)
    """
    print(f"调用获取天气: location={location}, date={date}")
    return await fetch_weather_report(location, date)


@tool
async def search_travel_guides(query: str):
    """搜索旅游指南和建议"""
    print(f"调用搜索旅游指南和建议: {query}")
    return await tavily_search(query)


@tool
async def search_hotels(location: str, check_in: str, check_out: str):
    """
    查询实际酒店信息 (使用通用搜索)。
    Args:
        location: 地点
        check_in: 入住日期
        check_out: 退房日期
    """
    query = f"hotels in {location} from {check_in} to {check_out}"
    print(f"调用查询酒店: {query}")
    return await tavily_search(query)


@tool
async def search_tickets(attraction: str, date: str):
    """
    查询实际景点门票信息 (使用通用搜索)。
    Args:
        attraction: 景点名称
        date: 游玩日期
    """
    query = f"tickets for {attraction} on {date}"
    print(f"调用查询门票: {query}")
    return await tavily_search(query)


@tool
def get_current_time():
    """获取当前系统时间，格式为 YYYY-MM-DD HH:MM:SS"""
    print("调用获取当前时间")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =============================================================================
# 工具 1: 机场代码查询 (辅助工具)
# 作用: 将用户口语的 "Beijing", "New York" 转换为 IATA 代码 "PEK", "JFK"
# =============================================================================


@tool
def lookup_airport_code(city_name: str):
    """
    Look up the IATA airport code for a given city name. 
    Essential for flight searches.
    Args:
        city_name: The name of the city (e.g., "Beijing", "New York", "London")
    """
    print(f"🔍 [Tool] Searching airport code for: {city_name}")

    # 常用机场映射表 (建议实际生产中替换为数据库查询或专用 API)
    mapping = {
        "Beijing": "PEK", "Shanghai": "PVG", "Guangzhou": "CAN", "Shenzhen": "SZX",
        "New York": "JFK", "Los Angeles": "LAX", "San Francisco": "SFO",
        "London": "LHR", "Tokyo": "HND", "Paris": "CDG", "Singapore": "SIN",
        "Dubai": "DXB", "Sydney": "SYD", "Hong Kong": "HKG"
    }

    # 简单的模糊匹配处理
    for city, code in mapping.items():
        if city.lower() in city_name.lower():
            return code

    # 如果没找到，可以返回提示让 Agent 尝试其他名字，或者这里可以 fallback 到通用搜索
    return f"IATA code for '{city_name}' not found in local cache. Please try major city names (e.g., 'Tokyo' instead of 'Shinjuku')."


# =============================================================================
# 工具 2: 航班搜索 (核心工具)
# 实现: SerpApi (Google Flights 引擎)
# =============================================================================

@tool
def search_flights(origin: str, destination: str, date: str):
    """
    Search for real-time flight tickets using Google Flights engine.
    Returns structured data including airline, flight number, time, and price.

    Args:
        origin: Departure airport IATA code (e.g., "PEK", "JFK") - NOT city name.
        destination: Arrival airport IATA code (e.g., "HND", "LHR") - NOT city name.
        date: Departure date in "YYYY-MM-DD" format.
    """
    if not GoogleSearch:
        return "System Error: 'google-search-results' library is missing. Please install it."

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return "System Error: SERPAPI_API_KEY environment variable is missing."

    print(f"✈️ [Tool] Searching flights: {origin} -> {destination} on {date}")

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": date,
        "currency": "CNY",  # 默认货币，可按需修改
        "hl": "zh-cn",      # 语言设置
        "api_key": api_key
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        # 提取 'best_flights' (性价比最高的) 或 'other_flights'
        flight_results = results.get("best_flights", [])
        if not flight_results:
            flight_results = results.get("other_flights", [])

        if not flight_results:
            return f"No flights found from {origin} to {destination} on {date}."

        parsed_flights = []
        # 限制返回数量为 5 条，避免 Token 消耗过大
        for flight in flight_results[:5]:
            # Google Flights 数据结构解析
            flight_info = flight.get("flights", [{}])[0]

            # 安全获取时间
            dep_time = flight_info.get(
                "departure_airport", {}).get("time", "N/A")
            arr_time = flight_info.get(
                "arrival_airport", {}).get("time", "N/A")

            item = {
                "airline": flight_info.get("airline"),
                "flight_number": flight_info.get("flight_number"),
                "departure": f"{origin} at {dep_time}",
                "arrival": f"{destination} at {arr_time}",
                "duration": f"{flight.get('total_duration')} min",
                "price": f"¥{flight.get('price', 'Unknown')}",
                "link": flight.get("google_flights_url")  # 提供链接方便用户核实
            }
            parsed_flights.append(item)

        return json.dumps(parsed_flights, ensure_ascii=False)

    except Exception as e:
        return f"API Error during flight search: {str(e)}"


# =============================================================================
# 导出工具列表
# =============================================================================
# 这是一个便捷列表，Agent 可以直接 import tools from app.tools.tools
tools = [
    # 航班相关 (来自 app.tools.flight)
    lookup_airport_code,
    search_flights,

    # 数据库预订相关
    book_hotel,
    book_flight,
    book_ticket,
    query_booked_flights,
    query_booked_hotels,

    # 信息查询相关
    get_weather,
    search_travel_guides,
    search_hotels,
    search_tickets,
    get_current_time
]
