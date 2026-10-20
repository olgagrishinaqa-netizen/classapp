#!/usr/bin/env bash
# Применение манифестов K3s для коммита $1. Запускается pull-deploy.sh от root на ВМ.
#
# Образ берётся по неизменяемому дайджесту, если задан IMAGE_DIGEST (sha256:...), иначе по тегу main-<sha>.
# При любой ошибке откатываются ВСЕ компоненты, которые этот деплой успел изменить (etcd, Patroni, nginx, web);
# миграции БД автоматически не откатываются (они должны быть обратно совместимы).
set -euo pipefail

COMMIT_SHA="${1:?usage: deploy-steps.sh <commit-sha>}"
IMAGE_REPO="${IMAGE_REPO:-olgagrishinaqa-netizen/classapp}"
SRC_DIR="${SRC_DIR:-/opt/classapp/repo}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
KUBE="kubectl"
IMAGE_DIGEST="${IMAGE_DIGEST:-}"
if [ -n "$IMAGE_DIGEST" ]; then
  [[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "IMAGE_DIGEST имеет неверный формат"; exit 1; }
  K8S_IMAGE="ghcr.io/${IMAGE_REPO}@${IMAGE_DIGEST}"
else
  K8S_IMAGE="ghcr.io/${IMAGE_REPO}:main-${COMMIT_SHA}"
fi
K8S_DIR="$SRC_DIR/k8s"
STATE_DIR="${STATE_DIR:-/var/lib/classapp-deploy}"

# --- Откат: запоминаем версии компонентов ДО деплоя -------------------------------------------
# Порядок: от зависимостей к потребителям (для отката используется обратный порядок).
WORKLOADS="deployment/etcd statefulset/classapp-patroni deployment/classapp-nginx deployment/classapp-web"
declare -A REV_BEFORE

rev_of() { # номер ревизии Deployment / идентификатор ревизии StatefulSet (пусто, если объекта ещё нет)
  case "$1" in
    deployment/*) $KUBE get "$1" -n default -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}' 2>/dev/null || true ;;
    statefulset/*) $KUBE get "$1" -n default -o jsonpath='{.status.updateRevision}' 2>/dev/null || true ;;
  esac
}

for w in $WORKLOADS; do REV_BEFORE[$w]="$(rev_of "$w")"; done

rollback_changed() {
  echo "ОТКАТ: возвращаю компоненты, изменённые этим деплоем, на прежнюю версию"
  local w now before
  for w in $(printf '%s\n' $WORKLOADS | tac); do
    before="${REV_BEFORE[$w]:-}"
    now="$(rev_of "$w")"
    if [ -n "$before" ] && [ -n "$now" ] && [ "$now" != "$before" ]; then
      echo "  откат $w ($now -> $before)"
      case "$w" in
        deployment/*) $KUBE rollout undo "$w" -n default --to-revision="$before" || true ;;
        statefulset/*) $KUBE rollout undo "$w" -n default || true ;;
      esac
    fi
  done
  for w in $WORKLOADS; do $KUBE rollout status "$w" -n default --timeout=180s || true; done
}

rollout_wait() { # rollout_wait <объект> <таймаут, сек>
  if ! $KUBE rollout status "$1" -n default --timeout="${2}s"; then
    echo "$1 не стал готовым за ${2} с"
    $KUBE get pods -n default -o wide || true
    $KUBE describe "$1" -n default | tail -25 || true
    rollback_changed
    exit 1
  fi
}

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
    rollback_changed
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
  rollback_changed
  exit 1
fi

echo "ШАГ 6: web + nginx через kustomize"
if [ -n "$IMAGE_DIGEST" ]; then
  sed -i "s#newTag:.*#digest: ${IMAGE_DIGEST}#" "$K8S_DIR/kustomization.yaml"
else
  sed -i "s#newTag:.*#newTag: main-${COMMIT_SHA}#" "$K8S_DIR/kustomization.yaml"
fi
$KUBE apply -k "$K8S_DIR"
$KUBE set image deployment/classapp-web classapp-web="$K8S_IMAGE" -n default

echo "ШАГ 7: rollout всех компонентов и проверка работоспособности"
rollout_wait deployment/etcd 180
rollout_wait statefulset/classapp-patroni 600
rollout_wait deployment/classapp-nginx 180
rollout_wait deployment/classapp-web 300
sleep 10
HEALTHY=0
for i in $(seq 1 15); do
  if curl -fsS --max-time 5 http://127.0.0.1:30080/healthz | grep -q '"database":"ok"' \
     && [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:30080/login)" = "200" ]; then
    HEALTHY=1; echo "healthz и страница входа OK"; break
  fi
  sleep 4
done
if [ "$HEALTHY" -ne 1 ]; then
  echo "приложение не прошло проверку работоспособности после раскатки"
  rollback_changed
  exit 1
fi

# Запоминаем, что именно выкачено (по этому файлу workflow пропускает повторный деплой того же коммита).
mkdir -p "$STATE_DIR"
echo "$COMMIT_SHA" > "$STATE_DIR/deployed_sha"
echo "$K8S_IMAGE" > "$STATE_DIR/deployed_image"

echo "ШАГ 8: аннотация деплоя в Grafana (необязательный шаг, ошибки не критичны)"
# Вертикальная метка «деплой» на графиках дашбордов. Пароль берётся из секрета
# classapp-grafana, Grafana доступна на ноде по NodePort 30300.
(
  set +e
  GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:30300}"
  GF_USER="$($KUBE get secret classapp-grafana -n monitoring -o jsonpath='{.data.admin-user}' 2>/dev/null | base64 -d)"
  GF_PASS="$($KUBE get secret classapp-grafana -n monitoring -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d)"
  if [ -z "$GF_USER" ] || [ -z "$GF_PASS" ]; then
    echo "секрет classapp-grafana не найден, аннотацию пропускаем"
    exit 0
  fi
  PAYLOAD="$(COMMIT_SHA="$COMMIT_SHA" python3 -c 'import json,os; sha=os.environ["COMMIT_SHA"]; print(json.dumps({"text": "Деплой classapp " + sha[:7], "tags": ["deploy", "classapp"]}))')"
  HTTP_CODE="$(curl -sS --max-time 10 -o /tmp/grafana-annotation.out -w '%{http_code}' \
      -u "${GF_USER}:${GF_PASS}" -H 'Content-Type: application/json' \
      -d "$PAYLOAD" "${GRAFANA_URL}/api/annotations" 2>/tmp/grafana-annotation.err)"
  case "$HTTP_CODE" in
    200) echo "аннотация деплоя ${COMMIT_SHA:0:7} добавлена" ;;
    000) echo "Grafana не отвечает на ${GRAFANA_URL}: $(head -c 200 /tmp/grafana-annotation.err)" ;;
    *)   echo "Grafana вернула HTTP ${HTTP_CODE}: $(head -c 200 /tmp/grafana-annotation.out)" ;;
  esac
  $KUBE get pods -n monitoring -l app.kubernetes.io/name=grafana --no-headers 2>/dev/null | sed 's/^/    /'
) || true

echo "ШАГ 9: очистка"
journalctl --vacuum-time=7d >/dev/null 2>&1 || true
if k3s crictl images >/dev/null 2>&1; then
  # --prune удаляет образы, которые не использует ни один контейнер.
  if PRUNE_OUT="$(k3s crictl rmi --prune 2>&1)"; then
    echo "очистка неиспользуемых образов выполнена"
  else
    echo "crictl rmi --prune не удалась (пропускаем): $(printf '%s' "$PRUNE_OUT" | tail -n 2)"
  fi
fi
