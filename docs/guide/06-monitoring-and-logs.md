# 6. Мониторинг и логи

В проекте два независимых контура наблюдаемости:

| Контур | Где работает | Что даёт |
|---|---|---|
| **Метрики** (Prometheus + Grafana) | в Kubernetes, через роль Ansible `monitoring` (**по умолчанию выключен**, см. ниже) и локально через compose | графики запросов, ошибок, готовности подов, нагрузки |
| **Логи** (Loki + Promtail + Grafana) | локальный стек `docker-compose.logging.yml` | поиск по логам приложения и nginx, аудит входов |

> **Важно про ресурсы.** На ВМ 2 ГБ стек Prometheus/Grafana вместе с Patroni и web не помещается (нода уходит в swap и
> перестаёт отвечать). Поэтому `monitoring_enabled: false` в `ansible/group_vars/all.yml`. На демонстрацию: `make configure MONITORING=true`
> (лучше с большей ВМ или временно остановив часть нагрузки).

---

## 6.1. Откуда берутся метрики и логи в приложении

- **Метрики:** библиотека `prometheus-flask-exporter` добавляет эндпоинт `/metrics` (число и длительность запросов, статусы).
  Свои метрики приложения в `app/audit.py`: `classapp_login_attempts_total{result,channel}`, `classapp_user_actions_total{endpoint,status_class}`,
  `classapp_registrations_total`. Под gunicorn с несколькими воркерами метрики агрегируются через каталог `PROMETHEUS_MULTIPROC_DIR`
  (`gunicorn.conf.py`).
- **Логи:** приложение пишет JSON-строки в `/var/log/classapp/app.json.log` (поля `timestamp`, `level`, `message`, а для аудита ещё `event`,
  `ip`, `user_id`, `reason`, `status`); nginx пишет JSON-лог доступа в `access.json.log`. Оба каталога лежат на диске ВМ (hostPath).

---

## 6.2. Метрики в Kubernetes: роль `monitoring`

### `ansible/roles/monitoring/files/values.yaml` — настройки chart `kube-prometheus-stack`
| Блок | Что делает |
|---|---|
| заголовок | профиль «облегчённый» под ноду 2 vCPU / 2 ГБ |
| `defaultRules.create: false` | не создавать сотни стандартных правил оповещений (нагрузка на диск и CPU) |
| `alertmanager.enabled: false` | оповещения не нужны — экономия памяти |
| `kubeEtcd/kubeScheduler/kubeControllerManager/kubeProxy: enabled: false` | в K3s эти компоненты внутри одного процесса, отдельные цели недоступны |
| `grafana.enabled`, `admin.existingSecret: classapp-grafana` | Grafana включена; пароль админа берётся из секрета, а не хранится здесь |
| `grafana.service: NodePort 30300` | порт 30300 внутри ВМ (снаружи закрыт); нужен скрипту деплоя для аннотаций |
| `grafana.ini.server.root_url` + `serve_from_sub_path: true` | Grafana работает по адресу `/grafana/` (за nginx) |
| `grafana.resources` | запрос 50m CPU / 96 МБ, лимит 300m / 256 МБ |
| `livenessProbe` / `readinessProbe` | увеличенные задержки и таймауты: на слабой ВМ Grafana стартует долго, стандартные пробы убивали её в цикле |
| `prometheus.service: NodePort 30900` | доступ с самой ВМ (наружу не публикуется, нет авторизации; смотреть через `ssh -L 9090:127.0.0.1:30900`) |
| `prometheusSpec.serviceMonitorSelectorNilUsesHelmValues: false` (и для PodMonitor) | Prometheus подхватывает **любые** ServiceMonitor, а не только созданные самим chart |
| `scrapeInterval: 60s`, `retention: 2d`, `retentionSize: 2GB` | опрос раз в минуту, хранить 2 дня или 2 ГБ: экономия диска и CPU |
| `prometheusSpec.resources` | запрос 100m CPU / 200 МБ, лимит 400m / 384 МБ |
| `prometheusOperator`, `prometheus-node-exporter`, `kube-state-metrics` | ограничения ресурсов; node-exporter (метрики ноды) и kube-state-metrics (состояние объектов Kubernetes) нужны дашбордам |

### `ansible/roles/monitoring/files/classapp-monitoring.yaml` — построчно
| Строки | Что делает |
|---|---|
| 1–18 | **ServiceMonitor `classapp-web`** (в пространстве `monitoring`): «Prometheus, опрашивай Service с меткой `classapp-web` в `default`, порт `http`, путь `/metrics`, каждые 15 с» |
| 20–37 | **ServiceMonitor `classapp-patroni`**: то же для Patroni (порт `patroni-api`, `/metrics`) |
| 39–46 | **ConfigMap с дашбордом** `classapp-grafana-dashboard`. Метка `grafana_dashboard: "1"` — по ней sidecar Grafana находит и автоматически загружает дашборд |
| 47–63 | JSON дашборда «Classapp overview»: обновление 15 с; «аннотации» — вертикальные метки «Деплои» по тегу `deploy` (их ставит шаг 8 деплоя) |
| 64–137 | панели: запросов в секунду, доля 5xx, **готовые поды web и Patroni**, загрузка CPU ноды, попытки входа (успех/неудача), действия пользователей по разделам, p95 времени ответа, регистрации за 24 часа |

Формулы PromQL: `rate(...[5m])` — скорость роста счётчика за 5 минут; `histogram_quantile(0.95, ...)` — 95-й процентиль времени ответа;
`increase(...)` — прирост за период.

---

## 6.3. Локальный стек метрик и правил (docker-compose)

| Файл | Что делает |
|---|---|
| `monitoring/prometheus.yml` | `scrape_interval: 15s`; подключает файл правил `alert.rules.yml`; цель — `web:8000/metrics` |
| `monitoring/alert.rules.yml` | четыре правила: **InstanceDown** (приложение недоступно > 2 мин, `critical`), **HighErrorRate** (доля 5xx > 5% 5 мин), **LoginBruteForceSuspected** (> 15 неудачных входов за 5 мин — возможен подбор пароля), **HighLatencyP95** (p95 > 1.5 с 10 мин) |

Правила используются локальным compose-стеком; в Kubernetes `defaultRules` и Alertmanager выключены.

---

## 6.4. Логи: Loki + Promtail (локальный стек)

### `docker-compose.logging.yml`
Три сервиса: **Loki** (хранилище логов, порт 3100), **Promtail** (читает файлы логов с диска и отправляет в Loki; монтирует
`/var/log/classapp` и `/var/log/nginx` в режиме «только чтение» и свой конфиг), **Grafana** (порт 3000, подключаются
`provisioning/` и каталог дашбордов).

### `promtail-config.yml` — построчно
| Строки | Что делает |
|---|---|
| 1–3 | свой HTTP-порт 9080; gRPC выключен |
| 5–6 | файл `positions` — где Promtail остановился в каждом файле (чтобы не читать заново) |
| 8–9 | куда отправлять: `http://loki:3100/loki/api/v1/push` |
| 12–19 | задание **flask-app**: читает `app.json.log`; метки `job`, `service` |
| 20–32 | этап `json`: вытаскивает поля JSON (`timestamp`, `level`, `message`, `event`, `ip`, `user_id`, `status` и др.) |
| 33–35 | делает **метками** только `level` и `event` (мало значений — Loki не любит метки с большим числом уникальных значений) |
| 36–41 | берёт время записи из поля `timestamp` (несколько допустимых форматов) |
| 42–47 | для обычных записей (без `event`) в Loki кладётся только текст сообщения; **аудит-события остаются полным JSON**, чтобы можно было искать по `ip` и `user_id` |
| 49–70 | задание **nginx-web**: читает `access.json.log`; поля `status`, `request_method`, `request_uri`, `remote_addr`, `upstream_response_time`; метками становятся `status` и `method` |

### Каталог `provisioning/` — автоматическая настройка Grafana
| Файл | Что делает |
|---|---|
| `datasources/loki.yml` | подключает источник данных Loki (`http://loki:3100`, по умолчанию, только для чтения) |
| `dashboards/dashboards.yml` | говорит Grafana загружать дашборды-файлы из `/var/lib/grafana/dashboards`, класть в папку «ClassApp», обновлять каждые 10 с |
| `dashboards_json/classapp_overview.json` | «ClassApp: Обзор» — запросы, ошибки 5xx, p95, активные пользователи, входы за сутки, трафик по статусам, самые посещаемые страницы, самые активные пользователи, ошибки приложения |
| `dashboards_json/classapp_audit.json` | «ClassApp Audit» — успешные и неудачные входы, неудачные входы по IP (поиск подбора пароля), события входа/выхода/регистрации, действия пользователей |
| `dashboards_json/classapp_dashboard.json` | «ClassApp Error Monitoring» — ошибки Flask, nginx 500 и 502, тренд ошибок и потоки логов ошибок |

---

## 6.5. Кратко: как проверить, что наблюдаемость работает

- Метрики приложения: открыть `/metrics` (в кластере — внутри ВМ) и найти `classapp_login_attempts_total`.
- Grafana в Kubernetes (если включена): `http://<IP>/grafana/`, пользователь `admin`, пароль в секрете `classapp-grafana`
  (`kubectl -n monitoring get secret classapp-grafana -o jsonpath='{.data.admin-password}' | base64 -d`).
- Prometheus: `ssh -L 9090:127.0.0.1:30900 ubuntu@<IP>` и открыть `http://localhost:9090`.
- Метка деплоя на графиках: ставится шагом 8 `deploy-steps.sh` автоматически.
