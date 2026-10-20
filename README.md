# classapp

Веб-приложение на Flask для учёта дел школьного класса: пользователи и роли, задачи, новости,
расписание, взносы и расходы, состав класса. Дипломный DevOps-проект: инфраструктура как код,
CI/CD, Kubernetes, отказоустойчивая БД, мониторинг и бэкапы.

## Состав репозитория

| Путь | Назначение |
|---|---|
| `app/`, `config.py`, `alembic/` | приложение (Flask, SQLAlchemy) и миграции БД |
| `tests/` | автотесты (pytest) и нагрузочный сценарий Locust (`tests/load/`) |
| `Dockerfile`, `entrypoint.sh`, `gunicorn.conf.py` | образ приложения |
| `terraform/aws/` | IaC: ВМ, Elastic IP, security group, S3-бакет бэкапов, IAM-роль |
| `terraform/` (корень) | устаревший вариант для Yandex Cloud (legacy) |
| `ansible/` | роли: `common`, `k3s`, `bootstrap_secrets`, `monitoring`, `backup` |
| `k8s/` | манифесты K3s: etcd, Patroni (PostgreSQL HA), миграции, web, nginx, HPA |
| `scripts/pull-deploy/` | шаги деплоя (`deploy-steps.sh`); запасной pull-деплой на ВМ |
| `.github/workflows/` | CI/CD: `ci.yml`, `build.yml`, `deploy.yml` |
| `monitoring/`, `provisioning/`, `docker-compose.*.yml` | локальные стеки Prometheus/Grafana/Loki |
| `docs/` | заметки по защите и разбору проблем (Patroni/etcd) |

## Развёртывание с нуля одной командой

Вся инфраструктура описана кодом: Terraform создаёт ВМ, сеть и S3-бакет в AWS, Ansible ставит
K3s, секреты и мониторинг, затем применяются манифесты `k8s/`.

```bash
# нужны: terraform, ansible, jq, SSH-ключ (~/.ssh/id_ed25519 или id_rsa), доступ к AWS (~/.aws)
make up
```

`make up` = `make infra` (Terraform) → `make configure` (Ansible) → `make deploy` (приложение).
Шаги можно запускать по отдельности; `make destroy` удаляет инфраструктуру, `make check` запускает
те же проверки, что и CI. Сгенерированные пароли администратора и Grafana Ansible показывает
один раз и сохраняет в `ansible/last-run.log` (в `.gitignore`).

Образ `main-<sha>` для деплоя должен уже лежать в GHCR, то есть CI и сборка на `main` должны
пройти хотя бы раз.

## Как попасть в приложение

Снаружи открыт один порт — **80**. Его слушает nginx (Deployment `classapp-nginx`) и
распределяет запросы:

- `/` → `classapp-web-service` (Flask/gunicorn, несколько реплик за Service);
- `/grafana/` → Grafana.

Prometheus наружу не публикуется: `ssh -L 9090:127.0.0.1:30900 ubuntu@<IP>`, затем
`http://localhost:9090`. Проверка живости: `GET /healthz`.

## Сборка и CI/CD

| Событие | Что происходит |
|---|---|
| коммит в **любую ветку** | `ci.yml`: линтер (pre-commit: black, isort, flake8, bandit) → автотесты (pytest) → пробная сборка образа. Затем `build.yml` собирает образ и загружает его в GHCR с тегом `<ветка>-<sha>`; отчёты тестов (`junit`, `coverage`) сохраняются как артефакт GitHub Actions |
| коммит в **`main`** | дополнительно `deploy.yml` выкатывает образ на ВМ: миграции Alembic → rollout → проверка `/healthz`, при сбое откат |
| результат сборки и деплоя | уведомление в Telegram (секреты `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; без них в логе предупреждение) |

Секреты GitHub для деплоя: `SSH_HOST` (Elastic IP, `terraform output master1_static_ip`),
`SSH_KEY` (приватный ключ), опционально `SSH_PORT`.

## База данных и бэкапы

PostgreSQL работает под управлением Patroni (Zalando Spilo) с etcd для координации, схема
меняется только миграциями Alembic (Job `classapp-migrate` перед обновлением web). Роль `backup`
ставит systemd-таймер: каждую ночь `pg_dump` и архив загрузок уходят в S3 (хранение 14 дней,
доступ через IAM-роль ВМ).

Восстановление БД:

```bash
aws s3 cp s3://<бакет>/db/<файл>.sql.gz - | gunzip \
  | kubectl exec -i <pod-patroni-master> -c patroni -- psql -U postgres classapp
```

## Локальная разработка

```bash
cp .env.sample .env
docker compose -f docker-compose.dev.yml up --build   # http://localhost:8000
pip install -r requirements.txt -r requirements-dev.txt
pytest                                                # SQLite; TEST_DATABASE_URL — для Postgres
```

Нагрузочный тест: `locust -f tests/load/locustfile.py --host=http://localhost:8000`.
Разбор проблем с Patroni/etcd: [docs/PATRONI_TROUBLESHOOTING.md](docs/PATRONI_TROUBLESHOOTING.md).
