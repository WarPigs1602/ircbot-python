from plugin_system import CommandSpec, PluginSpec


WEATHER_CODE_MAPS = {
    "de": {
        0: "klar",
        1: "ueberwiegend klar",
        2: "leicht bewolkt",
        3: "bewolkt",
        45: "Nebel",
        48: "Reifnebel",
        51: "leichter Nieselregen",
        53: "Nieselregen",
        55: "starker Nieselregen",
        61: "leichter Regen",
        63: "Regen",
        65: "starker Regen",
        71: "leichter Schneefall",
        73: "Schneefall",
        75: "starker Schneefall",
        80: "Regenschauer",
        81: "starke Regenschauer",
        82: "heftige Regenschauer",
        95: "Gewitter",
        96: "Gewitter mit Hagel",
        99: "Gewitter mit Hagel",
    },
    "en": {
        0: "clear",
        1: "mostly clear",
        2: "partly cloudy",
        3: "cloudy",
        45: "fog",
        48: "depositing rime fog",
        51: "light drizzle",
        53: "drizzle",
        55: "dense drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "rain showers",
        81: "strong rain showers",
        82: "violent rain showers",
        95: "thunderstorm",
        96: "thunderstorm with hail",
        99: "thunderstorm with hail",
    },
}


MESSAGES = {
    "de": {
        "usage_weather": "Nutzung: {prefix}{command} <ort>",
        "weather_not_found": "Wetter für {location}: Ort nicht gefunden.",
        "weather_unreachable": "Wetter für {location}: Daten nicht erreichbar.",
        "weather_for": "Wetter für {location}: {temperature}°C, {condition}, gefühlt {feels_like}°C, Luftfeuchtigkeit {humidity}%, Niederschlag {precipitation} mm, Wind {wind_speed} km/h",
        "weather_short": "Wetter für {location}: {condition}",
        "weather_cc": "Wetter für {location}",
        "humidity": "Luftfeuchtigkeit",
        "precipitation": "Niederschlag",
        "wind": "Wind",
        "unknown": "unbekannt",
    },
    "en": {
        "usage_weather": "Usage: {prefix}{command} <location>",
        "weather_not_found": "Weather for {location}: location not found.",
        "weather_unreachable": "Weather for {location}: data unavailable.",
        "weather_for": "Weather for {location}: {temperature}°C, {condition}, feels like {feels_like}°C, humidity {humidity}%, precipitation {precipitation} mm, wind {wind_speed} km/h",
        "weather_short": "Weather for {location}: {condition}",
        "weather_cc": "Weather for {location}",
        "humidity": "Humidity",
        "precipitation": "Precipitation",
        "wind": "Wind",
        "unknown": "unknown",
    },
}


def handle_weather(bot, context, arg: str) -> None:
    weather_text = bot.get_weather_text(arg.strip(), context.command_prefix, context.reply_target)
    bot.send_privmsg(context.reply_target, weather_text)


PLUGIN = PluginSpec(
    name="weather",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="weather",
            handler=handle_weather,
            aliases=("wetter",),
            primary_names={"de": "wetter", "en": "weather"},
            help_args={"de": "<ort>", "en": "<location>"},
            help_sort=100,
        ),
    ),
)