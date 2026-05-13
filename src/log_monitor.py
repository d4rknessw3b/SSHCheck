"""
log_monitor.py — Мониторинг /var/log/auth.log в реальном времени.
Парсит строки и создаёт SSHEvent-объекты.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import AsyncGenerator, Optional

from .database import SSHEvent

logger = logging.getLogger(__name__)

# ─── Regex-паттерны ──────────────────────────────────────────────────────────

# Failed password for [invalid user] <user> from <ip> port <port> ssh2
RE_FAILED = re.compile(
    r"Failed (\w+) for (?:invalid user )?(\S+) from ([\d.]+) port (\d+)"
)

# Accepted password/publickey for <user> from <ip> port <port>
RE_ACCEPTED = re.compile(
    r"Accepted (\w+) for (\S+) from ([\d.]+) port (\d+)"
)

# Invalid user <user> from <ip> port <port>
RE_INVALID_USER = re.compile(
    r"Invalid user (\S+) from ([\d.]+)(?: port (\d+))?"
)

# Connection closed/reset by (authenticating user|invalid user) <user> <ip> port <port>
RE_DISCONNECT = re.compile(
    r"(?:Disconnected from|Connection (?:closed|reset) by)(?: (?:authenticating user|invalid user))? (\S+) ([\d.]+) port (\d+)"
)

# Maximum authentication attempts exceeded for ...
RE_MAX_AUTH = re.compile(
    r"error: maximum authentication attempts exceeded for (?:invalid user )?(\S+) from ([\d.]+) port (\d+)"
)

# Общий паттерн для извлечения IP из любой строки sshd
RE_ANY_SSH_IP = re.compile(r"from ([\d.]+)")


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def parse_line(line: str) -> Optional[SSHEvent]:
    """
    Разбирает строку из auth.log и возвращает SSHEvent или None.
    Обрабатывает только строки, связанные с sshd.
    """
    if "sshd" not in line:
        return None

    # Failed attempt
    m = RE_FAILED.search(line)
    if m:
        method, user, ip, port = m.groups()
        return SSHEvent(
            timestamp=_now_iso(),
            event_type="failed",
            ip=ip,
            username=user,
            auth_method=method,
            port=int(port),
            raw_line=line.strip(),
        )

    # Accepted
    m = RE_ACCEPTED.search(line)
    if m:
        method, user, ip, port = m.groups()
        return SSHEvent(
            timestamp=_now_iso(),
            event_type="accepted",
            ip=ip,
            username=user,
            auth_method=method,
            port=int(port),
            raw_line=line.strip(),
        )

    # Invalid user (port may be absent in older sshd versions)
    m = RE_INVALID_USER.search(line)
    if m:
        user, ip, port = m.groups()
        return SSHEvent(
            timestamp=_now_iso(),
            event_type="invalid_user",
            ip=ip,
            username=user,
            port=int(port) if port else None,
            raw_line=line.strip(),
        )

    # Max auth exceeded
    m = RE_MAX_AUTH.search(line)
    if m:
        user, ip, port = m.groups()
        return SSHEvent(
            timestamp=_now_iso(),
            event_type="failed",
            ip=ip,
            username=user,
            port=int(port),
            raw_line=line.strip(),
        )

    # Disconnect
    m = RE_DISCONNECT.search(line)
    if m:
        user, ip, port = m.groups()
        return SSHEvent(
            timestamp=_now_iso(),
            event_type="disconnect",
            ip=ip,
            username=user if user not in ("authenticating", "invalid") else None,
            port=int(port),
            raw_line=line.strip(),
        )

    return None


async def tail_log(path: str, poll_interval: float = 0.5) -> AsyncGenerator[str, None]:
    """
    Асинхронный генератор, читающий новые строки из файла (аналог `tail -f`).
    Обрабатывает ротацию лога (logrotate).
    """
    logger.info("Начинаю мониторинг лога: %s", path)
    last_inode = None
    last_pos = 0

    # Переходим в конец файла при старте (не обрабатываем историю)
    if os.path.exists(path):
        with open(path, "rb") as f:
            f.seek(0, 2)  # EOF
            last_pos = f.tell()
        last_inode = os.stat(path).st_ino

    while True:
        await asyncio.sleep(poll_interval)

        if not os.path.exists(path):
            logger.warning("Лог-файл не найден: %s. Жду...", path)
            continue

        current_inode = os.stat(path).st_ino

        # Обнаружена ротация лога
        if last_inode is not None and current_inode != last_inode:
            logger.info("Обнаружена ротация лога, сбрасываю позицию.")
            last_pos = 0

        last_inode = current_inode

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                chunk = f.read()
                if chunk:
                    for line in chunk.splitlines():
                        if line.strip():
                            yield line
                    last_pos = f.tell()
        except OSError as e:
            logger.error("Ошибка чтения лога: %s", e)


async def monitor(log_path: str, event_queue: asyncio.Queue) -> None:
    """Основной цикл мониторинга. Кладёт события в очередь."""
    async for line in tail_log(log_path):
        event = parse_line(line)
        if event:
            logger.debug("Событие: %s %s %s", event.event_type, event.ip, event.username)
            await event_queue.put(event)
