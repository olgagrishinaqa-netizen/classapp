# Руководство по проекту classapp

Это учебный разбор проекта «папка за папкой, файл за файлом». Он написан для подготовки к защите
диплома: что лежит в каждой папке, зачем нужен каждый файл и что делают его строки.

## Как читать

Идите по порядку: каждый следующий файл опирается на предыдущий.

| № | Файл руководства | О чём |
|---|---|---|
| 0 | этот файл | карта проекта, путь изменения от кода до пользователя, словарь терминов |
| 1 | [01-app.md](01-app.md) | Python-приложение: конфиг, модели, формы, маршруты, аудит, шаблоны |
| 2 | [02-database-and-tests.md](02-database-and-tests.md) | миграции Alembic и автотесты |
| 3 | [03-docker-and-cicd.md](03-docker-and-cicd.md) | Docker, линтеры, GitHub Actions (CI/CD), Makefile, скрипты деплоя |
| 4 | [04-kubernetes.md](04-kubernetes.md) | манифесты K3s: etcd, Patroni, web, nginx, миграции, HPA |
| 5 | [05-terraform-ansible.md](05-terraform-ansible.md) | Terraform (AWS), Ansible, бэкапы, расписание ВМ |
| 6 | [06-monitoring-and-logs.md](06-monitoring-and-logs.md) | Prometheus, Grafana, Loki, Promtail, алерты |

Принцип подробности: файлы инфраструктуры и CI/CD, о которых вас будут спрашивать на защите,
разобраны **построчно**. Код приложения, шаблоны и тесты разобраны **по блокам** (по функциям),
потому что построчно это тысячи строк без пользы.

## Карта репозитория

```
classapp/
├── app/                 приложение Flask (код, шаблоны, статика)        -> 01-app.md
├── alembic/, alembic.ini   миграции схемы БД                              -> 02
├── tests/               автотесты pytest и нагрузочный тест Locust        -> 02
├── config.py            конфигурация (dev/prod)                           -> 01
├── Dockerfile, entrypoint.sh, gunicorn.conf.py   образ и запуск           -> 03
├── .github/workflows/   CI/CD: ci.yml, build.yml, deploy.yml              -> 03
├── .pre-commit-config.yaml, .flake8, pyproject.toml   линтеры             -> 03
├── Makefile             «одна команда»: make up                           -> 03
├── scripts/pull-deploy/ шаги деплоя на ВМ (+ запасной pull-таймер)        -> 03
├── k8s/                 манифесты Kubernetes                              -> 04
├── terraform/           IaC: terraform/aws (основной), корень (legacy)    -> 05
├── ansible/             настройка ВМ: K3s, секреты, бэкапы, мониторинг    -> 05
├── monitoring/, provisioning/, promtail-config.yml   локальный стек наблюдаемости -> 06
├── docker-compose.*.yml   локальные стеки (dev, logging, устаревший prod) -> 03, 06
├── docs/                заметки (эта папка guide, шпаргалка, Patroni)
└── requirements*.txt, pytest.ini, .env.sample, .gitignore, .gitattributes   вспомогательное
```

## Путь изменения от кода до пользователя

```
git push (любая ветка)
  -> ci.yml:    линтер -> pytest -> пробная сборка образа -> уведомление в Telegram
  -> build.yml: сборка образа и загрузка в GHCR (тег <ветка>-<sha>)
  -> (только main) deploy.yml: по SSH на ВМ -> deploy-steps.sh:
        миграции Alembic -> kubectl apply -> rollout -> проверка /healthz
  -> пользователь:  браузер -> порт 80 -> nginx -> web (2 реплики) -> Patroni/PostgreSQL
```

Как появилась сама ВМ (делается один раз командой `make up`):

```
Terraform (terraform/aws)  ВМ, Elastic IP, security group, S3, IAM, расписание
  -> generate_inventory.sh  из вывода Terraform делает inventory для Ansible
  -> Ansible (ansible/)     пакеты, swap, K3s, секреты, бэкапы
  -> deploy-steps.sh        манифесты k8s, миграции, приложение
```

## Что за что отвечает (по требованиям диплома)

| Требование | Где реализовано |
|---|---|
| Terraform | `terraform/aws/` (+ состояние в S3, `terraform/bootstrap-state.sh`) |
| Автоматизированный CI/CD | `.github/workflows/`, `scripts/pull-deploy/deploy-steps.sh` |
| Kubernetes | K3s, манифесты в `k8s/` |
| Вход снаружи по одному порту | nginx на порту 80 (`k8s/classapp-nginx.yaml`), security group открывает только 80/443/22 |
| nginx распределяет запросы | `/` -> web (несколько реплик через Service), `/grafana/` -> Grafana |
| Ansible | `ansible/` (роли common, k3s, bootstrap_secrets, monitoring, backup) |
| Patroni | `k8s/patroni.yaml` + `k8s/etcd.yaml` |
| Бэкапы | `ansible/roles/backup/` (ночной pg_dump + загрузки в S3, `classapp-restore`) |

## Словарь терминов

- **IaC (Infrastructure as Code)** — инфраструктура описана файлами в git и поднимается командами, а не кликами в консоли.
- **Terraform** — создаёт облачные ресурсы (ВМ, сети, бакеты) из описания. `plan` показывает изменения, `apply` их применяет.
- **Ansible** — настраивает уже существующую ВМ (ставит пакеты, K3s). Идемпотентен: повторный запуск ничего не ломает.
- **K3s** — лёгкий Kubernetes в одном бинарнике; подходит для ВМ на 2 ГБ.
- **Pod** — минимальная единица в Kubernetes: один или несколько контейнеров. **Deployment** — «держи N одинаковых подов». **StatefulSet** — то же, но для хранилищ с постоянными данными (Patroni). **Service** — постоянный адрес и балансировщик перед подами. **Job** — одноразовая задача (миграции).
- **Patroni** — управляет PostgreSQL: выбирает лидера, при его отказе переключает на реплику. **etcd** — хранилище, где Patroni держит «кто сейчас лидер».
- **GHCR** — реестр Docker-образов GitHub (ghcr.io).
- **Alembic** — инструмент миграций схемы БД.
- **Gunicorn** — production-сервер для Flask (несколько воркеров). **WSGI** — стандарт, по которому сервер вызывает приложение.
- **Elastic IP** — постоянный публичный адрес в AWS: не меняется при остановке ВМ.
- **EventBridge Scheduler** — планировщик AWS: по расписанию запускает и останавливает ВМ.
