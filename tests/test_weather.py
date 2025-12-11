import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from third_api.weather import fetch_weather_report


@pytest.mark.asyncio
async def test_fetch_weather_report_success():
    # Mock data
    mock_geo_data = {
        "results": [
            {
                "latitude": 52.52,
                "longitude": 13.41,
                "name": "Berlin",
                "country": "Germany"
            }
        ]
    }

    mock_weather_data = {
        "current_weather": {
            "temperature": 20.0,
            "weathercode": 0
        },
        "daily": {
            "time": ["2023-10-27"],
            "weathercode": [0],
            "temperature_2m_max": [22.0],
            "temperature_2m_min": [15.0]
        }
    }

    # Mock httpx.AsyncClient
    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        MockClient.return_value = mock_client_instance
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        # Setup side_effect for client.get to return different responses based on URL
        async def get_side_effect(url, params=None):
            mock_response = MagicMock()
            if "geocoding-api" in url:
                mock_response.json.return_value = mock_geo_data
            elif "api.open-meteo.com" in url:
                mock_response.json.return_value = mock_weather_data
            return mock_response

        mock_client_instance.get.side_effect = get_side_effect

        # Run the function
        result = await fetch_weather_report("Berlin")

        # Assertions
        assert "Weather Report for Berlin, Germany" in result
        assert "Current: Clear sky, 20.0°C" in result
        assert "2023-10-27: Clear sky, High 22.0°C / Low 15.0°C" in result


@pytest.mark.asyncio
async def test_fetch_weather_report_location_not_found():
    # Mock data for no results
    mock_geo_data = {"results": []}

    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        MockClient.return_value = mock_client_instance
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        async def get_side_effect(url, params=None):
            mock_response = MagicMock()
            if "geocoding-api" in url:
                mock_response.json.return_value = mock_geo_data
            return mock_response

        mock_client_instance.get.side_effect = get_side_effect

        # Run the function
        result = await fetch_weather_report("UnknownCity")

        # Assertions
        assert "Error: Could not find location 'UnknownCity'" in result
