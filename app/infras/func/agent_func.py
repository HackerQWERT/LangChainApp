import os
import json
from datetime import datetime, timedelta
from langchain.tools import tool

# =============================================================================
# 依赖处理 (Mock / Real)
# 为了保证代码在 Canvas 环境中可运行，添加了 Mock 回退逻辑
# =============================================================================
try:
    # 尝试导入真实后端依赖
    from app.infras.db import (
        AsyncDatabaseManager,
        async_get_flights,
        async_get_hotels,
        async_lock_flight,
        async_confirm_flight,
        async_lock_hotel,
        async_confirm_hotel
    )
    from app.infras.third_api import fetch_weather_report
    from app.infras.third_api.tavily import tavily_search
    print("✅ 成功加载真实后端依赖 (app.infras)。")
except ImportError:
    print("⚠️ 未找到后端依赖 (app.infras)，启用 Mock 模式。")

    # Mock Database Manager
    class AsyncDatabaseManager:
        async def ping(self): pass
        def get_db(self): return "mock_db"
        async def close(self): pass

    # Mock DB Functions
    async def async_lock_flight(
        *args, **kwargs): return "MOCK_FLIGHT_ORDER_123"

    async def async_lock_hotel(*args, **kwargs): return "MOCK_HOTEL_ORDER_456"
    async def async_confirm_flight(*args): return True
    async def async_confirm_hotel(*args): return True
    async def async_get_flights(*args): return []
    async def async_get_hotels(*args): return []

    # Mock Third Party APIs
    async def fetch_weather_report(loc, date=None):
        return f"Mock Weather for {loc}: Sunny, 25°C"

    async def tavily_search(query):
        if "攻略" in query:
            return "Mock Guide: 推荐去外滩、迪士尼和东方明珠。"
        return "Mock Search Result"

# =============================================================================
# 全局初始化 (Global Initialization)
# =============================================================================

# 1. 初始化 Google Search (SerpApi)
try:
    from serpapi import GoogleSearch
except ImportError:
    GoogleSearch = None
    print("Warning: 'google-search-results' not installed. Flight search will not work.")

# 2. 初始化全球机场数据库 (airportsdata)
AIRPORTS_DB = {}
try:
    import airportsdata
    print("正在加载全球机场数据库 (airportsdata)...")
    AIRPORTS_DB = airportsdata.load('IATA')
    print(f"数据库加载完成，共包含 {len(AIRPORTS_DB)} 个机场。")
except ImportError:
    print("Warning: 'airportsdata' library not found. Airport code lookup will fail.")
except Exception as e:
    print(f"Warning: Failed to load airport database: {e}")


# =============================================================================
# 数据库交互工具 (Database Tools)
# =============================================================================

@tool
async def lock_flight(flight_number: str, date: str, user_id: str = "default_user", from_airport: str = "Unknown", to_airport: str = "Unknown", passenger: str = "Unknown"):
    """锁定机票订单"""
    print(
        f"调用锁定机票订单: flight_number={flight_number}, user_id={user_id}, from={from_airport}, to={to_airport}, date={date}, passenger={passenger}")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    flight_data = {
        "flight_number": flight_number,
        "from": from_airport,
        "to": to_airport,
        "date": date,
        "passenger": passenger
    }
    order_id = await async_lock_flight(db, flight_data, user_id)
    await db_manager.close()
    if order_id:
        return str(order_id)
    else:
        raise Exception("Failed to lock flight order.")


@tool
async def lock_hotel(hotel_name: str, check_in: str, user_id: str = "default_user", location: str = "Unknown", check_out: str = "Unknown", guest: str = "Unknown"):
    """锁定酒店订单"""
    print(
        f"调用锁定酒店订单: user_id={user_id}, hotel_name={hotel_name}, location={location}, check_in={check_in}, check_out={check_out}, guest={guest}")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    hotel_data = {
        "name": hotel_name,
        "location": location,
        "check_in": check_in,
        "check_out": check_out,
        "guest": guest
    }
    order_id = await async_lock_hotel(db, hotel_data, user_id)
    await db_manager.close()
    if order_id:
        return str(order_id)
    else:
        raise Exception("Failed to lock hotel order.")


@tool
async def confirm_flight(order_id: str):
    """确认机票订单"""
    print(f"调用确认机票订单: order_id={order_id}")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    success = await async_confirm_flight(db, order_id)
    await db_manager.close()
    if success:
        return f"Successfully confirmed flight order {order_id}."
    else:
        return f"Failed to confirm flight order {order_id}."


@tool
async def confirm_hotel(order_id: str):
    """确认酒店订单"""
    print(f"调用确认酒店订单: order_id={order_id}")
    db_manager = AsyncDatabaseManager()
    await db_manager.ping()
    db = db_manager.get_db()
    success = await async_confirm_hotel(db, order_id)
    await db_manager.close()
    if success:
        return f"Successfully confirmed hotel order {order_id}."
    else:
        return f"Failed to confirm hotel order {order_id}."


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
# 信息查询工具 (Info Retrieval Tools: Weather & Search)
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
async def search_hotels(location: str, check_in: str, check_out: str = "unknown"):
    """
    查询实际酒店信息 (使用 Google Hotels Engine)。
    Args:
        location: 地点 (如 "Shanghai", "Tokyo")
        check_in: 入住日期 (YYYY-MM-DD)
        check_out: 退房日期 (YYYY-MM-DD)
    """
    if not GoogleSearch:
        return "System Error: 'google-search-results' library is missing. Please install it."

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return "System Error: SERPAPI_API_KEY environment variable is missing."

    # 默认逻辑: 如果未提供退房日期，默认设置为入住日期后 1 天
    if check_out == "unknown" or not check_out:
        try:
            dt = datetime.strptime(check_in, "%Y-%m-%d")
            ret_dt = dt + timedelta(days=1)
            check_out = ret_dt.strftime("%Y-%m-%d")
            print(f"   -> Auto-filled check_out: {check_out} (+1 day)")
        except ValueError:
            pass

    print(
        f"🏨 [Tool] Searching hotels in {location} from {check_in} to {check_out}")

    params = {
        "engine": "google_hotels",
        "q": f"hotels in {location}",
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": "1",
        "currency": "CNY",
        "gl": "cn",
        "hl": "zh-cn",
        "api_key": api_key
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        properties = results.get("properties", [])
        if not properties:
            return f"No hotels found in {location}."

        parsed_hotels = []
        for hotel in properties[:5]:
            name = hotel.get("name", "Unknown Hotel")
            description = hotel.get("description", "")

            # 提取价格
            rate_info = hotel.get("rate_per_night", {})
            price = rate_info.get("lowest") or rate_info.get(
                "before_taxes_fees") or "N/A"

            # 提取评分
            rating = hotel.get("overall_rating", "N/A")
            reviews = hotel.get("reviews", 0)

            # 提取星级
            hotel_class = hotel.get("extracted_hotel_class") or hotel.get(
                "hotel_class", "N/A")

            # 提取链接
            link = hotel.get("link")

            # 提取图片
            images = hotel.get("images", [])
            thumbnail = images[0].get("thumbnail") if images else None

            # 提取设施 (前5个)
            amenities = hotel.get("amenities", [])[:5]
            amenities_str = ", ".join(amenities) if amenities else "N/A"

            item = {
                "name": name,
                "description": description,
                "price": price,
                "rating": rating,
                "reviews": reviews,
                "class": f"{hotel_class} Star" if str(hotel_class).isdigit() else str(hotel_class),
                "amenities": amenities_str,
                "link": link,
                "thumbnail": thumbnail
            }
            parsed_hotels.append(item)

        return json.dumps(parsed_hotels, ensure_ascii=False)

    except Exception as e:
        return f"API Error during hotel search: {str(e)}"


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
# 航班特定工具 (Flight Specific Tools)
# =============================================================================

@tool
def lookup_airport_code(query: str):
    """
    根据城市名称或机场名称查询 IATA 机场代码。
    如果你需要搜索航班，必须先使用此工具获取标准的 3 字母代码（如 PEK, JFK）。

    Args:
        query: 城市名 (如 "Beijing", "New York") 或 机场名 (如 "Heathrow", "Narita")
    """
    if not AIRPORTS_DB:
        return "系统错误: 机场数据库未加载，请联系管理员安装 'airportsdata'。"

    print(f"🔍 [Tool] 正在本地数据库搜索机场代码: {query}")

    query_lower = query.lower().strip()
    found_airports = []

    for code, data in AIRPORTS_DB.items():
        city = data.get('city', '').lower()
        name = data.get('name', '').lower()

        if query_lower == city or query_lower in name:
            info = f"{data['name']} ({code}) - {data['city']}, {data['country']}"
            found_airports.append(info)

    if found_airports:
        result_str = "\n".join(found_airports[:10])
        if len(found_airports) > 10:
            result_str += f"\n... (and {len(found_airports) - 10} more)"
        return f"Found the following airports for '{query}':\n{result_str}"

    return f"在本地数据库中未找到 '{query}' 的相关机场。请尝试使用更通用的城市名称（英文），或者使用 search_travel_guides 工具在线搜索 IATA 代码。"


@tool
def search_flights(origin: str, destination: str, date: str, return_date: str = None):
    """
    Search for real-time flight tickets using Google Flights engine.
    Returns structured data including airline, flight number, time, and price.

    Args:
        origin: Departure airport IATA code (e.g., "PEK", "JFK") - NOT city name.
        destination: Arrival airport IATA code (e.g., "HND", "LHR") - NOT city name.
        date: Departure date in "YYYY-MM-DD" format.
        return_date: Optional return date in "YYYY-MM-DD" format for round-trip.
    """
    if not GoogleSearch:
        return "System Error: 'google-search-results' library is missing. Please install it."

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return "System Error: SERPAPI_API_KEY environment variable is missing."

    # 默认逻辑: 如果未提供返程日期，默认设置为出发日期后 7 天
    if not return_date:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            ret_dt = dt + timedelta(days=7)
            return_date = ret_dt.strftime("%Y-%m-%d")
            print(f"   -> Auto-filled return_date: {return_date} (+7 days)")
        except ValueError:
            pass  # 日期格式错误交由 API 处理

    print(f"✈️ [Tool] Searching flights: {origin} -> {destination} on {date}" + (
        f" return {return_date}" if return_date else ""))

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": date,
        "currency": "CNY",
        "hl": "zh-cn",
        "api_key": api_key
    }

    if return_date:
        params["return_date"] = return_date

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        flight_results = results.get("best_flights", [])
        if not flight_results:
            flight_results = results.get("other_flights", [])

        if not flight_results:
            return f"No flights found from {origin} to {destination} on {date}."

        parsed_flights = []
        for flight in flight_results[:5]:
            flights_segments = flight.get("flights", [])
            if not flights_segments:
                continue

            first_segment = flights_segments[0]
            last_segment = flights_segments[-1]

            dep_time = first_segment.get(
                "departure_airport", {}).get("time", "N/A")
            arr_time = last_segment.get(
                "arrival_airport", {}).get("time", "N/A")

            flight_numbers = [
                f"{s.get('airline')} {s.get('flight_number')}" for s in flights_segments]
            flight_number_str = ", ".join(flight_numbers)

            airlines = list(set([s.get("airline")
                            for s in flights_segments if s.get("airline")]))
            airline_str = ", ".join(airlines)

            raw_price = flight.get('price', 'Unknown')
            price_display = f"¥{raw_price}" if str(
                raw_price).isdigit() else str(raw_price)

            item = {
                "airline": airline_str,
                "flight_number": flight_number_str,
                "departure": f"{origin} at {dep_time}",
                "arrival": f"{destination} at {arr_time}",
                "duration": f"{flight.get('total_duration')} min",
                "price": price_display,
                "link": flight.get("google_flights_url")
            }
            parsed_flights.append(item)

        return json.dumps(parsed_flights, ensure_ascii=False)

    except Exception as e:
        return f"API Error during flight search: {str(e)}"
