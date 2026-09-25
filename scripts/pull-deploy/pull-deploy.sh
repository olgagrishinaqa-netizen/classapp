#!/usr/bin/env bash
# Poller: раз в пару минут (systemd timer) проверяет, есть ли свежий main с
# готовым образом в GHCR, и запускает deploy-steps.sh из репозитория.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/olgagrishinaqa-netizen/classapp.git}"
BRANCH="${BRANCH:-main}"
IMAGE_REPO="${IMAGE_REPO:-olgagrishinaqa-netizen/classapp}"
SRC_DIR="${SRC_DIR:-/opt/classapp/repo}"
STATE_DIR="${STATE_DIR:-/var/lib/classapp-deploy}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

mkdir -p "$STATE_DIR" "$(dirname "$SRC_DIR")"
exec 9>"$STATE_DIR/lock"
flock -n 9 || exit 0

# shellcheck disable=SC1091
[ -f /etc/classapp/pull-deploy.env ] && . /etc/classapp/pull-deploy.env

log() { echo "[$(date -u +%FT%TZ)] $*"; }
notify() {
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
  curl -s --max-time 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" >/dev/null || true
}

SHA="$(git ls-remote "$REPO_URL" "refs/heads/$BRANCH" | cut -f1)"
[ -n "$SHA" ] || { log "git ls-remote вернул пусто, пропускаем"; exit 0; }

[ "$SHA" = "$(cat "$STATE_DIR/deployed_sha" 2>/dev/null || true)" ] && exit 0

FAILED_FILE="$STATE_DIR/failed"
if [ -f "$FAILED_FILE" ] && [ "$(cut -d' ' -f1 "$FAILED_FILE")" = "$SHA" ] \
   && [ "$(cut -d' ' -f2 "$FAILED_FILE")" -ge "$MAX_ATTEMPTS" ]; then
  exit 0
fi

# Образ main-<sha> появляется только после успешных CI и build.
TOKEN="$(curl -fsS --max-time 15 "https://ghcr.io/token?service=ghcr.io&scope=repository:${IMAGE_REPO}:pull" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])' 2>/dev/null || true)"
if ! curl -fsSI --max-time 15 -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
  "https://ghcr.io/v2/${IMAGE_REPO}/manifests/main-${SHA}" >/dev/null 2>&1; then
  log "образ main-${SHA} ещё не опубликован, ждём"
  exit 0
fi

log "Деплой ${SHA}"
if [ ! -d "$SRC_DIR/.git" ]; then git clone --quiet "$REPO_URL" "$SRC_DIR"; fi
git -C "$SRC_DIR" fetch --quiet origin "$BRANCH"
git -C "$SRC_DIR" checkout --quiet -f "$SHA"

if IMAGE_REPO="$IMAGE_REPO" SRC_DIR="$SRC_DIR" bash "$SRC_DIR/scripts/pull-deploy/deploy-steps.sh" "$SHA"; then
  echo "$SHA" > "$STATE_DIR/deployed_sha"
  rm -f "$FAILED_FILE"
  log "Готово: ${SHA}"
  notify "✅ classapp: деплой ${SHA:0:7} успешен"
else
  COUNT=1
  [ -f "$FAILED_FILE" ] && [ "$(cut -d' ' -f1 "$FAILED_FILE")" = "$SHA" ] && COUNT=$(( $(cut -d' ' -f2 "$FAILED_FILE") + 1 ))
  echo "$SHA $COUNT" > "$FAILED_FILE"
  log "ОШИБКА деплоя ${SHA} (попытка ${COUNT}/${MAX_ATTEMPTS})"
  notify "❌ classapp: деплой ${SHA:0:7} упал (попытка ${COUNT}/${MAX_ATTEMPTS}), см. journalctl -u classapp-pull-deploy"
  exit 1
fi
