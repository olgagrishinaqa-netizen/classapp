#!/usr/bin/env bash
# Разовая установка ЗАПАСНОГО pull-деплоя на ВМ: sudo bash install.sh [--enable]
# Основной путь деплоя — .github/workflows/deploy.yml (push по SSH). Таймер по умолчанию
# только устанавливается, но не включается: иначе два пути гонятся за один и тот же коммит.
# Включить: sudo bash install.sh --enable   (или sudo systemctl enable --now classapp-pull-deploy.timer)
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Запустите от root: sudo bash $0"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"

install -m 755 "$HERE/pull-deploy.sh" /usr/local/bin/classapp-pull-deploy
mkdir -p /etc/classapp
if [ ! -f /etc/classapp/pull-deploy.env ]; then
  cat > /etc/classapp/pull-deploy.env <<'ENV'
# Необязательно: уведомления в Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ENV
  chmod 600 /etc/classapp/pull-deploy.env
fi

cat > /etc/systemd/system/classapp-pull-deploy.service <<'UNIT'
[Unit]
Description=classapp pull-based deploy to K3s
After=network-online.target k3s.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/classapp-pull-deploy
TimeoutStartSec=20min
UNIT

cat > /etc/systemd/system/classapp-pull-deploy.timer <<'UNIT'
[Unit]
Description=Poll for new classapp release every 2 minutes

[Timer]
OnBootSec=2min
OnUnitInactiveSec=2min
Unit=classapp-pull-deploy.service

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
if [ "${1:-}" = "--enable" ]; then
  systemctl enable --now classapp-pull-deploy.timer
  echo "Установлено и ВКЛЮЧЕНО. Логи: journalctl -u classapp-pull-deploy -f"
else
  echo "Установлено, таймер НЕ включён (основной деплой — GitHub Actions)."
  echo "Включить: sudo systemctl enable --now classapp-pull-deploy.timer"
fi
echo "Запустить вручную один раз: sudo systemctl start classapp-pull-deploy"
