# from app.infras.db import AsyncDatabaseManager, async_insert_flight, async_insert_hotel, async_get_flights, async_get_hotels
# from fastapi import APIRouter
# from app.infras.agent import travel_supervisor

# router = APIRouter()


# @router.get("/")
# def read_root():
#     return {"message": "Welcome to LangChain Travel router API"}


# @router.post("/book-flight")
# async def book_flight_endpoint(from_airport: str, to_airport: str) -> dict:
#     db_manager = AsyncDatabaseManager()
#     await db_manager.ping()
#     db = db_manager.get_db()
#     flight_data = {
#         "from": from_airport,
#         "to": to_airport,
#         "date": "2025-11-01",
#         "passenger": "API User"
#     }
#     result = await async_insert_flight(db, flight_data)
#     await db_manager.close()
#     return {"message": "Flight booked", "id": str(result)}


# @router.post("/book-hotel")
# async def book_hotel_endpoint(hotel_name: str) -> dict:
#     db_manager = AsyncDatabaseManager()
#     await db_manager.ping()
#     db = db_manager.get_db()
#     hotel_data = {
#         "name": hotel_name,
#         "location": "New York",
#         "check_in": "2025-11-01",
#         "check_out": "2025-11-03",
#         "guest": "API User"
#     }
#     result = await async_insert_hotel(db, hotel_data)
#     await db_manager.close()
#     return {"message": "Hotel booked", "id": str(result)}


# @router.get("/flights")
# async def get_flights_endpoint():
#     db_manager = AsyncDatabaseManager()
#     await db_manager.ping()
#     db = db_manager.get_db()
#     flights = await async_get_flights(db)
#     await db_manager.close()
#     return {"flights": flights}


# @router.get("/hotels")
# async def get_hotels_endpoint():
#     db_manager = AsyncDatabaseManager()
#     await db_manager.ping()
#     db = db_manager.get_db()
#     hotels = await async_get_hotels(db)
#     await db_manager.close()
#     return {"hotels": hotels}
