#!/usr/bin/env bash
# Безопасное применение Terraform: сохраняем план, показываем итог и, если план что-то УДАЛЯЕТ или
# ПЕРЕСОЗДАЁТ (например, ВМ вместе с данными), требуем подтверждение. Применяется именно сохранённый план,
# поэтому между проверкой и применением ничего не изменится.
#
# Использование: ./safe-apply.sh <каталог terraform>      (FORCE=1 — без вопросов, например для CI)
set -euo pipefail

TF_DIR="${1:?usage: safe-apply.sh <terraform dir>}"
PLAN_FILE="$(mktemp)"
trap 'rm -f "$PLAN_FILE"' EXIT

terraform -chdir="$TF_DIR" plan -input=false -out="$PLAN_FILE" -no-color | tail -n 25

DESTRUCTIVE="$(terraform -chdir="$TF_DIR" show -json "$PLAN_FILE" \
  | jq -r '[.resource_changes[]? | select(.change.actions | index("delete")) | .address] | join(", ")')"

if [ -n "$DESTRUCTIVE" ] && [ "${FORCE:-0}" != "1" ]; then
  echo
  echo "ВНИМАНИЕ: план удаляет или пересоздаёт: ${DESTRUCTIVE}"
  echo "Данные на пересоздаваемой ВМ будут потеряны (восстановление: sudo classapp-restore apply)."
  read -r -p "Продолжить? Введите 'yes': " answer
  [ "$answer" = "yes" ] || { echo "Отменено."; exit 1; }
fi

terraform -chdir="$TF_DIR" apply -input=false "$PLAN_FILE"
