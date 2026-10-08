# Инфраструктура classapp: что и зачем (шпаргалка к защите)

Читать в таком порядке: сначала «Общая картина», потом файлы по слоям. В конце — слабые места, про которые могут спросить, и честные ответы.

---

## 0. Общая картина (выучить наизусть)

Путь кода до пользователя:

```
git push в main
  → CI (.github/workflows/ci.yml): линтеры, тесты pytest, пробная сборка образа
  → Build (build.yml): сборка Docker-образа, пуш в GHCR с тегом main-<sha>
  → Deploy (deploy.yml, SSH)  ИЛИ  pull-deploy (systemd-таймер на ВМ)
  → scripts/pull-deploy/deploy-steps.sh на ВМ: применяет k8s-манифесты
  → K3s на ВМ в Yandex Cloud: nginx → web (Flask+gunicorn) → Patroni/Postgres
  → Prometheus + Grafana смотрят на метрики
```

Как появилась сама ВМ:

```
Terraform (terraform/)  → создаёт сеть, firewall, статический IP, ВМ в Yandex Cloud
generate_inventory.sh   → из вывода Terraform делает inventory для Ansible
Ansible (ansible/)      → ставит пакеты, K3s, создаёт секреты, ставит мониторинг
```

**Одна фраза про подход:** Infrastructure as Code — вся инфраструктура описана файлами в git, поднимается с нуля командами, воспроизводима. Не «накликано руками в консоли».

**Почему именно такой стек:**
- **Terraform** — декларативно описывает облачные ресурсы, `plan` показывает, что изменится до применения.
- **Ansible** — настраивает уже существующую ВМ (пакеты, K3s). Идемпотентный: повторный запуск не ломает.
- **K3s** — облегчённый Kubernetes в одном бинарнике. Полный k8s не влезет в ВМ 2 vCPU/4 ГБ.
- **Docker** — одинаковое окружение на ноутбуке, в CI и в проде.
- **GHCR** — реестр образов рядом с кодом, авторизация встроенным `GITHUB_TOKEN`.
- **Patroni + etcd** — автоматический failover PostgreSQL (высокая доступность БД).
- **Prometheus/Grafana/Loki** — метрики и логи.

---

## 1. Контейнеризация

### Dockerfile
**Что:** база `python:3.11-slim`; создаётся непривилегированный пользователь `appuser`; ставятся зависимости (`pip install --no-cache-dir`); копируется код; запуск через `entrypoint.sh`; по умолчанию `gunicorn -w 4` на порту 8000.
**Зачем:**
- `slim` — меньше образ и поверхность атаки.
- `appuser` — приложение не работает от root (если взломают, ущерб меньше).
- `requirements.txt` копируется ДО остального кода — слой с зависимостями кэшируется, пересборка при смене кода быстрая.
- `PYTHONUNBUFFERED=1` — логи сразу попадают в stdout; `PYTHONDONTWRITEBYTECODE=1` — не мусорим `.pyc`.
- `/tmp/prometheus_multiproc` — каталог для метрик нескольких воркеров (см. gunicorn.conf.py).
- `FLASK_CONFIG=config.ProdConfig` — по умолчанию образ работает в боевом режиме.

**Вопрос:** «Почему gunicorn, а не `flask run`?» — встроенный сервер Flask для разработки, не держит нагрузку и небезопасен. Gunicorn — production WSGI-сервер с несколькими воркерами.

### entrypoint.sh
**Что:** (1) проверяет, что заданы `SECRET_KEY` и `DB_PASSWORD` (иначе падает сразу); (2) если нет `DATABASE_URL`, собирает его из `POSTGRES_*`, пароль URL-кодируется (`quote`), чтобы спецсимволы не ломали строку; (3) ждёт готовности БД: до 30 попыток с паузой 2 с; (4) `exec "$@"` запускает основную команду.
**Зачем:** fail fast — лучше упасть сразу с понятной ошибкой, чем работать с кривой конфигурацией. Ожидание БД нужно, потому что приложение и БД стартуют одновременно. `exec` — gunicorn становится PID 1 и корректно получает сигналы остановки (graceful shutdown).

### gunicorn.conf.py
**Что:** хуки `on_starting` (чистит каталог метрик) и `child_exit` (убирает метрики умершего воркера).
**Зачем:** gunicorn запускает несколько процессов, у каждого свои счётчики. Без multiprocess-режима Prometheus при каждом запросе видел бы метрики случайного воркера, и счётчики «прыгали» бы. Воркеры пишут в файлы в `PROMETHEUS_MULTIPROC_DIR`, `/metrics` их агрегирует.

### nginx.conf (для docker-compose)
**Что:** reverse proxy на `web:8000`; JSON-формат access-лога; `client_max_body_size 20m`; `keepalive 32` к апстриму; пробрасывает заголовки `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`; отдельные location для `/static/`, `/healthz`, `/`.
**Зачем:** nginx принимает соединения клиентов (в том числе медленных) и освобождает воркеры gunicorn; в будущем на нём удобно делать TLS. JSON-лог читается Promtail → Loki без парсинга регулярками. `X-Forwarded-*` нужны, чтобы приложение знало реальный IP клиента (он используется в журнале входов и аудите).
**Вопрос:** «Почему 20m?» — загрузка изображений новостей и чеков.

### docker-compose.dev.yml
**Что:** Postgres 15 на порту 5433 + web с кодом, смонтированным как volume и `flask run --debug`.
**Зачем:** локальная разработка с автоперезагрузкой. Пароли `postgres/postgres` — только для локального окружения, наружу не торчит.

### docker-compose.prod.yml
**Что:** db (Postgres 15), web (образ из GHCR), nginx, prometheus. Общая сеть `app-network`, volumes для данных, `restart: unless-stopped`, healthcheck'и, лимиты размера json-логов (50 МБ × 5–10 файлов).
**Зачем:** простой вариант запуска без Kubernetes (запасной/исторический). `depends_on: condition: service_healthy` — nginx не стартует раньше здорового web, web — раньше здоровой БД. `${DB_PASSWORD:?...}` — compose откажется стартовать без пароля. Ротация логов нужна, чтобы диск не забился.
**Важно знать:** в K8s-проде используется `k8s/`, а не этот файл.

### docker-compose.logging.yml + promtail-config.yml + provisioning/
**Что:** Loki (хранилище логов), Promtail (агент, читает файлы логов и шлёт в Loki), Grafana (визуализация). `provisioning/datasources/loki.yml` подключает Loki как источник данных автоматически; `provisioning/dashboards*` подгружает три дашборда (`overview`, `dashboard`, `audit`).
**Как работает Promtail:** читает `app.json.log` (Flask) и `access.json.log` (nginx), парсит JSON, делает метки `level`, `event`, `status`, `method`. Для аудит-событий (`event` не пустой) сохраняется полный JSON, чтобы в Loki были `ip` и `user_id`.
**Зачем метки только низкокардинальные:** в Loki метки — это индекс. Если сделать меткой `request_uri` или `ip` (тысячи значений), индекс раздуется и всё замедлится. Остальные поля достаются запросом через `| json`.
**Зачем provisioning:** дашборды как код — Grafana поднимается сразу настроенной, не нужно ничего настраивать руками.
**Вопрос:** «Метрики и логи — в чём разница?» — метрики это числа во времени (сколько запросов, какая задержка), дёшево и хорошо для алертов; логи это события с деталями (кто, откуда, что), нужны для расследований.

---

## 2. CI/CD (.github/workflows/)

### ci.yml
Запускается на push и PR в main. `concurrency` с `cancel-in-progress` отменяет устаревшие прогоны.
- **lint:** pre-commit (black, isort, flake8, bandit и др.) с кэшем хуков. Шаг заканчивается `|| true`, то есть **не блокирует** пайплайн (см. «слабые места»).
- **test:** pytest на SQLite (`TEST_DATABASE_URL=sqlite:///...`) с покрытием; отчёты junit/coverage выкладываются артефактом на 14 дней. Зависит от lint (`needs`).
- **build-check:** сборка образа БЕЗ пуша — проверяем, что Dockerfile не сломан. Кэш слоёв в GitHub Actions cache (`type=gha`).
- **notify:** уведомление в Telegram об итоге (`if: always()`).
- `permissions: contents: read` — принцип наименьших привилегий для токена.

### build.yml
Запускается по завершении CI (`workflow_run`), только если CI успешен и ветка main (или вручную). Это гарантирует: **в реестр попадают только проверенные коммиты**.
- Тег образа: `<ветка>-<полный sha коммита>` (например `main-3f2a…`). Иммутабельный тег = точная версия, можно откатиться на любой коммит. `latest` добавляется только для main и без пересборки (`imagetools create` — просто второй тег на тот же манифест).
- Имя владельца приводится к нижнему регистру — Docker не принимает заглавные в имени образа.
- `packages: write` — единственное повышенное право, нужное для пуша в GHCR.

### deploy.yml
Запускается после успешного Build на main. Подключается по SSH к ВМ, загружает `k8s/` и `scripts/pull-deploy/` (tar через ssh), запускает `deploy-steps.sh` с SHA коммита.
Особенности (появились из-за нестабильного канала GitHub-раннеры → Yandex Cloud): уменьшение MTU до 1400, одно мультиплексируемое SSH-соединение (`ControlMaster`), `IPQoS none`, повторы на каждом шаге, диагностический probe портов, ожидание SSH до 10 минут.
Секреты: `SSH_HOST`, `SSH_KEY`, опционально `SSH_PORT`, `TELEGRAM_*`.
**Принцип:** логика деплоя вынесена в `deploy-steps.sh` и общая у SSH- и pull-вариантов — один источник правды.

### .pre-commit-config.yaml
Хуки перед коммитом: пробелы/конец файла/большие файлы/маркеры конфликта; black (формат), isort (импорты), flake8 (стиль/ошибки), bandit (уязвимости в Python-коде). Исключены alembic и venv.
**Зачем:** ловить проблемы до CI. bandit — это SAST (статический анализ безопасности).

---

## 3. Terraform (terraform/)

### main.tf
- **provider yandex** (версия зафиксирована `~> 0.136.0` из-за таймаутов), `max_retries = 10`.
- **yandex_vpc_network + subnet:** своя сеть и подсети (по одной на зону: a, b, d; зона c в Yandex была DOWN).
- **Security group `k3s`** — виртуальный firewall: SSH (22) из `allowed_ssh_cidrs`; снаружи открыты **только 80 и 443** (единая точка входа — nginx; NodePort'ы 30080/30300/30900 доступны лишь изнутри ВМ); любой трафик внутри подсетей (нужен для связи нод K3s); исходящий — всё разрешено.
- **ОС:** Ubuntu 22.04 LTS (по семейству образов `data.yandex_compute_image`).
- **yandex_vpc_address master1:** зарезервированный статический внешний IP — не меняется при остановке/перезапуске ВМ (важно для preemptible, которую платформа может остановить).
- **yandex_compute_instance.k3s с `for_each`:** ноды описаны картой `master-N` / `worker-N`, ВМ создаётся по списку зон. Один код — и одна нода, и HA-кластер.
- `metadata.ssh-keys` — публичный ключ для пользователя `ubuntu`.

### variables.tf — два режима
- **Дешёвый (по умолчанию):** 1 нода, preemptible, HDD, 2 vCPU, 50% гарантированной доли, 4 ГБ.
- **Демо (`terraform.tfvars.demo.example`):** 2 мастера + 1 воркер, без preemptible — для показа отказоустойчивости на защите.
- `yc_token` помечен `sensitive`; `tfvars` с секретами в `.gitignore`.
- `preemptible` дешевле, но платформа может остановить ВМ (максимум 24 ч работы). Это осознанный компромисс по стоимости.

### outputs.tf
Выводит IDs, публичные/приватные IP нод, статический IP master-1. Нужны для inventory Ansible и для настройки `SSH_HOST`.

### generate_inventory.sh
Берёт `terraform output -json k3s_nodes`, через `jq` генерирует `ansible/inventory/hosts.ini` с группами `k3s_master`, `k3s_worker`. Ключ SSH определяет автоматически (ed25519 → rsa). **Зачем:** руками IP не переписывать, нет рассинхрона между Terraform и Ansible.

### .terraform.lock.hcl
Фиксирует точные версии/хэши провайдеров — воспроизводимость.

**Вопросы:** «Что такое state?» — файл, где Terraform запоминает, какие реальные ресурсы соответствуют коду. «Что делает plan/apply?» — plan показывает разницу, apply применяет. «Почему не конфигурировать Ansible'ом ВМ целиком?» — разделение ответственности: Terraform создаёт ресурсы, Ansible настраивает ОС.

---

## 4. Ansible (ansible/)

### ansible.cfg
`pipelining`, `retries`, увеличенный `timeout`, и главное — **ControlMaster/ControlPersist**: одно SSH-соединение на весь прогон вместо новой сессии на каждую задачу. Иначе sshd упирается в `MaxStartups` и рвёт соединения.

### playbook.yml — два play
1. На всех нодах: ждёт SSH (`wait_for_connection`), собирает факты, роли `common` → `k3s`.
2. Только на первом мастере: роли `bootstrap_secrets` → `monitoring`.
`gather_facts: false` + отдельный `setup` после ожидания SSH — потому что сразу после создания ВМ SSH ещё не готов.

### group_vars/all.yml
Версия K3s зафиксирована (`v1.30.8+k3s1`), порт API, namespace мониторинга, зеркало реестра `docker.io → cr.yandex` (стабильнее тянуть образы), админский телефон. `k3s_token` в открытом виде не хранится — берётся из `vault.yml` (ansible-vault, в `.gitignore`; шаблон в `vault.yml.example`).

### roles/common
Базовые пакеты (curl, git, jq, python3…) и Python-библиотека `kubernetes` — она нужна модулям `kubernetes.core`, которые выполняются на самой ВМ. kubectl отдельно не качается: его симлинк создаёт установщик K3s (меньше внешних загрузок = меньше точек отказа).

### roles/k3s
Пишет `registries.yaml` (зеркала); ставит K3s через официальный скрипт get.k3s.io с зафиксированной версией:
- первый мастер — `server` (инициирует кластер),
- дополнительные мастера — `server` + `K3S_URL`,
- воркеры — `agent`.
`--disable traefik` — стандартный ingress не нужен, нашу точку входа делает свой nginx. `creates: /usr/local/bin/k3s` делает задачу идемпотентной. Повторы `retries/until` — сеть нестабильна. После изменения registries — перезапуск k3s. В конце ждёт порт 6443 (API).

### roles/bootstrap_secrets
Создаёт Secret `classapp-secrets` (пароль БД, SECRET_KEY, админ-логин/пароль, DATABASE_URL) со **случайно сгенерированными** значениями — **только если секрета ещё нет**. Иначе при каждом прогоне менялся бы пароль в Secret, а в уже инициализированной Postgres он остался бы прежним, и приложение перестало бы подключаться. Пароли выводятся один раз при создании. Аналогично `classapp-grafana`.
**Зачем:** секреты не лежат в git, генерируются на месте.

### roles/monitoring
Устанавливает `kube-prometheus-stack` через **HelmChart CRD** встроенного Helm-контроллера K3s (не нужен отдельный helm), values — через `HelmChartConfig`. Затем ждёт, пока появится CRD `ServiceMonitor` (чарт ставится асинхронно), и применяет `classapp-monitoring.yaml`.

### monitoring/files/values.yaml
Облегчённый профиль под слабую ноду: отключены Alertmanager и стандартные правила, не нужные в K3s цели (etcd/scheduler/controller-manager/proxy — внутри одного процесса k3s); лимиты CPU/RAM у Prometheus/Grafana/exporter'ов; `scrapeInterval: 60s`; хранение 2 дня / 2 ГБ; NodePort 30300 (Grafana) и 30900 (Prometheus) — только для доступа изнутри ВМ. Grafana наружу публикуется через nginx по пути `/grafana/` (`root_url` + `serve_from_sub_path`), Prometheus не публикуется (нет авторизации) — доступ через SSH-туннель. Мягкие пробы Grafana — после перезагрузки preemptible-ВМ она стартует долго и дефолтные пробы убивали её в цикле.

### monitoring/files/classapp-monitoring.yaml
- `ServiceMonitor classapp-web` — Prometheus скрейпит `/metrics` приложения каждые 15 с;
- `ServiceMonitor classapp-patroni` — метрики Patroni;
- ConfigMap с дашбордом «Classapp overview» (метка `grafana_dashboard: "1"` — sidecar Grafana подхватывает автоматически): RPS, 5xx, число подов, CPU ноды, входы success/failure, действия пользователей, p95, регистрации. Включена аннотация «Деплои» (вертикальные метки на графиках).

---

## 5. Kubernetes (k8s/)

`kustomization.yaml` собирает всё в один `kubectl apply -k k8s/`; `images.newTag` переписывается при деплое на `main-<sha>`. Откат: `kubectl rollout undo deployment/classapp-web`.

### etcd.yaml
Один под etcd + Service `etcd-service:2379`. Это **DCS** (Distributed Configuration Store) для Patroni — хранит информацию, кто лидер БД. `strategy: Recreate` — два etcd с одним именем рядом нельзя. `ETCD_ENABLE_V2=true` — Patroni (Spilo) использует v2 API.

### patroni.yaml
- **ServiceAccount + Role + RoleBinding:** Patroni обновляет pods/endpoints/services через API Kubernetes → нужны права (минимальные, в пределах namespace).
- **Headless Service** (`clusterIP: None`) — стабильные DNS-имена подов StatefulSet.
- **StatefulSet, 2 реплики** (лидер + реплика). StatefulSet, а не Deployment: у каждого пода постоянная идентичность и свой диск.
- **volumeClaimTemplates 10 Gi** — у каждой реплики свой PVC → данные переживают пересоздание пода.
- **initContainer** `fix-data-dir-perms` — выдаёт каталогу прав пользователя postgres (uid 101).
- Образ **Zalando Spilo** (Postgres + Patroni в одном). Настраивается переменными `SCOPE`, `ETCD_HOSTS`, `PGDATA` (важно: PGDATA должен лежать на смонтированном томе, иначе данные теряются).
- **Пробы:** readiness `/health`, liveness `/liveness` на порту Patroni API 8008; большие `initialDelay` — инициализация БД на слабой ВМ долгая.
- **Sidecar `role-labeler`:** каждые 10 с спрашивает у Patroni роль пода и ставит метку `patroni-role=master|replica`. Нужно, чтобы Service находил текущего лидера.

### services.yaml
`classapp-db-master` (selector `patroni-role: master`) и `classapp-db-replica`. **Ключ failover:** приложение всегда ходит на `classapp-db-master`; когда Patroni выбирает нового лидера, role-labeler переставляет метку, и Service сам начинает вести на нового лидера. Приложению ничего менять не нужно.

### migrate-job.yaml
Job, запускающий `alembic upgrade head`. initContainer ждёт `pg_isready` и создаёт БД `classapp`, если её нет (Spilo сам её не создаёт). `backoffLimit: 4`, `ttlSecondsAfterFinished: 3600`. **Зачем отдельный Job:** миграции выполняются один раз, а не в каждом из 3 подов web (иначе гонка).

### classapp-web.yaml
- Deployment, 3 реплики, gunicorn с 2 воркерами.
- Конфигурация и секреты — из Secret `classapp-secrets` (`secretKeyRef`), не из образа.
- **resources** requests/limits — планировщик знает, сколько нужно; один под не съест всю ноду.
- **readinessProbe/livenessProbe** на `/healthz`: readiness — «готов принимать трафик» (иначе под выводят из Service), liveness — «жив» (иначе перезапускают).
- initContainer `fix-log-dir-perms` — права на логи/загрузки для uid 1000.
- hostPath-тома: логи `/var/log/classapp` (их читает Promtail) и загрузки `/var/lib/classapp/uploads` (чтобы файлы переживали перезапуск пода).
- Service `classapp-web-service` (ClusterIP :8000) — внутренняя точка входа.
- **Откат при плохом деплое:** новые поды не станут Ready → rolling update останавливается, старые продолжают работать.

### classapp-nginx.yaml
ConfigMap с `nginx.conf` + Deployment (1 реплика) + Service NodePort 30080. Под занимает **hostPort 80** хоста — сайт открывается без указания порта. Реплика одна, потому что на одном хосте порт 80 может занять только один под.
**Единая точка входа (reverse proxy):** nginx — единственный вход снаружи и маршрутизирует по пути: `/` → `classapp-web-service:8000` (приложение), `/grafana/` → Grafana в namespace `monitoring`. Адрес Grafana задан через переменную и `resolver` CoreDNS (10.43.0.10) — nginx стартует, даже если мониторинг ещё не поднят. Зачем один вход: меньше открытых портов — меньше поверхность атаки; один адрес для пользователя; TLS потом настраивается в одном месте; сервисы можно переносить без смены внешних адресов.

### hpa.yaml
HorizontalPodAutoscaler: от 2 до 5 реплик web, цель — средняя загрузка CPU 70%. Нужен metrics-server (встроен в K3s). Работает потому, что у подов заданы `requests.cpu` (процент считается от них).

---

## 6. Скрипты деплоя (scripts/pull-deploy/)

### deploy-steps.sh (9 шагов, запускается на ВМ от root)
1. Снять taint с мастера — на единственной ноде должны работать и рабочие поды.
2. Применить etcd, services, patroni; если StatefulSet выдаёт ошибку «immutable spec» — пересоздать его с `--cascade=orphan` (поды и данные остаются).
3. Ждать endpoint `classapp-db-master` до 15 минут (холодный старт на слабой ВМ долгий).
4. Нормализовать `classapp-secrets`: пересобрать `database-url` из пароля (с URL-кодированием, `sslmode=require`).
5. Запустить миграции: удалить старый Job, применить новый с образом этого коммита, ждать до 10 минут, при ошибке вывести логи.
6. `kubectl apply -k` (web + nginx) и `set image` на конкретный тег.
7. `rollout status`; при провале — автоматический `rollout undo`. Затем проверка `healthz`.
8. Аннотация деплоя в Grafana (необязательный шаг, ошибки не критичны).
9. Очистка: `journalctl --vacuum-time=7d`, `crictl rmi --prune` (диск маленький).
**Порядок важен:** БД → миграции → приложение. Нельзя катить новый код на старую схему.

### pull-deploy.sh + install.sh (pull-модель)
Причина появления: из GitHub Actions до ВМ нестабильно ходит SSH (канал Azure → Yandex Cloud). Поэтому ВМ сама **опрашивает** GitHub: systemd-таймер каждые 2 минуты запускает скрипт. Он:
- берёт блокировку (`flock`) — два деплоя одновременно не пойдут;
- смотрит SHA последнего коммита main (`git ls-remote`);
- если он уже задеплоен — выходит;
- проверяет, что образ `main-<sha>` уже опубликован в GHCR (значит CI и build прошли);
- делает checkout и запускает `deploy-steps.sh`;
- сохраняет `deployed_sha`; при провале считает попытки (макс. 3) и шлёт Telegram.
`install.sh` ставит скрипт и юнит+таймер (`OnBootSec=2min`, `OnUnitInactiveSec=2min`).
**Плюсы pull-модели:** не нужен входящий SSH с интернета (меньше поверхность атаки), нет секрета с ключом в GitHub, устойчивость к сетевым сбоям. Это ровно подход GitOps-агентов (ArgoCD/Flux), только упрощённый.

### diagnose-patroni.sh и docs/PATRONI_TROUBLESHOOTING.md
Скрипт — быстрая проверка здоровья кластера Patroni (StatefulSet, поды, роли, endpoints, etcd, логи). Документ — разбор реальных проблем: пустой etcd-раздел в конфиге, RBAC на endpoints, ImagePullBackOff, зависший StatefulSet, Service без endpoints, нет подключения web → БД, Alembic Job, метрики Patroni; плюс команды диагностики и восстановление после потери кворума etcd.

---

## 7. Мониторинг и алерты

### monitoring/prometheus.yml и alert.rules.yml (docker-compose)
Скрейп `web:8000/metrics` каждые 15 с. Правила:
- **InstanceDown** — `up == 0` дольше 2 мин (critical);
- **HighErrorRate** — доля 5xx > 5% за 5 мин;
- **LoginBruteForceSuspected** — > 15 неудачных входов за 5 мин (подбор пароля);
- **HighLatencyP95** — p95 > 1.5 с в течение 10 мин.
**Важно:** эти правила работают в compose-варианте. В K8s Alertmanager отключён (экономия RAM), поэтому алерты там — визуальные (дашборды).

### Дашборды Grafana
`classapp_overview` (инфраструктура и бизнес-метрики), `classapp_audit` (журнал входов, события безопасности из Loki), `classapp_dashboard`.

---

## 8. Слабые места — и что отвечать

Лучше самой про них сказать и объяснить, чем ждать вопроса.

| Что видно | Честный ответ |
|---|---|
| Lint в CI с `\|\| true` не блокирует пайплайн | Сделано, чтобы стиль не останавливал выкладку на этапе стабилизации; сейчас контроль идёт локально через pre-commit. Шаг улучшения: убрать `\|\| true`. |
| SSH открыт для `0.0.0.0/0` | Значение по умолчанию; в прод-окружении ограничивается `allowed_ssh_cidrs` (переменная уже есть). Ограничение не сделано, так как адреса GitHub-раннеров плавающие. Pull-деплой снимает необходимость открывать SSH. |
| etcd — одна реплика, `ALLOW_NONE_AUTHENTICATION` | Это учебный/экономный профиль: etcd доступен только внутри кластера (ClusterIP). В проде — 3 реплики, аутентификация, TLS. |
| Два пода Patroni на одной ноде | В дешёвом режиме (1 нода) защита от отказа **ПО** и автоматический failover Postgres работают, но от отказа **ВМ** — нет. Настоящая HA-демонстрация — в demo-профиле (2+1 нода), для этого он и сделан. |
| Prometheus не опубликован наружу | Намеренно: у него нет авторизации. Доступ — SSH-туннель `ssh -L 9090:127.0.0.1:30900`; для публикации нужен basic auth в nginx. |
| Один nginx с hostPort (он же единая точка входа) | Ограничение одной ноды (порт 80 хоста один). В HA-варианте — LoadBalancer/Ingress. |
| Preemptible ВМ | Осознанный выбор по цене; ВМ может быть остановлена. Статический IP и автозапуск K3s (systemd) смягчают последствия; данные БД лежат на PVC. На защиту — demo-профиль без preemptible. |
| Grafana в compose-logging: `admin/admin` | Только для локального окружения. В K8s пароль генерируется и лежит в Secret. |
| `docker-compose.prod.yml` и K8s — два варианта | Compose — простой вариант без Kubernetes; прод идёт в K8s. |
| Alertmanager выключен в K8s | Экономия RAM на 4 ГБ ноде; алерты описаны в `alert.rules.yml`, в K8s есть дашборды. Следующий шаг — включить Alertmanager с Telegram. |
| В Spilo `NAMESPACE=service` | Это внутреннее имя для пути ключей в etcd (`/service/classapp-ha/...`), а не k8s-namespace. Не путать. |
| Образы `latest` для web в манифесте | Реальный тег подставляется при деплое (`kustomize images` + `set image` на `main-<sha>`); в кластере всегда конкретный коммит. |

---

## 9. Вопросы, которые точно зададут

1. **Что произойдёт, если упадёт под с лидером БД?** Patroni (через etcd) повышает реплику до лидера (десятки секунд), role-labeler переставляет метку `patroni-role=master`, Service `classapp-db-master` начинает вести на новый под. Приложение переподключается само.
2. **Что при падении пода web?** Deployment создаёт новый; во время этого readiness убирает мёртвый под из Service, трафик идёт на оставшиеся.
3. **Что при плохом релизе?** Новые поды не пройдут readiness → rollout не завершится → `rollout undo` в `deploy-steps.sh`; плюс иммутабельные теги `main-<sha>` позволяют откатиться на любой коммит.
4. **Как масштабируется?** Горизонтально: HPA 2–5 подов по CPU; в demo-режиме дополнительные ноды добавляются Terraform + Ansible.
5. **Где хранятся секреты?** В k8s Secret; генерируются Ansible при первом bootstrap; не в git. `vault.yml` — ansible-vault и gitignore.
6. **Как воспроизвести всё с нуля?** `terraform apply` → `generate_inventory.sh` → `ansible-playbook` → push в main (или таймер pull-deploy на ВМ сам подтянет релиз).
7. **Чем CI отличается от CD?** CI — проверка кода (lint, тесты, сборка); CD — доставка в окружение (build.yml + deploy). Выкладка идёт только после зелёного CI.
8. **Как узнаёте, что что-то сломалось?** Метрики и дашборды Grafana, логи в Loki, Telegram-уведомления о CI/build/deploy, healthcheck'и и пробы k8s.
9. **Как защищено приложение?** непривилегированный пользователь в контейнере, bandit в pre-commit, ограничение по сети через security group, секреты вне образа, `sslmode=require` к БД, журнал входов и алерт на подбор пароля, минимальные RBAC права у Patroni.
10. **Почему K3s, а не обычный k8s?** Один бинарник, мало памяти (важно для ВМ 4 ГБ), в комплекте containerd, metrics-server, Helm-контроллер.
11. **Зачем StatefulSet для БД?** Стабильные имена и персональный диск каждой реплики.
12. **Зачем readiness и liveness отдельно?** Не готов ≠ мёртв: приложение может стартовать долго, и перезапускать его нельзя, но и трафик слать рано.

---

## 10. Что стоит перепроверить перед защитой

- Что последний деплой реально прошёл и поды в `Running`: `kubectl get pods -A` на ВМ.
- Какой способ деплоя вы показываете: SSH (`deploy.yml`) или pull-таймер — выберите один и расскажите историю про нестабильный канал как обоснование.
- Демо-режим: применить `terraform.tfvars.demo.example` заранее, не в день защиты, и проверить failover (`kubectl delete pod classapp-patroni-0`, наблюдать смену лидера).
- Что в README и здесь указаны актуальные значения (число реплик, порты).
