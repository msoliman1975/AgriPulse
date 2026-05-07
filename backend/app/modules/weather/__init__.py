"""Public surface for the `weather` module.

Other modules import `WeatherService` (Protocol) and the factory; the
internals (repository, models, router, schemas) are forbidden by the
"weather internals are private" import-linter contract.
"""

from app.modules.weather.service import WeatherService, get_weather_service

__all__ = ["WeatherService", "get_weather_service"]
