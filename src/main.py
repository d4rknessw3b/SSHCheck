"""
main.py — Точка входа SSHCheck.
Запускает три параллельные задачи:
  1. Мониторинг лог-файла
  2. Обработка событий (алёрты, БД, гео)
  3. Telegram-бот (polling)
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime

from .config import load_config
from .database import Database
from .log_monitor import monitor
from .processor import process_events
from .bot import build_application, send_alert, send_summary

# ─── Логирование ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sshcheck.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("sshcheck")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run() -> None:
    # 1. Конфигурация
    config = load_config("config.yml")
    logger.info("Конфигурация загружена. Chat ID: %s", config.chat_id)

    # 2. База данных
    db = Database(config.db_path)
    await db.connect()

    # 3. Очередь событий (буфер между монитором и процессором)
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    # 4. Telegram Application
    app = build_application(config, db)
    await app.initialize()
    await app.start()

    bot = app.bot

    # Стартовое уведомление
    await send_alert(
        bot,
        config.chat_id,
        f"🚀 *SSHCheck запущен*\n"
        f"📂 Мониторинг: `{config.log_file.replace('-', '\\-')}`\n"
        f"🔔 Порог алёрта: *{config.alert_threshold}* попыток/час\n"
        f"🕐 `{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC').replace('-', '\\-')}`",
    )

    logger.info("Запускаю фоновые задачи...")

    tasks = [
        asyncio.create_task(monitor(config.log_file, event_queue), name="log-monitor"),
        asyncio.create_task(
            process_events(event_queue, db, bot, config), name="event-processor"
        ),
        asyncio.create_task(app.updater.start_polling(), name="tg-polling"),
    ]

    # Периодический сводный отчёт
    if config.summary_interval > 0:
        tasks.append(
            asyncio.create_task(
                _periodic_summary(bot, config, db), name="summary-scheduler"
            )
        )

    # Graceful shutdown при SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig_name: str) -> None:
        logger.info("Получен сигнал %s, завершаю работу...", sig_name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown, sig.name)
        except NotImplementedError:
            pass  # Windows не поддерживает add_signal_handler

    await stop_event.wait()

    # Останавливаем
    logger.info("Останавливаю сервис...")
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await db.close()

    logger.info("SSHCheck остановлен.")


async def _periodic_summary(bot, config, db: Database) -> None:
    """Отправляет сводный отчёт с заданным интервалом."""
    await asyncio.sleep(config.summary_interval)  # первый отчёт через N секунд
    while True:
        try:
            await send_summary(bot, config.chat_id, db, config)
            logger.info("Плановый отчёт отправлен.")
        except Exception as e:
            logger.error("Ошибка отправки планового отчёта: %s", e)
        await asyncio.sleep(config.summary_interval)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Прервано пользователем.")


if __name__ == "__main__":
    main()
