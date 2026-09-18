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

`terraform.tfstate`, `terraform.tfvars` и токены не должны попадать в Git.
Для production используйте remote backend в Yandex Object Storage и ограничьте
`allowed_ssh_cidrs` адресом VPN/офиса.

### Подготовка нод через Ansible

```bash
cd ansible
cp inventory/hosts.ini.example inventory/hosts.ini
# Замените public_ip на значения из terraform output.
ansible-galaxy collection install -r requirements.yml
ansible-playbook -i inventory/hosts.ini playbook.yml \
  -e "k3s_token=$(openssl rand -hex 32)"
```

Роль `common` устанавливает Docker, curl, git, kubectl и Helm. Роль `k3s`
устанавливает фиксированную версию K3s, создает HA control plane и подключает
workers. Секрет `k3s_token` рекомендуется хранить в Ansible Vault.

### Мониторинг и логирование в Kubernetes

Роль `monitoring` устанавливает Helm chart `kube-prometheus-stack`, включая
Prometheus, Grafana, node-exporter и kube-state-metrics. Манифест
`classapp-monitoring.yaml` добавляет ServiceMonitor для Flask `/metrics`,
Patroni API `/metrics` и Grafana dashboard с HTTP 5xx, готовностью web/Patroni
и CPU нод.

Перед запуском роли создайте Secret Grafana:

```bash
kubectl create namespace monitoring
kubectl -n monitoring create secret generic classapp-grafana \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='CHANGE_ME'
```

### CI/CD и endpoints

После push в `main` `ci.yml` выполняет проверки, `build.yml` публикует образ в
GHCR, а `deploy.yml` запускается через `workflow_run` после успешной сборки
`main`. Deploy применяет Kubernetes-манифесты, выполняет Alembic Job до
обновления web Deployment и проверяет rollout.

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
