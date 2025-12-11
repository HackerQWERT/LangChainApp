import pytest
import os
from app.infras.func.agent_func import search_travel_guides


@pytest.mark.asyncio
async def test_search_travel_guides_integration():
    # Ensure API key is present (optional check, but good for debugging)
    if not os.environ.get("TAVILY_API_KEY"):
        # Try to load from .env if not in environment
        from dotenv import load_dotenv
        load_dotenv()

    if not os.environ.get("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY not set, skipping integration test")

    query = "Tokyo travel guide"

    # Actual call to the tool
    result = await search_travel_guides.ainvoke(query)

    # Assertions
    assert isinstance(result, str)
    assert len(result) > 0

    # Check for expected content in the real response
    # The implementation returns "Summary: ..." or "Source: ..." or error message
    if "Error" in result and "TAVILY_API_KEY" in result:
        pytest.fail(f"Tavily API Key missing or invalid: {result}")

    # We expect some content related to the search
    # Note: Real search results are dynamic, but usually contain the query keywords
    assert "Tokyo" in result or "Japan" in result
    assert "Summary:" in result or "Source:" in result
