# SSHCheck 🛡️

> Мониторинг SSH-атак на Ubuntu с уведомлениями в Telegram

## Возможности

- 📡 **Мониторинг в реальном времени** — анализирует `/var/log/auth.log` и мгновенно реагирует на события
- 🔔 **Telegram-алёрты** — уведомления при превышении порога неудачных попыток
- 🟢 **Контроль успешных входов** — оповещение о каждом успешном SSH-подключении
- 🌍 **Геолокация атакующих** — определение страны, города, провайдера (ip-api.com)
- 📊 **Статистика и отчёты** — интерактивные команды бота
- 💾 **SQLite-хранилище** — все события сохраняются для последующего анализа
- 🚫 **Авто-блокировка** — опциональная блокировка IP через `ufw`
- ⚙️ **Systemd-сервис** — автозапуск и мониторинг здоровья процесса

## Структура проекта

```
SSHCheck/
├── src/
│   ├── config.py        # Загрузка конфигурации
│   ├── database.py      # Асинхронная работа с SQLite
│   ├── log_monitor.py   # Парсинг и tail auth.log
│   ├── geo.py           # Геолокация IP (кэшированная)
│   ├── processor.py     # Обработка событий, алёрты
│   ├── bot.py           # Telegram-бот, команды
│   └── main.py          # Точка входа, оркестрация
├── tests/
│   └── test_log_monitor.py
├── config.yml           # Конфигурация (заполнить!)
├── run.py               # Запуск
├── requirements.txt
├── sshcheck.service     # Systemd unit
└── install.sh           # Автоустановщик
```

## Быстрый старт

### 1. Получите Telegram Bot Token

1. Напишите [@BotFather](https://t.me/BotFather) в Telegram
2. Создайте бота: `/newbot`
3. Скопируйте токен

Узнайте свой Chat ID: напишите [@userinfobot](https://t.me/userinfobot)

### 2. Установка на Ubuntu

```bash
# Клонируйте репозиторий
git clone https://github.com/YOUR_USER/SSHCheck.git
cd SSHCheck

# Запустите автоустановщик (требует root)
sudo bash install.sh
```

### 3. Настройте конфигурацию

```bash
sudo nano /opt/sshcheck/config.yml
```

Обязательно заполните:
```yaml
bot_token: "1234567890:ABCdef..."
chat_id: 123456789
```

### 4. Запустите сервис

```bash
sudo systemctl start sshcheck
sudo systemctl status sshcheck

# Просмотр логов в реальном времени
sudo journalctl -u sshcheck -f
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и список команд |
| `/stats` | Общая статистика (всего/неудачных/успешных) |
| `/top [N]` | Топ-N атакующих IP с геолокацией |
| `/recent [N]` | Последние N событий |
| `/summary` | Подробный отчёт с анализом |
| `/status` | Текущий статус сервиса, аптайм |
| `/help` | Справка |

## Конфигурация

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `bot_token` | **обязателен** | Токен Telegram-бота |
| `chat_id` | **обязателен** | ID вашего Telegram-чата |
| `log_file` | `/var/log/auth.log` | Путь к лог-файлу SSH |
| `alert_threshold` | `5` | Попыток за час до отправки алёрта |
| `alert_cooldown` | `600` | Пауза (сек) между алёртами для одного IP |
| `summary_interval` | `3600` | Интервал автоотчётов (0 — отключить) |
| `geolocation` | `true` | Определение геолокации IP |
| `auto_block` | `false` | Автоблокировка через ufw |
| `auto_block_threshold` | `20` | Порог для автоблокировки |
| `whitelist_ips` | `[127.0.0.1]` | IP, которые не вызывают алёрты |

## Поддерживаемые события

| Событие | Значок | Описание |
|---------|--------|----------|
| `failed` | 🔴 | Неудачная попытка входа (пароль/ключ) |
| `accepted` | 🟢 | Успешный вход |
| `invalid_user` | 🟡 | Попытка входа с несуществующим пользователем |
| `disconnect` | ⚪ | Разрыв соединения |

## Ручной запуск (без systemd)

```bash
cd /opt/sshcheck
source venv/bin/activate
python run.py
```

## Тесты

```bash
pip install pytest
pytest tests/ -v
```

## Требования

- Ubuntu 20.04+
- Python 3.9+
- Доступ к `/var/log/auth.log` (root или группа `adm`)

## Лицензия

MIT
