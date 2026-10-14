from typing import Any
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import httpx
import os
from mcp.server.fastmcp import FastMCP

# Both providers put credentials in query parameters; do not log request URLs.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Initialize FastMCP server
port = int(os.getenv("PORT", 8085))
mcp = FastMCP("weather", host="0.0.0.0", port=port)

# Constants
WEATHERAPI_BASE = "https://api.weatherapi.com/v1"
USER_AGENT = "weather-app/1.0"

# Get API key from environment variable
API_KEY = os.getenv("WEATHERAPI_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


async def make_openweather_request(endpoint: str, params: dict) -> Any:
    """Call OpenWeather without exposing the API key in error messages."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"https://api.openweathermap.org/{endpoint}",
                params={**params, "appid": OPENWEATHER_API_KEY},
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            print(f"OpenWeather HTTP error: {error.response.status_code}")
        except httpx.RequestError as error:
            print(f"OpenWeather request failed: {type(error).__name__}")
    return None


async def openweather_data(city: str, endpoint: str) -> dict | None:
    # Use the dedicated geocoder; built-in city lookup is deprecated.
    # https://openweathermap.org/api/geocoding-api
    locations = await make_openweather_request("geo/1.0/direct", {"q": city, "limit": 1})
    if not locations:
        return None
    location = locations[0]
    data = await make_openweather_request(
        f"data/2.5/{endpoint}",
        {"lat": location["lat"], "lon": location["lon"], "units": "metric"},
    )
    if data:
        data["_location_name"] = location["name"]
    return data


def format_openweather_current(data: dict) -> str:
    # dt is the UTC data-calculation time; metric wind is m/s.
    # https://openweathermap.org/api/current
    current = data["main"]
    updated = datetime.fromtimestamp(
        data["dt"], timezone(timedelta(seconds=data["timezone"]))
    ).isoformat()
    visibility = f"{data['visibility'] / 1000} km" if "visibility" in data else "unavailable"
    return f"""Current Weather for {data['name']}, {data['sys']['country']}:
Source: OpenWeather Current Weather API

Temperature: {current['temp']}°C
Feels like: {current['feels_like']}°C
Condition: {data['weather'][0]['description']}
Humidity: {current['humidity']}%
Wind: {round(data['wind']['speed'] * 3.6, 2)} km/h, {data['wind'].get('deg', 'unknown')}°
Pressure: {current['pressure']} hPa
UV Index: unavailable in this API
Visibility: {visibility}
Last updated (data calculation, local time): {updated}
"""


def format_openweather_forecast(data: dict, days: int) -> str:
    # Group 3-hour samples by city-local date. These are interval aggregates,
    # not the provider's daily min/max or daily precipitation probability.
    # https://openweathermap.org/api/forecast5
    local_tz = timezone(timedelta(seconds=data["city"]["timezone"]))
    grouped: dict[str, list] = {}
    for interval in data["list"]:
        date = datetime.fromtimestamp(interval["dt"], local_tz).date().isoformat()
        grouped.setdefault(date, []).append(interval)
    forecasts = [
        f"Weather Forecast for {data.get('_location_name', data['city']['name'])}, {data['city']['country']}:",
        f"OpenWeather location label: {data['city']['name']}",
        "Source: OpenWeather 5-day / 3-hour forecast. First day may be partial.",
        "High/low are extrema of available 3-hour temperatures; rain chance is the maximum interval probability.",
    ]
    for date in sorted(grouped)[:max(1, min(days, 3))]:
        intervals = grouped[date]
        temps = [item["main"]["temp"] for item in intervals]
        conditions = ", ".join(dict.fromkeys(item["weather"][0]["description"] for item in intervals))
        rain = round(max(item.get("pop", 0) for item in intervals) * 100)
        wind = round(max(item["wind"]["speed"] for item in intervals) * 3.6, 2)
        forecasts.append(f"""{date} (local date; {len(intervals)} forecast intervals):
High (interval maximum): {max(temps)}°C
Low (interval minimum): {min(temps)}°C
Condition: {conditions}
Chance of Rain (maximum 3-hour probability): {rain}%
Max Wind: {wind} km/h
UV Index: unavailable in this API""")
    return "\n---\n".join(forecasts)

async def make_weather_request(endpoint: str, params: dict[str, str]) -> dict[str, Any] | None:
    """Make a request to the WeatherAPI with proper error handling."""
    # Check if API key is set
    if not API_KEY:
        print("ERROR: WeatherAPI key not set. Please set WEATHERAPI_KEY environment variable.")
        return None
        
    headers = {
        "User-Agent": USER_AGENT,
    }
    # Add API key to parameters
    params["key"] = API_KEY
    
    url = f"{WEATHERAPI_BASE}/{endpoint}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"HTTP Error {e.response.status_code}: {e.response.text}")
            return None
        except httpx.RequestError as e:
            print(f"WeatherAPI request failed: {type(e).__name__}")
            return None
        except Exception as e:
            print(f"WeatherAPI unexpected error: {type(e).__name__}")
            return None

@mcp.tool()
async def get_current_weather(city: str) -> str:
    """Get current weather conditions for a city.

    Args:
        city: City name (e.g., "Hanoi", "Haiphong", "Danang", "Brisbane", "Sydney")
    """
    if OPENWEATHER_API_KEY and not API_KEY:
        data = await openweather_data(city, "weather")
        if data:
            return format_openweather_current(data)
        return f"Unable to fetch OpenWeather data for {city}. Check the city name and active OPENWEATHER_API_KEY."

    params = {
        "q": city,
        "aqi": "no"
    }
    
    data = await make_weather_request("current.json", params)

    if not data:
        if not API_KEY:
            return f"❌ WeatherAPI key not configured. Please set WEATHERAPI_KEY environment variable with your API key from weatherapi.com"
        return f"Unable to fetch current weather data for {city}. Please check the city name and API key configuration."

    current = data["current"]
    location = data["location"]
    
    return f"""
Current Weather for {location['name']}, {location['region']}, {location['country']}:

Temperature: {current['temp_c']}°C ({current['temp_f']}°F)
Feels like: {current['feelslike_c']}°C ({current['feelslike_f']}°F)
Condition: {current['condition']['text']}
Humidity: {current['humidity']}%
Wind: {current['wind_kph']} km/h ({current['wind_mph']} mph) {current['wind_dir']}
Pressure: {current['pressure_mb']} mb
UV Index: {current['uv']}
Visibility: {current['vis_km']} km

Last updated: {current['last_updated']}
"""

@mcp.tool()
async def get_forecast(city: str, days: int = 3) -> str:
    """Get weather forecast for a city.

    Args:
        city: City name (e.g., "Hanoi", "Haiphong", "Danang", "Brisbane", "Sydney", "Melbourne")
        days: Number of days to forecast (limited to 1-3 in this lab)
    """
    if OPENWEATHER_API_KEY and not API_KEY:
        data = await openweather_data(city, "forecast")
        if data:
            return format_openweather_forecast(data, days)
        return f"Unable to fetch OpenWeather forecast for {city}. Check the city name and active OPENWEATHER_API_KEY."

    # Limit days to 3 for free tier
    days = min(days, 3)
    
    params = {
        "q": city,
        "days": str(days),
        "aqi": "no",
        "alerts": "no"
    }
    
    data = await make_weather_request("forecast.json", params)

    if not data:
        if not API_KEY:
            return f"❌ WeatherAPI key not configured. Please set WEATHERAPI_KEY environment variable with your API key from weatherapi.com"
        return f"Unable to fetch forecast data for {city}. Please check the city name and API key configuration."

    location = data["location"]
    forecast_days = data["forecast"]["forecastday"]
    
    forecasts = []
    forecasts.append(f"Weather Forecast for {location['name']}, {location['region']}, {location['country']}:")
    
    for day in forecast_days:
        day_data = day["day"]
        date = day["date"]
        
        forecast = f"""
{date}:
High: {day_data['maxtemp_c']}°C ({day_data['maxtemp_f']}°F)
Low: {day_data['mintemp_c']}°C ({day_data['mintemp_f']}°F)
Condition: {day_data['condition']['text']}
Chance of Rain: {day_data['daily_chance_of_rain']}%
Max Wind: {day_data['maxwind_kph']} km/h
UV Index: {day_data['uv']}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)

@mcp.tool()
async def health_check() -> str:
    """Health check endpoint for deployment verification."""
    return "✅ Weather MCP Server is running! Ready to provide weather data for Australian cities and worldwide."

print("✅ MCP server initialized with Streamable HTTP transport")
print("🔧 Available tools: get_current_weather, get_forecast, health_check")

if __name__ == "__main__":
    import sys
    
    is_cloud_run = bool(os.getenv("PORT"))
    is_standalone = len(sys.argv) == 1 and sys.stdin.isatty()
    
    if is_cloud_run or is_standalone:
        print(f"🚀 Starting MCP server on http://0.0.0.0:{port}/mcp")
        mcp.run(transport="streamable-http")
    else:
        print("Starting FastMCP server in stdio mode for local client", file=sys.stderr)
        mcp.run()
