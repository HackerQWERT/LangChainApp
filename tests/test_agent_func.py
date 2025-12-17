from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import pytest
import os
from app.infras.func.agent_func import search_flights, search_travel_guides, lookup_airport_code
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@pytest.fixture(scope="session", autouse=True)
def load_serpapi_key():
    if not os.environ.get("SERPAPI_API_KEY"):
        # Try to load from .env if not in environment
        from dotenv import load_dotenv
        load_dotenv()


@pytest.mark.asyncio
async def test_lookup_airport_code():
    query = "Tokyo"

    result = await lookup_airport_code.ainvoke(query)
    print(f"Lookup result for '{query}': {result}")
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_search_flights():
    if not os.environ.get("SERPAPI_API_KEY"):
        pytest.skip("SERPAPI_API_KEY not set, skipping integration test")

    departure = "PEK"
    arrival = "LAX"
    date_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    return_date_str = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

    result = await search_flights.ainvoke({"origin": departure, "destination": arrival, "date": date_str, "return_date": return_date_str})
    print(
        f"Flight search result from {departure} to {arrival} on {date_str} return {return_date_str}: {result}")
    assert isinstance(result, str)
    assert "airline" in result or "No flights found" in result


@pytest.mark.asyncio
async def test_search_google_flights():
    from serpapi import GoogleSearch

    params = {
        "engine": "google_flights",
        "departure_id": "PEK",
        "arrival_id": "AUS",
        "outbound_date": "2025-12-17",
        "return_date": "2025-12-23",
        "currency": "USD",
        "hl": "en",
        "api_key": os.environ.get("SERPAPI_API_KEY")
    }

    search = GoogleSearch(params)
    results = search.get_dict()
    print(f"Google Flights API raw results: {results}")


@pytest.mark.asyncio
async def test_search_google_hotels():
    from serpapi import GoogleSearch
    params = {
        "engine": "google_hotels",
        "q": "Los Angeles",
        "check_in_date": "2025-12-17",
        "check_out_date": "2025-12-23",
        "currency": "USD",
        "hl": "en",
        "api_key": os.environ.get("SERPAPI_API_KEY")
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    print(f"Google Hotels API raw results: {results}")


@pytest.mark.asyncio
async def test_search_hotels():
    from app.infras.func.agent_func import search_hotels

    location = "Los Angeles"
    check_in = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    check_out = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")

    result = await search_hotels.ainvoke({"location": location, "check_in": check_in, "check_out": check_out})
    print(
        f"Hotel search result in {location} from {check_in} to {check_out}: {result}")
    assert isinstance(result, str)
    assert "hotel" in result or "No hotels found" in result
