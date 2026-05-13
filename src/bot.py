"""
bot.py — Telegram-бот для SSHCheck.
Команды: /start, /help, /stats, /top, /recent, /summary, /status
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from .config import Config
from .database import Database, SSHEvent
from .geo import get_geo, format_geo

logger = logging.getLogger(__name__)

# ─── Форматирование ──────────────────────────────────────────────────────────

ICONS = {
    "failed": "🔴",
    "accepted": "🟢",
    "invalid_user": "🟡",
    "disconnect": "⚪",
}


def _escape(text: str) -> str:
    """Экранирование для MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


async def format_alert(event: SSHEvent, count: int, geo_str: str) -> str:
    """Форматирует сообщение об атаке."""
    icon = ICONS.get(event.event_type, "⚠️")
    lines = [
        f"{icon} *Атака обнаружена* {icon}",
        "",
        f"🖥 `{_escape(event.ip)}`",
        f"👤 Пользователь: `{_escape(event.username or 'неизвестен')}`",
        f"🔑 Метод: `{_escape(event.auth_method or 'неизвестен')}`",
        f"🌍 {_escape(geo_str)}",
        f"📊 Попыток с этого IP: *{count}*",
        f"🕐 Время: `{_escape(event.timestamp)}`",
    ]
    return "\n".join(lines)


# ─── Хендлеры команд ────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🛡 *SSHCheck Bot* запущен\\!\n\n"
        "Я мониторю SSH\\-подключения к вашему серверу и уведомляю об атаках\\.\n\n"
        "Доступные команды:\n"
        "/stats — общая статистика\n"
        "/top — топ атакующих IP\n"
        "/recent — последние события\n"
        "/summary — подробный отчёт\n"
        "/status — статус сервиса\n"
        "/help — справка"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Справка SSHCheck*\n\n"
        "*/stats* — Краткая статистика\\: всего событий, неудачных, успешных\n"
        "*/top \\[N\\]* — Топ N \\(по умолчанию 10\\) атакующих IP\\-адресов\n"
        "*/recent \\[N\\]* — Последние N событий из лога\n"
        "*/summary* — Полный отчёт за последние 24 часа\n"
        "*/status* — Текущий статус мониторинга\n\n"
        "Алёрты отправляются автоматически при превышении порога атак\\."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.bot_data["db"]
    stats = await db.get_stats_summary()

    text = (
        "📊 *Статистика SSH*\n\n"
        f"📋 Всего событий: *{stats['total_events']}*\n"
        f"🔴 Неудачных попыток: *{stats['total_failed']}*\n"
        f"🟢 Успешных входов: *{stats['total_accepted']}*\n"
        f"🌐 Уникальных атакующих IP: *{stats['unique_ips']}*\n\n"
        f"📅 За сегодня \\(неудачных\\): *{stats['today_failed']}*\n"
        f"⏱ За последний час: *{stats['hour_failed']}*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.bot_data["db"]
    config: Config = ctx.bot_data["config"]

    # Разбираем аргумент: /top 5
    try:
        limit = int(ctx.args[0]) if ctx.args else 10
        limit = max(1, min(limit, 25))
    except (ValueError, IndexError):
        limit = 10

    top_ips = await db.get_top_ips(limit=limit)
    top_users = await db.get_top_usernames(limit=5)

    if not top_ips:
        await update.message.reply_text("✅ Нет данных об атаках.")
        return

    lines = [f"🏆 *Топ\\-{limit} атакующих IP*\n"]
    for i, (ip, cnt) in enumerate(top_ips, 1):
        geo = await get_geo(ip, db, config.geo_cache_ttl) if config.geolocation else None
        geo_short = f"{geo.country_code}" if geo else "??"
        lines.append(f"{i}\\. `{_escape(ip)}` \\— *{cnt}* попыток \\({_escape(geo_short)}\\)")

    if top_users:
        lines.append("\n👤 *Топ\\-5 целевых пользователей*")
        for user, cnt in top_users:
            lines.append(f"  • `{_escape(user)}` — {cnt}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_recent(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.bot_data["db"]

    try:
        limit = int(ctx.args[0]) if ctx.args else 10
        limit = max(1, min(limit, 20))
    except (ValueError, IndexError):
        limit = 10

    events = await db.get_recent_events(limit=limit)

    if not events:
        await update.message.reply_text("📭 Нет записанных событий.")
        return

    lines = [f"📜 *Последние {len(events)} событий*\n"]
    for row in events:
        icon = ICONS.get(row["event_type"], "⚪")
        ts = row["timestamp"][11:19]  # Только время HH:MM:SS
        ip = _escape(row["ip"])
        user = _escape(row["username"] or "—")
        lines.append(f"{icon} `{ts}` `{ip}` → {user}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.bot_data["db"]
    config: Config = ctx.bot_data["config"]

    await update.message.reply_text("⏳ Формирую отчёт...")

    stats = await db.get_stats_summary()
    top_ips = await db.get_top_ips(limit=5)
    top_users = await db.get_top_usernames(limit=5)

    now = datetime.utcnow().strftime("%Y\\-%m\\-%d %H:%M UTC")
    lines = [
        f"📋 *Сводный отчёт SSHCheck*",
        f"🕐 {now}\n",
        f"📊 *Статистика за всё время:*",
        f"  • Неудачных попыток: *{stats['total_failed']}*",
        f"  • Успешных входов: *{stats['total_accepted']}*",
        f"  • Уникальных IP\\-атакующих: *{stats['unique_ips']}*",
        f"  • За сегодня \\(неудач\\): *{stats['today_failed']}*",
        f"  • За последний час: *{stats['hour_failed']}*\n",
    ]

    if top_ips:
        lines.append("🏆 *Топ\\-5 атакующих IP:*")
        for i, (ip, cnt) in enumerate(top_ips, 1):
            geo = await get_geo(ip, db, config.geo_cache_ttl) if config.geolocation else None
            geo_str = f"{geo.country}, {geo.city}" if geo else "Unknown"
            lines.append(f"  {i}\\. `{_escape(ip)}` — {cnt} попыток \\({_escape(geo_str)}\\)")

    if top_users:
        lines.append("\n👤 *Топ\\-5 атакуемых аккаунтов:*")
        for user, cnt in top_users:
            lines.append(f"  • `{_escape(user)}` — {cnt} попыток")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uptime: datetime = ctx.bot_data.get("start_time", datetime.utcnow())
    delta = datetime.utcnow() - uptime
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60

    config: Config = ctx.bot_data["config"]
    text = (
        "✅ *SSHCheck работает*\n\n"
        f"⏱ Аптайм: *{hours}ч {minutes}м*\n"
        f"📂 Лог: `{_escape(config.log_file)}`\n"
        f"🔔 Порог алёрта: *{config.alert_threshold}* попыток\n"
        f"⏳ Кулдаун алёрта: *{config.alert_cooldown}* сек\n"
        f"🌍 Геолокация: {'включена' if config.geolocation else 'отключена'}\n"
        f"🚫 Авто\\-блокировка: {'включена' if config.auto_block else 'отключена'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


# ─── Публичный API ───────────────────────────────────────────────────────────

def build_application(config: Config, db: Database) -> Application:
    """Создаёт и настраивает Telegram-приложение."""
    app = Application.builder().token(config.bot_token).build()

    app.bot_data["db"] = db
    app.bot_data["config"] = config
    app.bot_data["start_time"] = datetime.utcnow()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("status", cmd_status))

    return app


async def send_alert(bot: Bot, chat_id: int, text: str) -> None:
    """Отправляет сообщение-алёрт в указанный чат."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        logger.error("Ошибка отправки алёрта: %s", e)


async def send_summary(bot: Bot, chat_id: int, db: Database, config: Config) -> None:
    """Отправляет периодический сводный отчёт."""
    stats = await db.get_stats_summary()
    top_ips = await db.get_top_ips(limit=5)

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"📊 *Плановый отчёт* \\| {_escape(now)}\n",
        f"🔴 За последний час: *{stats['hour_failed']}* неудачных попыток",
        f"📅 За сегодня: *{stats['today_failed']}*",
        f"🌐 Всего уникальных атакующих IP: *{stats['unique_ips']}*",
    ]

    if top_ips and stats["hour_failed"] > 0:
        lines.append("\n🏆 Самые активные сейчас:")
        for ip, cnt in top_ips[:3]:
            geo = await get_geo(ip, db, config.geo_cache_ttl) if config.geolocation else None
            geo_short = f"{geo.country_code}" if geo else "??"
            lines.append(f"  • `{_escape(ip)}` — {cnt} попыток \\({_escape(geo_short)}\\)")

    await send_alert(bot, chat_id, "\n".join(lines))
