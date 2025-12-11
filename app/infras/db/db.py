import asyncio
from motor.motor_asyncio import AsyncIOMotorClient


class AsyncDatabaseManager:
    """异步数据库管理器，使用连接池 (Singleton Pattern)"""

    _client = None
    _db = None

    def __init__(self, uri="mongodb://localhost:27017/", db_name="test"):
        """初始化异步连接"""
        if AsyncDatabaseManager._client is None:
            AsyncDatabaseManager._client = AsyncIOMotorClient(
                uri, maxPoolSize=10, minPoolSize=2)
            AsyncDatabaseManager._db = AsyncDatabaseManager._client[db_name]
            print("AsyncDatabaseManager: Created new MongoDB connection pool")

        self._client = AsyncDatabaseManager._client
        self._db = AsyncDatabaseManager._db

    async def ping(self):
        """测试连接"""
        try:
            await self._db.command("ping")
            print(f"AsyncDatabaseManager: 成功连接到 MongoDB 数据库: {self._db.name}")
            return True
        except Exception as e:
            print(f"AsyncDatabaseManager: MongoDB 连接失败: {e}")
            return False

    def get_db(self):
        """获取数据库实例"""
        return self._db

    async def close(self):
        """
        关闭连接
        注意：由于现在是单例模式，调用此方法不会真正关闭全局连接，
        以防止影响其他正在使用的请求。
        """
        pass


async def async_insert_flight(db, flight_data):
    """异步插入 flight 数据"""
    try:
        collection = db['flights']
        result = await collection.insert_one(flight_data)
        print(f"成功插入 flight: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        print(f"插入 flight 失败: {e}")
        return None


async def async_insert_hotel(db, hotel_data):
    """异步插入 hotel 数据"""
    try:
        collection = db['hotels']
        result = await collection.insert_one(hotel_data)
        print(f"成功插入 hotel: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        print(f"插入 hotel 失败: {e}")
        return None


async def async_get_flights(db):
    """异步查询所有 flights"""
    try:
        collection = db['flights']
        flights = await collection.find().to_list(length=None)
        print(f"查询到 {len(flights)} 个 flights:")
        for flight in flights:
            print(flight)
        return flights
    except Exception as e:
        print(f"查询 flights 失败: {e}")
        return []


async def async_get_hotels(db):
    """异步查询所有 hotels"""
    try:
        collection = db['hotels']
        hotels = await collection.find().to_list(length=None)
        print(f"查询到 {len(hotels)} 个 hotels:")
        for hotel in hotels:
            print(hotel)
        return hotels
    except Exception as e:
        print(f"查询 hotels 失败: {e}")
        return []


if __name__ == "__main__":
    async def example():
        db_manager = AsyncDatabaseManager()
        await db_manager.ping()
        db = db_manager.get_db()
        await async_insert_flight(db, {"from": "BOS", "to": "JFK"})
        await db_manager.close()

    asyncio.run(example())
