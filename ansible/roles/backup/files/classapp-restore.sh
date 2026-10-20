#!/usr/bin/env bash
# Восстановление из бэкапа в S3 (бакет задаёт /etc/classapp/backup.env, доступ — IAM-роль ВМ).
#
#   sudo classapp-restore verify [ключ]   проверка: дамп грузится во временную БД, считаем
#                                         таблицы/админов/версию миграций, БД удаляется.
#                                         Боевую БД не трогает — безопасно запускать в любой момент.
#   sudo classapp-restore apply  [ключ]   ВОССТАНОВЛЕНИЕ: web останавливается, БД classapp
#                                         пересоздаётся из дампа, загрузки и чеки распаковываются
#                                         из архива, web запускается обратно. Текущие данные теряются!
#
# [ключ] — имя файла дампа в s3://<бакет>/db/ (по умолчанию самый свежий). Архив загрузок
# берётся с тем же временным штампом, если он есть.
set -euo pipefail

source /etc/classapp/backup.env
export AWS_DEFAULT_REGION KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
UPLOADS_DIR="${UPLOADS_DIR:-/var/lib/classapp/uploads}"
MODE="${1:-}"
KEY="${2:-}"

[ "$MODE" = verify ] || [ "$MODE" = apply ] || { sed -n '2,13p' "$0"; exit 1; }

PATRONI_POD="$(kubectl get pod -n default -l patroni-role=master -o jsonpath='{.items[0].metadata.name}')"
[ -n "$PATRONI_POD" ] || { echo "мастер Patroni не найден"; exit 1; }

pg() { # pg "<аргументы psql>" — SQL читается со stdin
  kubectl exec -i -n default "$PATRONI_POD" -c patroni -- \
    sh -c "PGPASSWORD=\$PATRONI_SUPERUSER_PASSWORD psql -h 127.0.0.1 -U postgres $1"
}

if [ -z "$KEY" ]; then
  KEY="$(aws s3 ls "s3://${BACKUP_BUCKET}/db/" | sort | tail -1 | awk '{print $4}')"
fi
[ -n "$KEY" ] || { echo "в s3://${BACKUP_BUCKET}/db/ нет дампов"; exit 1; }
STAMP="${KEY#classapp-}"; STAMP="${STAMP%.sql.gz}"
echo "дамп: ${KEY}"

# Базу создаём от template0: в template1 у Spilo уже есть служебные схемы (metric_helpers и др.),
# которые лежат и в дампе, — загрузка в обычную БД падает на "already exists".
load_dump() { # load_dump <имя БД>
  echo "DROP DATABASE IF EXISTS $1" | pg "-q"
  echo "CREATE DATABASE $1 TEMPLATE template0" | pg "-q"
  aws s3 cp "s3://${BACKUP_BUCKET}/db/${KEY}" - --only-show-errors | gunzip \
    | pg "-d $1 -q -v ON_ERROR_STOP=1" >/dev/null
}

if [ "$MODE" = verify ]; then
  DB=classapp_restore_test
  trap 'echo "DROP DATABASE IF EXISTS ${DB}" | pg "-q" 2>/dev/null || true' EXIT
  load_dump "$DB"
  echo "select 'таблиц: '||count(*) from information_schema.tables where table_schema='public'" | pg "-d $DB -t -A"
  echo "select 'админов: '||count(*) from \"user\" where role='admin'" | pg "-d $DB -t -A"
  echo "select 'версия миграций: '||version_num from alembic_version" | pg "-d $DB -t -A"
  echo "OK: бэкап ${KEY} восстанавливается"
  exit 0
fi

# --- apply ---
echo "ВНИМАНИЕ: БД classapp и загрузки будут заменены содержимым бэкапа ${KEY}"
REPLICAS="$(kubectl get deployment classapp-web -n default -o jsonpath='{.spec.replicas}')"
kubectl scale deployment classapp-web -n default --replicas=0
trap 'kubectl scale deployment classapp-web -n default --replicas="${REPLICAS:-2}"' EXIT
kubectl rollout status deployment/classapp-web -n default --timeout=120s || true

echo "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='classapp' AND pid <> pg_backend_pid()" \
  | pg "-q -t -A" >/dev/null
load_dump classapp

UPLOADS_KEY="uploads-${STAMP}.tar.gz"
if aws s3 ls "s3://${BACKUP_BUCKET}/uploads/${UPLOADS_KEY}" >/dev/null 2>&1; then
  mkdir -p "$UPLOADS_DIR"
  aws s3 cp "s3://${BACKUP_BUCKET}/uploads/${UPLOADS_KEY}" - --only-show-errors \
    | tar xz -C "$UPLOADS_DIR"
  chown -R 1000:1000 "$UPLOADS_DIR"
  echo "загрузки и чеки восстановлены из ${UPLOADS_KEY}"
else
  echo "архива загрузок ${UPLOADS_KEY} нет — пропускаю"
fi
echo "готово: web запускается обратно (${REPLICAS:-2} реплики)"
