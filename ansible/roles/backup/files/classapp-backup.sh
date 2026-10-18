#!/usr/bin/env bash
# Ночной бэкап: pg_dump из мастера Patroni + архив загрузок -> S3.
# Бакет задаётся в /etc/classapp/backup.env (BACKUP_BUCKET), доступ — через IAM-роль ВМ.
set -euo pipefail

source /etc/classapp/backup.env
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
UPLOADS_DIR="${UPLOADS_DIR:-/var/lib/classapp/uploads}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

POD="$(kubectl get pod -n default -l patroni-role=master -o jsonpath='{.items[0].metadata.name}')"
[ -n "$POD" ] || { echo "мастер Patroni не найден"; exit 1; }

kubectl exec -n default "$POD" -c patroni -- \
  sh -c 'PGPASSWORD="$PGPASSWORD_SUPERUSER" pg_dump -h 127.0.0.1 -U postgres classapp' \
  | gzip > "$TMP/db.sql.gz"
# защита от пустого дампа (pg_dump упал, а gzip отдал пустой поток)
[ "$(gzip -dc "$TMP/db.sql.gz" | wc -c)" -gt 1000 ] || { echo "дамп подозрительно мал"; exit 1; }

aws s3 cp "$TMP/db.sql.gz" "s3://${BACKUP_BUCKET}/db/classapp-${TS}.sql.gz" --only-show-errors

if [ -d "$UPLOADS_DIR" ]; then
  tar czf "$TMP/uploads.tar.gz" -C "$UPLOADS_DIR" .
  aws s3 cp "$TMP/uploads.tar.gz" "s3://${BACKUP_BUCKET}/uploads/uploads-${TS}.tar.gz" --only-show-errors
fi

echo "бэкап ${TS} загружен в s3://${BACKUP_BUCKET}"
