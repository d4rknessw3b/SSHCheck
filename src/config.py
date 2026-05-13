"""
config.py — Загрузка конфигурации из config.yml
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class Config:
    bot_token: str
    chat_id: int
    log_file: str = "/var/log/auth.log"
    db_path: str = "sshcheck.db"
    alert_threshold: int = 5
    alert_cooldown: int = 600
    summary_interval: int = 3600
    geolocation: bool = True
    geo_cache_ttl: int = 86400
    whitelist_ips: List[str] = field(default_factory=list)
    auto_block: bool = False
    auto_block_threshold: int = 20


def load_config(path: str = "config.yml") -> Config:
    """Загружает и валидирует конфигурацию из YAML-файла."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Файл конфигурации '{path}' не найден. "
            "Скопируйте config.yml.example в config.yml и заполните параметры."
        )

    with open(path, encoding="utf-8") as f:
        raw: dict = yaml.safe_load(f) or {}

    required = ("bot_token", "chat_id")
    for key in required:
        if key not in raw or not raw[key]:
            raise ValueError(f"Обязательный параметр '{key}' отсутствует в {path}")

    # Нормализуем whitelist_ips
    raw.setdefault("whitelist_ips", [])

    return Config(**{k: v for k, v in raw.items() if k in Config.__dataclass_fields__})
