#!/bin/bash
# ============================================================
# SSHCheck — Installation Script for Ubuntu
# ============================================================
# Usage: sudo bash install.sh
# ============================================================

set -e

INSTALL_DIR="/opt/sshcheck"
SERVICE_NAME="sshcheck"
PYTHON_MIN="3.9"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warning() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── Проверки ────────────────────────────────────────────────────────────────

[ "$(id -u)" -eq 0 ] || error "Запустите скрипт с правами root: sudo bash install.sh"

command -v python3 &>/dev/null || error "Python3 не найден. Установите: sudo apt install python3 python3-pip python3-venv"

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python версии: $PY_VER"

# ─── Установка ───────────────────────────────────────────────────────────────

info "Создаю директорию $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

info "Копирую файлы проекта..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/run.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Конфигурация
if [ ! -f "$INSTALL_DIR/config.yml" ]; then
    cp "$SCRIPT_DIR/config.yml" "$INSTALL_DIR/config.yml"
    warning "Скопирован config.yml. ОБЯЗАТЕЛЬНО заполните bot_token и chat_id!"
else
    info "config.yml уже существует, пропускаю."
fi

info "Создаю виртуальное окружение..."
python3 -m venv "$INSTALL_DIR/venv"

info "Устанавливаю зависимости..."
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

success "Зависимости установлены."

# ─── Права на чтение auth.log ────────────────────────────────────────────────

LOG_FILE="/var/log/auth.log"
if [ -f "$LOG_FILE" ]; then
    chmod o+r "$LOG_FILE" || warning "Не удалось выдать права на чтение $LOG_FILE. Запускайте от root."
    success "Права на $LOG_FILE настроены."
else
    warning "$LOG_FILE не найден. На вашей системе возможно используется journald."
    warning "В таком случае замените log_file в config.yml."
fi

# ─── Systemd сервис ──────────────────────────────────────────────────────────

info "Устанавливаю systemd сервис..."
cp "$SCRIPT_DIR/sshcheck.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

success "Сервис установлен."

# ─── Итог ────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  SSHCheck успешно установлен!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "Следующие шаги:"
echo ""
echo -e "  1. Заполните конфигурацию:"
echo -e "     ${YELLOW}nano $INSTALL_DIR/config.yml${NC}"
echo ""
echo -e "  2. Запустите сервис:"
echo -e "     ${YELLOW}sudo systemctl start $SERVICE_NAME${NC}"
echo ""
echo -e "  3. Проверьте статус:"
echo -e "     ${YELLOW}sudo systemctl status $SERVICE_NAME${NC}"
echo ""
echo -e "  4. Просмотр логов:"
echo -e "     ${YELLOW}sudo journalctl -u $SERVICE_NAME -f${NC}"
echo ""
echo "Удачи! Ваш сервер теперь под защитой 🛡"
