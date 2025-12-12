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


async def async_lock_flight(db, flight_data, user_id):
    """异步锁定 flight 订单"""
    try:
        collection = db['flights']
        flight_data['locked_by_user_id'] = user_id
        flight_data['status'] = 'locked'
        result = await collection.insert_one(flight_data)
        print(f"成功锁定 flight 订单: {result.inserted_id}")
        return str(result.inserted_id)
    except Exception as e:
        print(f"锁定 flight 订单失败: {e}")
        return None


async def async_confirm_flight(db, order_id):
    """异步确认 flight 订单"""
    try:
        from bson import ObjectId
        collection = db['flights']
        result = await collection.update_one(
            {'_id': ObjectId(order_id), 'status': 'locked'},
            {'$set': {'status': 'confirmed'}}
        )
        if result.modified_count > 0:
            print(f"成功确认 flight 订单: {order_id}")
            return True
        else:
            print(f"确认 flight 订单失败: 未找到锁定订单 {order_id}")
            return False
    except Exception as e:
        print(f"确认 flight 订单失败: {e}")
        return False


async def async_lock_hotel(db, hotel_data, user_id):
    """异步锁定 hotel 订单"""
    try:
        collection = db['hotels']
        hotel_data['locked_by_user_id'] = user_id
        hotel_data['status'] = 'locked'
        result = await collection.insert_one(hotel_data)
        print(f"成功锁定 hotel 订单: {result.inserted_id}")
        return str(result.inserted_id)
    except Exception as e:
        print(f"锁定 hotel 订单失败: {e}")
        return None


async def async_confirm_hotel(db, order_id):
    """异步确认 hotel 订单"""
    try:
        from bson import ObjectId
        collection = db['hotels']
        result = await collection.update_one(
            {'_id': ObjectId(order_id), 'status': 'locked'},
            {'$set': {'status': 'confirmed'}}
        )
        if result.modified_count > 0:
            print(f"成功确认 hotel 订单: {order_id}")
            return True
        else:
            print(f"确认 hotel 订单失败: 未找到锁定订单 {order_id}")
            return False
    except Exception as e:
        print(f"确认 hotel 订单失败: {e}")
        return False


if __name__ == "__main__":
    async def example():
        db_manager = AsyncDatabaseManager()
        await db_manager.ping()
        db = db_manager.get_db()
        # await async_insert_flight(db, {"from": "BOS", "to": "JFK"})
        await async_get_flights(db)
        await db_manager.close()

    asyncio.run(example())
