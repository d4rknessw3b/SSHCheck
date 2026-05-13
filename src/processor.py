"""
processor.py — Обрабатывает очередь SSH-событий:
  - сохраняет в БД
  - определяет геолокацию
  - отправляет алёрты в Telegram
  - выполняет авто-блокировку через ufw
"""
from __future__ import annotations

import asyncio
import logging
import subprocess

from telegram import Bot

from .config import Config
from .database import Database, SSHEvent
from .geo import get_geo, format_geo
from .bot import send_alert, format_alert

logger = logging.getLogger(__name__)

BLOCKED_IPS: set[str] = set()


async def process_events(
    queue: asyncio.Queue,
    db: Database,
    bot: Bot,
    config: Config,
) -> None:
    """Основной цикл обработки событий."""
    logger.info("Процессор событий запущен.")

    while True:
        try:
            event: SSHEvent = await queue.get()
            await _handle_event(event, db, bot, config)
            queue.task_done()
        except asyncio.CancelledError:
            logger.info("Процессор событий остановлен.")
            break
        except Exception as e:
            logger.error("Ошибка обработки события: %s", e, exc_info=True)


async def _handle_event(
    event: SSHEvent,
    db: Database,
    bot: Bot,
    config: Config,
) -> None:
    """Обрабатывает одно событие."""

    # 1. Сохраняем в БД
    await db.insert_event(event)

    # 2. Обрабатываем только неудачные попытки и неверных пользователей
    if event.event_type not in ("failed", "invalid_user"):
        if event.event_type == "accepted":
            # Уведомляем об успешном входе (это важно!)
            geo = await get_geo(event.ip, db, config.geo_cache_ttl) if config.geolocation else None
            geo_str = format_geo(geo)
            text = (
                f"🟢 *Успешный вход по SSH*\n\n"
                f"🖥 `{_escape(event.ip)}`\n"
                f"👤 Пользователь: `{_escape(event.username or '?')}`\n"
                f"🔑 Метод: `{_escape(event.auth_method or '?')}`\n"
                f"🌍 {_escape(geo_str)}"
            )
            await send_alert(bot, config.chat_id, text)
        return

    # 3. Проверяем whitelist
    if event.ip in config.whitelist_ips:
        logger.debug("IP %s в whitelist, пропускаю.", event.ip)
        return

    # 4. Считаем неудачные попытки за последний час
    failed_count = await db.get_failed_count(event.ip, since_minutes=60)
    total_count = await db.get_total_failed_count(event.ip)

    logger.info(
        "[%s] %s — попыток за час: %d, всего: %d",
        event.event_type, event.ip, failed_count, total_count
    )

    # 5. Проверяем порог алёрта
    if failed_count >= config.alert_threshold:
        already_alerted = await db.was_recently_alerted(event.ip, config.alert_cooldown)
        if not already_alerted:
            geo = await get_geo(event.ip, db, config.geo_cache_ttl) if config.geolocation else None
            geo_str = format_geo(geo)
            text = await format_alert(event, total_count, geo_str)
            await send_alert(bot, config.chat_id, text)
            await db.record_alert(event.ip)
            logger.info("Алёрт отправлен для %s", event.ip)

    # 6. Авто-блокировка через ufw
    if config.auto_block and total_count >= config.auto_block_threshold:
        if event.ip not in BLOCKED_IPS:
            await _block_ip(event.ip, config, bot)
            BLOCKED_IPS.add(event.ip)


async def _block_ip(ip: str, config: Config, bot: Bot) -> None:
    """Блокирует IP через ufw."""
    try:
        result = subprocess.run(
            ["ufw", "deny", "from", ip, "to", "any"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.warning("IP %s заблокирован через ufw.", ip)
            text = (
                f"🚫 *IP заблокирован*\n\n"
                f"`{_escape(ip)}` добавлен в ufw deny\n"
                f"Порог: {config.auto_block_threshold} попыток"
            )
            await send_alert(bot, config.chat_id, text)
        else:
            logger.error("ufw ошибка: %s", result.stderr)
    except Exception as e:
        logger.error("Не удалось заблокировать %s: %s", ip, e)


def _escape(text: str) -> str:
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))
