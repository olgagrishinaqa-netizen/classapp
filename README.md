# classapp

Веб-приложение на Flask для учёта дел школьного класса: пользователи и роли, задачи, новости,
расписание, взносы и расходы, состав класса. Дипломный DevOps-проект: инфраструктура как код,
CI/CD, Kubernetes, отказоустойчивая БД, мониторинг и бэкапы.

## Состав репозитория

| Путь | Назначение |
|---|---|
| `app/`, `config.py`, `alembic/` | приложение (Flask, SQLAlchemy) и миграции БД |
| `tests/` | автотесты (pytest) и нагрузочный сценарий Locust (`tests/load/`) |
| `Dockerfile`, `.dockerignore`, `entrypoint.sh`, `gunicorn.conf.py` | образ приложения |
| `requirements*.txt` | зависимости: `requirements.txt` — только продакшен (в образе), `-test` — для CI, `-dev` — для разработчика |
| `terraform/aws/` | IaC: ВМ, Elastic IP, security group, S3-бакет бэкапов, IAM-роль |
| `terraform/` (корень) | устаревший вариант для Yandex Cloud (legacy) |
| `ansible/` | роли: `common`, `k3s`, `bootstrap_secrets`, `monitoring`, `backup` |
| `k8s/` | манифесты K3s: etcd, Patroni (PostgreSQL HA), миграции, web, nginx, HPA |
| `scripts/pull-deploy/` | шаги деплоя (`deploy-steps.sh`); запасной pull-деплой на ВМ |
| `.github/` | CI/CD: `workflows/ci.yml`, `workflows/deploy.yml`, `dependabot.yml` (только обновления безопасности) |
| `.trivyignore.yaml` | обоснованные исключения сканера безопасности Trivy |
| `monitoring/`, `provisioning/`, `docker-compose.*.yml` | локальные стеки Prometheus/Grafana/Loki |
| `docs/guide/` | **учебное руководство по каждой папке и файлу** (читать с [docs/guide/README.md](docs/guide/README.md)) |
| `docs/` | шпаргалка к защите, разбор проблем Patroni/etcd |

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

Образ собирается **один раз**: именно тот образ, который прошёл проверки и дымовой тест, публикуется и затем выкатывается.

| Событие | Что происходит |
|---|---|
| коммит в **любую ветку** | `ci.yml`: **lint** (black, isort, flake8, bandit, shellcheck, hadolint, actionlint) · **secrets-scan** (gitleaks) · **dependency-audit** (pip-audit) · **iac** (terraform fmt/validate, ansible-lint, kubeconform, Trivy) · **test** (pytest на SQLite и PostgreSQL, покрытие ≥ 70%) · **migrations** (Alembic на PostgreSQL: накат, проверка расхождения моделей, откат и повторный накат) → **build** (сборка, сканирование образа Trivy, дымовой тест с ограничениями как в Kubernetes, SBOM, публикация в GHCR с тегом `<ветка>-<sha>`, подписанные аттестации происхождения и состава образа); отчёты тестов и SBOM сохраняются как артефакты |
| коммит в **`main`** | после успешного CI `deploy.yml` проверяет подпись происхождения образа и выкатывает его **по неизменяемому дайджесту**: миграции Alembic → rollout всех компонентов → проверка `/healthz` и входа изнутри и снаружи; при сбое **откат всех изменённых компонентов**; уже выкаченный коммит повторно не деплоится |
| результат | уведомление в Telegram о CI и о деплое (секреты `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) |

Меры безопасности пайплайна: действия GitHub закреплены по SHA коммита, минимальные права токена, имена веток не подставляются
в shell напрямую (защита от инъекции), деплой проверяет отпечаток сервера, версии зависимостей зафиксированы намеренно (стабильность), а Dependabot
присылает только срочные обновления безопасности при найденной уязвимости. Принятые риски перечислены с обоснованием в `.trivyignore.yaml`.

Секреты GitHub для деплоя: `SSH_HOST`, `SSH_KNOWN_HOSTS` (оба записывает `make github-secrets`), `SSH_KEY` (приватный ключ,
один раз вручную), опционально `SSH_PORT`. Деплой вручную (например, если коммит пришёл при выключенной ВМ):
Actions → *Deploy to Production* → *Run workflow* и полный SHA коммита.

## База данных и бэкапы

PostgreSQL работает под управлением Patroni (Zalando Spilo) с etcd для координации, схема
меняется только миграциями Alembic (Job `classapp-migrate` перед обновлением web). Роль `backup`
ставит systemd-таймер: каждую ночь (02:30) `pg_dump` и архив загрузок (включая чеки расходов,
`/var/lib/classapp/uploads`) уходят в S3, хранение 14 дней, доступ через IAM-роль ВМ.

На ВМ установлен скрипт `classapp-restore`:

```bash
sudo systemctl start classapp-backup       # сделать бэкап прямо сейчас
sudo classapp-restore verify               # проверить свежий бэкап во временной БД (боевую не трогает)
sudo classapp-restore apply                # ВОССТАНОВИТЬ БД и загрузки из свежего бэкапа (данные заменяются!)
sudo classapp-restore apply <файл.sql.gz>  # из конкретного дампа (aws s3 ls s3://<бакет>/db/)
```

Восстановление создаёт базу от `template0`: в `template1` у Spilo уже есть служебные схемы,
которые есть и в дампе. `apply` на время останавливает web и возвращает его обратно.

## Состояние Terraform

Состояние хранится в S3 (бакет `classapp-tfstate-<account>` с версионированием и шифрованием),
а не в локальном файле. Бакет создаёт `terraform/bootstrap-state.sh` (вызывается из `make tf-init`
автоматически) и не удаляется вместе с инфраструктурой. Блокировок нет (оператор один); при
переходе на Terraform ≥ 1.10 можно добавить `use_lockfile = true`.

## Единственный путь деплоя

Автоматический деплой — только `deploy.yml` (push по SSH после успешного CI на `main`).
Pull-таймер `scripts/pull-deploy/` — запасной вариант (если SSH с GitHub недоступен): `install.sh`
по умолчанию его только устанавливает, но не включает (`sudo bash install.sh --enable`).

## Локальная разработка

```bash
cp .env.sample .env
docker compose -f docker-compose.dev.yml up --build   # http://localhost:8000
pip install -r requirements.txt -r requirements-dev.txt
pytest                                                # SQLite; TEST_DATABASE_URL — для Postgres
```

Нагрузочный тест: `locust -f tests/load/locustfile.py --host=http://localhost:8000`.
Разбор проблем с Patroni/etcd: [docs/PATRONI_TROUBLESHOOTING.md](docs/PATRONI_TROUBLESHOOTING.md).
