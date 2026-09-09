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
infra/terraform/      # IaC: сеть, VM, container registry в Yandex Cloud
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

## Инфраструктура (Terraform)

Находится в `infra/terraform/`: сеть, VM, Container Registry в Yandex Cloud.

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply
```

> ⚠️ `terraform.tfstate` и `terraform.tfvars` не должны лежать в git — вынесены в `.gitignore`,
> состояние должно храниться в remote backend (например, Yandex Object Storage).

## Мониторинг

После деплоя доступны:
- Prometheus: `http://<SSH_HOST>:9090`
- Grafana: `http://<SSH_HOST>:3000` (логин `admin`, пароль — секрет `GRAFANA_ADMIN_PASSWORD`)
- Health-check приложения: `http://<SSH_HOST>/healthz`
- Метрики приложения: `http://<SSH_HOST>/metrics` (изнутри Docker-сети; наружу не проброшены)
