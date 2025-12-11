from app.infras.db import AsyncDatabaseManager, async_insert_flight, async_insert_hotel, async_get_flights, async_get_hotels
from langchain.tools import tool
from app.infras.third_api import fetch_weather_report
from datetime import datetime

from app.infras.third_api.tavily import tavily_search

# --- 现有数据库 Tools (保持不变) ---


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


# --- 真实天气实现 ---

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
async def search_flights(origin: str, destination: str, date: str):
    """
    查询实际航班信息。
    Args:
        origin: 出发地
        destination: 目的地
        date: 出发日期
    """
    query = f"flights from {origin} to {destination} on {date}"
    print(f"调用查询航班: {query}")
    return await tavily_search(query)


@tool
async def search_hotels(location: str, check_in: str, check_out: str):
    """
    查询实际酒店信息。
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
    查询实际景点门票信息。
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
