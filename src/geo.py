"""
geo.py — Геолокация IP-адресов через бесплатный ip-api.com.
Использует кэш из БД для снижения числа запросов.
"""
from __future__ import annotations

import logging
from typing import Optional

import aiohttp

from .database import Database, GeoInfo

logger = logging.getLogger(__name__)

GEO_API_URL = "http://ip-api.com/json/{ip}?fields=status,country,countryCode,city,org"

# Флаги стран для красивого отображения
COUNTRY_FLAGS: dict[str, str] = {
    "RU": "🇷🇺", "US": "🇺🇸", "CN": "🇨🇳", "DE": "🇩🇪", "GB": "🇬🇧",
    "FR": "🇫🇷", "NL": "🇳🇱", "UA": "🇺🇦", "BR": "🇧🇷", "IN": "🇮🇳",
    "KR": "🇰🇷", "JP": "🇯🇵", "SG": "🇸🇬", "HK": "🇭🇰", "VN": "🇻🇳",
    "TR": "🇹🇷", "IR": "🇮🇷", "ID": "🇮🇩", "TH": "🇹🇭", "PK": "🇵🇰",
}


def _is_private_ip(ip: str) -> bool:
    """Проверяет, является ли IP приватным/локальным."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return (
        a == 10
        or (a == 172 and 16 <= b <= 31)
        or (a == 192 and b == 168)
        or a == 127
        or ip.startswith("::1")
    )


async def get_geo(ip: str, db: Database, ttl: int = 86400) -> Optional[GeoInfo]:
    """Возвращает геолокацию IP. Сначала проверяет кэш, затем запрашивает API."""
    if _is_private_ip(ip):
        return GeoInfo(country="Local Network", country_code="LO", city="localhost", org="Private")

    # Проверяем кэш
    cached = await db.get_geo(ip, ttl)
    if cached:
        return cached

    # Запрашиваем API
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(GEO_API_URL.format(ip=ip)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if data.get("status") != "success":
            return None

        geo = GeoInfo(
            country=data.get("country", "Unknown"),
            country_code=data.get("countryCode", "??"),
            city=data.get("city", "Unknown"),
            org=data.get("org", "Unknown"),
        )
        await db.save_geo(ip, geo)
        return geo

    except Exception as e:
        logger.debug("Geo lookup failed for %s: %s", ip, e)
        return None


def format_geo(geo: Optional[GeoInfo]) -> str:
    """Форматирует геолокацию для отображения."""
    if geo is None:
        return "🌍 Unknown"
    flag = COUNTRY_FLAGS.get(geo.country_code, "🌐")
    return f"{flag} {geo.country}, {geo.city} | {geo.org}"
