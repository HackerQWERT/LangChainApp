import pytest
from third_api.weather import fetch_weather_report


@pytest.mark.asyncio
async def test_fetch_weather_report_real_api():
    """
    Integration test using real HTTP requests to Open-Meteo API.
    """
    location = "London"
    result = await fetch_weather_report(location)

    # Print result for visibility if run with -s
    print(f"\nReal API Response:\n{result}")

    # Assertions based on expected structure since data is dynamic
    assert "Weather Report for London" in result
    assert "Current:" in result
    assert "Forecast:" in result
    assert "°C" in result

    # Check for specific weather descriptions or structure parts
    # We can't check specific temperatures, but we can check format
    assert "High" in result
    assert "Low" in result


@pytest.mark.asyncio
async def test_fetch_weather_report_real_api_not_found():
    """
    Integration test for a non-existent location.
    """
    location = "ThisCityDoesNotExist12345"
    result = await fetch_weather_report(location)

    assert "Error: Could not find location" in result
