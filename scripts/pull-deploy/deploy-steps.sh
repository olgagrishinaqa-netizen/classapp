#!/usr/bin/env bash
# Применение манифестов K3s для коммита $1. Запускается pull-deploy.sh от root на ВМ.
set -euo pipefail

COMMIT_SHA="${1:?usage: deploy-steps.sh <commit-sha>}"
IMAGE_REPO="${IMAGE_REPO:-olgagrishinaqa-netizen/classapp}"
SRC_DIR="${SRC_DIR:-/opt/classapp/repo}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
KUBE="kubectl"
K8S_IMAGE="ghcr.io/${IMAGE_REPO}:main-${COMMIT_SHA}"
K8S_DIR="$SRC_DIR/k8s"

mkdir -p /var/log/classapp /var/log/nginx
chmod 755 /var/log/classapp /var/log/nginx

echo "ШАГ 1: снятие taint с мастер-ноды"
$KUBE taint nodes --all node-role.kubernetes.io/master:NoSchedule- || true
$KUBE taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule- || true

echo "ШАГ 2: манифесты СУБД"
$KUBE apply -f "$K8S_DIR/etcd.yaml"
$KUBE apply -f "$K8S_DIR/services.yaml"
PATRONI_APPLY_ERR="$(mktemp)"
if ! $KUBE apply -f "$K8S_DIR/patroni.yaml" 2>"$PATRONI_APPLY_ERR"; then
  if grep -q "updates to statefulset spec.*are forbidden" "$PATRONI_APPLY_ERR"; then
    echo "Immutable-изменение StatefulSet: пересборка через orphan-поды"
    $KUBE scale statefulset/classapp-patroni --namespace default --replicas=0 || true
    $KUBE delete statefulset classapp-patroni --namespace default --cascade=orphan
    $KUBE apply -f "$K8S_DIR/patroni.yaml"
  else
    cat "$PATRONI_APPLY_ERR"; rm -f "$PATRONI_APPLY_ERR"; exit 1
  fi
fi
rm -f "$PATRONI_APPLY_ERR"

echo "ШАГ 3: ожидание master endpoint Patroni"
# Холодный старт на слабой ноде (загрузка образа, инициализация Postgres) занимает минуты.
for i in $(seq 1 225); do
  EP="$($KUBE get endpoints classapp-db-master -n default -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || true)"
  [ -n "$EP" ] && { echo "classapp-db-master: $EP"; break; }
  if [ "$i" -eq 225 ]; then
    echo "classapp-db-master не получил endpoint за 15 минут"
    $KUBE get pods -l app.kubernetes.io/name=patroni -n default || true
    $KUBE describe pods -l app.kubernetes.io/name=patroni -n default | tail -40 || true
    $KUBE logs classapp-patroni-0 --all-containers=true --tail=60 -n default || true
    exit 1
  fi
  [ $((i % 15)) -eq 0 ] && $KUBE get pods -l app.kubernetes.io/name=patroni -n default || true
  sleep 4
done

echo "ШАГ 4: нормализация classapp-secrets (database-url)"
b64get() { $KUBE get secret classapp-secrets -n default -o jsonpath="{.data.$1}" 2>/dev/null || true; }
DB_PASSWORD_B64="$(b64get db-password)"
SECRET_KEY_B64="$(b64get secret-key)"
ADMIN_PHONE_B64="$(b64get admin-phone)"
ADMIN_PASSWORD_B64="$(b64get admin-password)"
if [ -z "$DB_PASSWORD_B64" ] || [ -z "$SECRET_KEY_B64" ]; then
  echo "classapp-secrets должен содержать db-password и secret-key (создаётся ролью ansible bootstrap_secrets)"
  exit 1
fi
DB_PASSWORD="$(printf '%s' "$DB_PASSWORD_B64" | base64 -d)"
SECRET_KEY="$(printf '%s' "$SECRET_KEY_B64" | base64 -d)"
ENCODED_DB_PASSWORD="$(DB_PASSWORD="$DB_PASSWORD" python3 -c 'import os,urllib.parse; print(urllib.parse.quote(os.environ["DB_PASSWORD"], safe=""))')"
DATABASE_URL="postgresql://postgres:${ENCODED_DB_PASSWORD}@classapp-db-master:5432/classapp?sslmode=require"
SECRET_ARGS=(--from-literal=db-password="$DB_PASSWORD" --from-literal=secret-key="$SECRET_KEY" --from-literal=database-url="$DATABASE_URL")
[ -n "$ADMIN_PHONE_B64" ] && SECRET_ARGS+=(--from-literal=admin-phone="$(printf '%s' "$ADMIN_PHONE_B64" | base64 -d)")
[ -n "$ADMIN_PASSWORD_B64" ] && SECRET_ARGS+=(--from-literal=admin-password="$(printf '%s' "$ADMIN_PASSWORD_B64" | base64 -d)")
$KUBE create secret generic classapp-secrets -n default "${SECRET_ARGS[@]}" --dry-run=client -o yaml | $KUBE apply -f -

echo "ШАГ 5: миграции Alembic"
$KUBE delete job classapp-migrate -n default --ignore-not-found=true
sed "s#ghcr.io/${IMAGE_REPO}:latest#${K8S_IMAGE}#g" "$K8S_DIR/migrate-job.yaml" | $KUBE apply -f -
if ! $KUBE wait --for=condition=complete job/classapp-migrate -n default --timeout=600s; then
  $KUBE get pods -l job-name=classapp-migrate -n default -o wide || true
  $KUBE describe pods -l job-name=classapp-migrate -n default | tail -30 || true
  $KUBE logs job/classapp-migrate --all-containers=true -n default || true
  exit 1
fi

echo "ШАГ 6: web + nginx через kustomize"
sed -i "s#newTag:.*#newTag: main-${COMMIT_SHA}#" "$K8S_DIR/kustomization.yaml"
$KUBE apply -k "$K8S_DIR"
$KUBE set image deployment/classapp-web classapp-web="$K8S_IMAGE" -n default

echo "ШАГ 7: rollout"
if ! $KUBE rollout status deployment/classapp-web -n default --timeout=300s; then
  $KUBE get pods -l app.kubernetes.io/name=classapp-web -n default || true
  $KUBE rollout undo deployment/classapp-web -n default || true
  exit 1
fi
sleep 10
for i in $(seq 1 15); do
  curl -fsS --max-time 5 http://127.0.0.1:30080/healthz >/dev/null 2>&1 && { echo "healthz OK"; break; }
  [ "$i" -eq 15 ] && echo "healthz не ответил, но rollout завершён"
  sleep 4
done

echo "ШАГ 8: очистка"
journalctl --vacuum-time=7d >/dev/null 2>&1 || true
if k3s crictl images >/dev/null 2>&1; then
  UNREF="$(k3s crictl images -q --unreferenced || true)"
  [ -n "$UNREF" ] && k3s crictl rmi $UNREF >/dev/null 2>&1 || true
fi
