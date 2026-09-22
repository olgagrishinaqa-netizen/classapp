# classapp

Веб-приложение на Flask для учёта дел класса (пользователи, расходы, задачи).
Дипломный DevOps-проект: автоматизированная инфраструктура (Terraform, Yandex Cloud),
CI/CD (GitHub Actions) и мониторинг (Prometheus + Grafana).

## Стек

- **Backend**: Flask, SQLAlchemy, Alembic (миграции), Flask-Login, Flask-WTF
- **БД**: PostgreSQL 15
- **Контейнеризация**: Docker, Docker Compose
- **Инфраструктура**: Terraform (Yandex Cloud — VM, сеть, Container Registry)
- **CI/CD**: GitHub Actions (lint → test → build → push → deploy)
- **Мониторинг**: Prometheus, Grafana; метрики Flask через `prometheus-flask-exporter`
- **Уведомления**: Telegram-бот о результатах CI/CD

## Структура репозитория

```
app/                  # исходный код приложения (Flask app factory, extensions)
alembic/              # миграции БД
terraform/            # IaC: VPC, multi-zone VM и security groups в Yandex Cloud
ansible/              # роли common, k3s и monitoring
tests/                # автотесты (pytest)
monitoring/           # конфиг Prometheus
.github/workflows/    # CI/CD пайплайны
docker-compose.dev.yml    # локальная разработка
docker-compose.prod.yml   # продакшн-стек (app + db + prometheus + grafana)
```

## Запуск локально

```bash
cp .env.sample .env        # заполнить переменные окружения
docker compose -f docker-compose.dev.yml up --build
```

Приложение будет доступно на `http://localhost:8000`, health-check — на `/healthz`.

## Запуск тестов

```bash
pip install -r requirements.txt -r requirements-dev.txt
docker run -d --rm -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=classapp_test postgres:15
pytest
```

### Нагрузочное тестирование

Сценарий на Locust лежит в `tests/load/locustfile.py` и имитирует типичную
навигацию залогиненного администратора (дашборд, задачи, новости, расходы).

```bash
# UI-режим (веб-интерфейс на http://localhost:8089)
locust -f tests/load/locustfile.py --host=http://localhost:8000

# headless-режим с отчётом (для CI/сравнения нагрузки)
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
  --headless -u 20 -r 5 --run-time 1m --csv=load_report
```

Учётные данные берутся из `LOAD_TEST_PHONE`/`LOAD_TEST_PASSWORD` (по умолчанию —
дефолтный bootstrap-админ дев-стенда, `ADMIN_PHONE`/`ADMIN_PASSWORD` из `.env`).

## CI/CD пайплайн

Три workflow в `.github/workflows/`:

| Workflow | Триггер | Что делает |
|---|---|---|
| `ci.yml` | push в любую ветку, PR в main/master | линтер (pre-commit) → автотесты (pytest + Postgres-сервис) → пробная сборка образа → уведомление в Telegram |
| `build.yml` | push в любую ветку | сборка Docker-образа, пуш в GHCR с тегом `<ветка>-<sha>`; тег `latest` обновляется только на `main` |
| `deploy.yml` | успешный `build.yml` на `main` | копирует `docker-compose.prod.yml` на прод-VM по SSH, поднимает стек, применяет миграции Alembic, уведомление в Telegram |

### Необходимые GitHub Secrets

- `SSH_HOST`, `SSH_KEY` — доступ к прод-VM
- `APP_SECRET_KEY`, `APP_DB_PASSWORD` — переменные окружения приложения
- `GRAFANA_ADMIN_PASSWORD` — пароль администратора Grafana
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — уведомления о результатах сборки/деплоя

## Развертывание инфраструктуры с нуля (IaC)

Каноническая IaC-конфигурация находится в `terraform/`. Она создает VPC с
подсетями в `ru-central1-a`, `ru-central1-b` и `ru-central1-c`, VM для K3s
control-plane/worker и security group. В outputs доступны внешние и внутренние
IP-адреса каждой ноды.

Один и тот же код работает в двух режимах — переключение только через tfvars,
дублировать инфраструктурный код не нужно:

| Режим | tfvars | Нод | Стоимость | Когда |
|---|---|---|---|---|
| **Повседневный** | `terraform.tfvars.example` | 1 (`master-1`, preemptible, HDD) | минимальная | обычная работа приложения для себя |
| **Демо для защиты** | `terraform.tfvars.demo.example` | 3 (2 master + 1 worker, обычные, SSD) | заметно выше | временно, на время показа HA/масштабируемости |

`master-1` (зона `ru-central1-a`) присутствует в обоих режимах и никогда не
пересоздаётся при переключении — данные Patroni на его локальном диске не
теряются. Пересоздаются/удаляются только добавленные `master-2`/`worker-1`.

### Terraform в Yandex Cloud

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Заполните cloud_id, folder_id, yc_token и ssh_public_key.
terraform init
terraform fmt -check
terraform plan -out=tfplan
terraform apply tfplan
terraform output -json k3s_nodes
```

Перед защитой — временно домасштабировать до полного кластера, после — вернуться обратно:

```bash
cp terraform.tfvars.demo.example terraform.tfvars.demo
# Заполните те же поля, что и в основном tfvars.
terraform apply -var-file=terraform.tfvars.demo    # 1 -> 3 ноды
./generate_inventory.sh && cd ../ansible && ansible-playbook -i inventory/hosts.ini playbook.yml && cd ../terraform
# k3s_token берётся из group_vars/vault.yml (тот же, что при первом запуске) —
# новые ноды подключатся к уже работающему кластеру, данные не теряются.
# ... демонстрация HPA/реплик/Patroni failover ...
terraform apply -var-file=terraform.tfvars.example  # обратно на 1 дешёвую ноду
```

`terraform.tfstate`, `terraform.tfvars*` и токены не должны попадать в Git.
Для production используйте remote backend в Yandex Object Storage и ограничьте
`allowed_ssh_cidrs` адресом VPN/офиса.

### Подготовка нод через Ansible

```bash
# Inventory генерируется автоматически из terraform output — руками
# редактировать inventory/hosts.ini не нужно (и не надо коммитить, см. .gitignore).
cd terraform && ./generate_inventory.sh && cd ../ansible

ansible-galaxy collection install -r requirements.yml

# k3s_token задаётся ОДИН раз и переиспользуется при каждом следующем прогоне
# (в т.ч. при демо-масштабировании) — иначе новые ноды не смогут
# присоединиться к уже поднятому кластеру. group_vars/vault.yml в .gitignore.
echo "k3s_token: \"$(openssl rand -hex 32)\"" > group_vars/vault.yml

ansible-playbook -i inventory/hosts.ini playbook.yml
```

Роль `common` устанавливает Docker, curl, git, kubectl и Helm. Роль `k3s`
устанавливает фиксированную версию K3s, создает HA control plane (2 master)
и подключает worker. Роль `bootstrap_secrets` при первом прогоне генерирует
и создаёт `classapp-secrets`/`classapp-grafana` — см. раздел «Мониторинг и
логирование» ниже. Хотите зашифровать `vault.yml` вместо простого файла —
используйте `ansible-vault encrypt group_vars/vault.yml`.

После первого успешного прогона обновите GitHub secret `SSH_HOST` — он должен
указывать на публичный IP первого мастера (`terraform output k3s_public_ips`),
т.к. `deploy.yml` применяет манифесты через SSH на этот узел и локальный
`kubectl`/`kubeconfig` (`/etc/rancher/k3s/k3s.yaml`) этой control-plane ноды.

### Конфигурация Patroni и etcd в Kubernetes

В манифесте `k8s/patroni.yaml` определены:

- **Образ Patroni**: `registry.opensource.zalan.do/acid/spilo-15:3.0-p1` (Zalando Spilo).
  От образов `bitnami(legacy)/postgresql-ha` пришлось отказаться — они несколько
  раз подряд оказывались недоступны для pull (архивный registry, устаревшие теги,
  rate-limit), что блокировало rollout всего StatefulSet. Spilo — проверенный,
  широко используемый образ (используется Zalando Postgres Operator), который
  надежно стартует и не требует кастомных initContainer/ConfigMap для etcd.

- **etcd-конфигурация через переменные окружения** (не ConfigMap):
  ```yaml
  env:
    - name: SCOPE
      value: classapp-ha
    - name: NAMESPACE
      value: service
    - name: ETCD_HOSTS
      value: etcd-service:2379
  ```
  В образе Zalando Spilo bootstrap-скрипт генерирует Patroni config из
  переменных `SCOPE` и `NAMESPACE`, а не из `PATRONI_SCOPE` / `PATRONI_NAMESPACE`.
  Эти значения должны быть одинаковыми на всех подах кластера, иначе новый pod
  создаст отдельный "остров" в etcd вместо присоединения к существующему мастеру
  (split-brain).

- **etcd Deployment** (`k8s/etcd.yaml`): однопроцессный etcd для координации HA-кластера.
  Service `etcd-service:2379` доступен для Patroni pods.

- **Patroni StatefulSet** (2 реплики): каждый pod имеет:
  - readinessProbe + livenessProbe с `initialDelaySeconds: 60-90` для ожидания инициализации БД
  - Два Service: `classapp-db-master` (для записи) и `classapp-db-replica` (для чтения)
  - `volumeClaimTemplates` (`patroni-data`), чтобы данные PostgreSQL сохранялись между
    пересозданиями pod'ов и не терялись при rolling update/eviction
  - Spilo сам управляет правами на `/data`, поэтому дополнительные initContainer
    или `fsGroup` не требуются.

- **role-labeler sidecar**: периодически запрашивает API Patroni и помечает pod 
  label `patroni-role=master` или `patroni-role=replica` для правильной маршрутизации 
  трафика через Service.

- **RBAC для Kubernetes API**: ServiceAccount `classapp-patroni` должен иметь доступ
  к `pods`, `pods/proxy`, `endpoints` и `services` для корректного leader/replica
  discovery и patch endpoint objects. Без этого Patroni запустит leader, но второй
  pod не сможет корректно присоединиться.

- **Создание прикладной БД `classapp`**: в отличие от bitnami-образа, Spilo не
  создаёт дополнительную БД автоматически из переменных окружения. Поэтому
  `k8s/migrate-job.yaml` перед запуском Alembic идемпотентно выполняет
  `CREATE DATABASE classapp`, если она ещё не существует.

- **Bootstrap администратора**: приложение создаёт администратора при первом запуске,
  но по умолчанию не перезаписывает существующий пароль на каждом рестарте pod'а.
  Для принудительного сброса используйте `ADMIN_RESET_PASSWORD_ON_BOOT=true`.

- **Секреты веб-приложения**: `classapp-web` и `classapp-migrate` читают
  `DB_PASSWORD`, `SECRET_KEY`, `ADMIN_PHONE`, `ADMIN_PASSWORD`, `DATABASE_URL`
  из секрета `classapp-secrets` через `secretKeyRef`.
  В `deploy.yml` перед миграциями выполняется идемпотентная «нормализация» секрета:
  из текущего `db-password` автоматически собирается корректный
  `database-url` (`...@classapp-db-master:5432/classapp?sslmode=require`, с URL-encoding пароля).

- **Лимит загрузок**: глобальный размер загружаемого файла ограничен переменной
  `MAX_CONTENT_LENGTH` (по умолчанию `10 MiB`). Лимит применяется к API/формам
  загрузки новостей, чеков и отчётов.

Пример создания/обновления секрета:
```bash
kubectl -n default create secret generic classapp-secrets \
  --from-literal=db-password='CHANGE_ME' \
  --from-literal=secret-key='CHANGE_ME' \
  --from-literal=admin-phone='79990000000' \
  --from-literal=admin-password='CHANGE_ME' \
  --from-literal=database-url='postgresql://postgres:CHANGE_ME@classapp-db-master:5432/classapp?sslmode=require' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Проверка готовности Patroni:
```bash
kubectl get pods -l app.kubernetes.io/name=patroni --show-labels
kubectl logs -l app.kubernetes.io/name=patroni -c patroni --tail=50
kubectl get endpoints classapp-db-master  # должен быть непуст
```

Если Patroni pods зависают в состоянии "Pending" или "CrashLoopBackOff", 
проверьте:
1. `kubectl describe pod classapp-patroni-0` — ищите описание и события
2. `kubectl logs classapp-patroni-0 -c patroni` — логи инициализации БД
3. `kubectl get svc etcd-service` — убедитесь, что etcd сервис доступен

### Масштабируемость

`classapp-web` и `classapp-nginx` разворачиваются в нескольких репликах
(3 и 2 соответственно), балансировка между ними обеспечивается штатными
Kubernetes Service (`classapp-web-service`, NodePort `classapp-nginx`).
Дополнительно `k8s/hpa.yaml` объявляет `HorizontalPodAutoscaler` для
`classapp-web` (2–5 реплик по CPU, порог 70%) — работает из коробки, т.к.
K3s поставляется с `metrics-server` по умолчанию.

Весь стек (etcd, Patroni, миграции, web, nginx, HPA) собран в
`k8s/kustomization.yaml`, поэтому `kubectl apply -k k8s/` — самостоятельный,
воспроизводимый способ поднять всё приложение одной командой.

### Мониторинг и логирование в Kubernetes

Роль `monitoring` устанавливает Helm chart `kube-prometheus-stack`, включая
Prometheus, Grafana, node-exporter и kube-state-metrics. Манифест
`classapp-monitoring.yaml` добавляет ServiceMonitor для Flask `/metrics`,
Patroni API `/metrics` и Grafana dashboard с HTTP 5xx, готовностью web/Patroni
и CPU нод. Локальный docker-compose стек мониторинга (`monitoring/prometheus.yml`)
дополнительно подключает alert-правила из `monitoring/alert.rules.yml`
(недоступность инстанса, повышенная доля 5xx-ответов).

Секреты `classapp-secrets` (для приложения) и `classapp-grafana` создаются
автоматически ролью `bootstrap_secrets`, которая выполняется перед `monitoring`
в том же прогоне `ansible-playbook playbook.yml` — значения генерируются
случайно и создаются **только при первом запуске** (идемпотентно, повторные
прогоны их не трогают и не перезаписывают уже работающий пароль БД). Сразу
после первого запуска сохраните пароли, которые Ansible выведет в консоль
(`debug`-таск в `roles/bootstrap_secrets`) — повторно они нигде не показываются.
Если нужны собственные значения вместо случайных — создайте секреты вручную
до запуска playbook, роль просто увидит, что они уже есть, и пропустит шаг.

### CI/CD и endpoints

После push в `main` `ci.yml` выполняет проверки, `build.yml` публикует образ в
GHCR, а `deploy.yml` запускается через `workflow_run` после успешной сборки
`main`. Deploy применяет Kubernetes-манифесты, выполняет Alembic Job до
обновления web Deployment и проверяет rollout.

Шаги SSH/SCP в `deploy.yml` (`appleboy/ssh-action`, `appleboy/scp-action`)
обёрнуты в `Wandalen/wretry.action` (3 попытки, задержка 15с). Причина:
эти экшены при старте скачивают свой бинарь (`drone-ssh`) с CDN GitHub
Releases, и изредка это скачивание падает с транзиентным 502/504 от CDN
**еще до** SSH-подключения к серверу — из-за чего наш идемпотентный
деплой-скрипт вообще не успевает запуститься. Retry-обёртка решает эту
проблему автоматически, без участия человека; повторный запуск самого
деплой-скрипта безопасен, так как все его шаги идемпотентны (`kubectl apply`,
Job с уникальным именем по SHA коммита и т.д.).

После установки доступны:
- Grafana: `http://<NODE_IP>:30300`
- Prometheus: `http://<NODE_IP>:30900`
- Health-check: `http://<NODE_IP>:30080/healthz`
- Метрики Flask: `/metrics`
- Метрики Patroni: `/metrics` на `classapp-patroni:8008`

Проверка:

```bash
kubectl -n default get pods
kubectl -n monitoring get pods
kubectl -n monitoring get servicemonitors
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

## Troubleshooting

При проблемах с развёртыванием Patroni HA, etcd конфигурацией или подключением
к БД см. [docs/PATRONI_TROUBLESHOOTING.md](docs/PATRONI_TROUBLESHOOTING.md) для
подробного описания типичных проблем и их решений.
