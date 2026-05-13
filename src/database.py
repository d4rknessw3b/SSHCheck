"""
database.py — Асинхронная работа с SQLite через aiosqlite.
Хранит все SSH-события и кэш геолокации.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import aiosqlite

logger = logging.getLogger(__name__)

# ─── DDL ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS ssh_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,   -- 'failed', 'accepted', 'invalid_user', 'disconnect'
    ip          TEXT    NOT NULL,
    username    TEXT,
    auth_method TEXT,               -- 'password', 'publickey', etc.
    port        INTEGER,
    raw_line    TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ip        ON ssh_events(ip);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON ssh_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type      ON ssh_events(event_type);

CREATE TABLE IF NOT EXISTS geo_cache (
    ip          TEXT PRIMARY KEY,
    country     TEXT,
    country_code TEXT,
    city        TEXT,
    org         TEXT,
    cached_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip          TEXT NOT NULL,
    alerted_at  TEXT NOT NULL
);
"""


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class SSHEvent:
    timestamp: str
    event_type: str
    ip: str
    username: Optional[str] = None
    auth_method: Optional[str] = None
    port: Optional[int] = None
    raw_line: Optional[str] = None


@dataclass
class GeoInfo:
    country: str
    country_code: str
    city: str
    org: str


# ─── Database class ──────────────────────────────────────────────────────────

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("База данных подключена: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ── Events ───────────────────────────────────────────────────────────────

    async def insert_event(self, event: SSHEvent) -> None:
        async with self._lock:
            await self._db.execute(
                """INSERT INTO ssh_events
                   (timestamp, event_type, ip, username, auth_method, port, raw_line)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.timestamp,
                    event.event_type,
                    event.ip,
                    event.username,
                    event.auth_method,
                    event.port,
                    event.raw_line,
                ),
            )
            await self._db.commit()

    async def get_failed_count(self, ip: str, since_minutes: int = 60) -> int:
        """Количество неудачных попыток с IP за последние N минут."""
        cutoff = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        async with self._db.execute(
            """SELECT COUNT(*) FROM ssh_events
               WHERE ip = ? AND event_type = 'failed'
               AND timestamp >= datetime('now', ?)""",
            (ip, f"-{since_minutes} minutes"),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_total_failed_count(self, ip: str) -> int:
        """Всего неудачных попыток с IP за всё время."""
        async with self._db.execute(
            "SELECT COUNT(*) FROM ssh_events WHERE ip=? AND event_type='failed'",
            (ip,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_recent_events(self, limit: int = 10) -> List[aiosqlite.Row]:
        async with self._db.execute(
            """SELECT * FROM ssh_events ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ) as cur:
            return await cur.fetchall()

    async def get_top_ips(self, limit: int = 10, event_type: str = "failed") -> List[Tuple[str, int]]:
        async with self._db.execute(
            """SELECT ip, COUNT(*) as cnt FROM ssh_events
               WHERE event_type=?
               GROUP BY ip ORDER BY cnt DESC LIMIT ?""",
            (event_type, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [(r["ip"], r["cnt"]) for r in rows]

    async def get_top_usernames(self, limit: int = 10) -> List[Tuple[str, int]]:
        async with self._db.execute(
            """SELECT username, COUNT(*) as cnt FROM ssh_events
               WHERE event_type='failed' AND username IS NOT NULL
               GROUP BY username ORDER BY cnt DESC LIMIT ?""",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [(r["username"], r["cnt"]) for r in rows]

    async def get_stats_summary(self) -> dict:
        """Общая сводка статистики."""
        result = {}
        queries = {
            "total_events": "SELECT COUNT(*) FROM ssh_events",
            "total_failed": "SELECT COUNT(*) FROM ssh_events WHERE event_type='failed'",
            "total_accepted": "SELECT COUNT(*) FROM ssh_events WHERE event_type='accepted'",
            "unique_ips": "SELECT COUNT(DISTINCT ip) FROM ssh_events WHERE event_type='failed'",
            "today_failed": "SELECT COUNT(*) FROM ssh_events WHERE event_type='failed' AND timestamp >= date('now')",
            "hour_failed": "SELECT COUNT(*) FROM ssh_events WHERE event_type='failed' AND timestamp >= datetime('now','-1 hour')",
        }
        for key, sql in queries.items():
            async with self._db.execute(sql) as cur:
                row = await cur.fetchone()
                result[key] = row[0] if row else 0
        return result

    # ── Geo cache ────────────────────────────────────────────────────────────

    async def get_geo(self, ip: str, ttl_seconds: int = 86400) -> Optional[GeoInfo]:
        async with self._db.execute(
            """SELECT * FROM geo_cache WHERE ip=?
               AND cached_at >= datetime('now', ?)""",
            (ip, f"-{ttl_seconds} seconds"),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return GeoInfo(
                    country=row["country"] or "Unknown",
                    country_code=row["country_code"] or "??",
                    city=row["city"] or "Unknown",
                    org=row["org"] or "Unknown",
                )
        return None

    async def save_geo(self, ip: str, geo: GeoInfo) -> None:
        async with self._lock:
            await self._db.execute(
                """INSERT OR REPLACE INTO geo_cache
                   (ip, country, country_code, city, org, cached_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                (ip, geo.country, geo.country_code, geo.city, geo.org),
            )
            await self._db.commit()

    # ── Alert log ────────────────────────────────────────────────────────────

    async def was_recently_alerted(self, ip: str, cooldown_seconds: int) -> bool:
        async with self._db.execute(
            """SELECT 1 FROM alert_log WHERE ip=?
               AND alerted_at >= datetime('now', ?)""",
            (ip, f"-{cooldown_seconds} seconds"),
        ) as cur:
            return await cur.fetchone() is not None

    async def record_alert(self, ip: str) -> None:
        async with self._lock:
            await self._db.execute(
                "INSERT INTO alert_log (ip, alerted_at) VALUES (?, datetime('now'))",
                (ip,),
            )
            await self._db.commit()
