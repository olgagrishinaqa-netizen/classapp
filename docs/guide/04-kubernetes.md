# 4. Kubernetes (папка `k8s/`)

**Что это.** K3s — лёгкий Kubernetes на одной ВМ. Манифесты — YAML-описания «что должно работать»; Kubernetes сам
запускает, перезапускает и подключает контейнеры. Применяются командой `kubectl apply -f` (шагами в `deploy-steps.sh`) либо
`kubectl apply -k k8s/` (через `kustomization.yaml`).

## Как всё связано

```
браузер -> :80 (hostPort) -> nginx (под) --/--------> classapp-web-service -> web (2 пода, gunicorn)
                                         --/grafana/-> Grafana (если мониторинг включён)
web --> classapp-db-master (Service) --> Patroni (под, роль master) --> диск ВМ (PVC)
Patroni <--> etcd-service (кто лидер)
```

> **Про номера строк.** Таблицы ниже составлены до добавления блоков `securityContext` (см. раздел «Усиление безопасности подов»). В манифестах `classapp-web`, `classapp-nginx`, `migrate-job` и `etcd` реальные номера строк теперь на 5–25 больше; ориентируйтесь на описание блока, а не на номер.

**Общие приёмы во всех манифестах:**
- `apiVersion`/`kind` — тип объекта; `metadata.name`/`namespace`/`labels` — имя, пространство имён (`default`) и метки.
- `app.kubernetes.io/name` — метка, по которой Service находит поды (`selector`).
- `tolerations` — разрешение запускаться на мастер-ноде (на одной ноде иначе поды «не поместились бы»).
- `resources.requests` — сколько ресурсов резервируется; `limits` — потолок (превысил память — контейнер убивается).
- `readinessProbe` — «готов принимать трафик?»; `livenessProbe` — «жив? если нет — перезапустить».
- `secretKeyRef` — значение берётся из секрета `classapp-secrets`, а не лежит в манифесте.

---

## `kustomization.yaml`
| Строки | Что делает |
|---|---|
| 1–3 | `Kustomization`, пространство имён `default` для всего |
| 5–12 | список ресурсов: etcd, services, patroni, migrate-job, web, nginx, hpa |
| 14–27 | комментарий: полный стек собран, чтобы `kubectl apply -k k8s/` был самостоятельным способом развернуть всё |
| 28–30 | `images`: подмена образа `ghcr.io/.../classapp` на тег `newTag`. В деплое `sed` заменяет `latest` на `main-<sha>` |

## `etcd.yaml` — хранилище для Patroni
| Строки | Что делает |
|---|---|
| 1–8 | Deployment `etcd` |
| 10 | 1 реплика (одна нода) |
| 11–13 | стратегия `Recreate`: сначала удалить старый под, потом создать новый (два etcd на одних данных не нужны); `progressDeadlineSeconds: 180` — считать неудачей, если за 3 минуты не готов |
| 23–29 | tolerations |
| 31–33 | контейнер `bitnamilegacy/etcd:3.5.11` |
| 34–52 | настройки через переменные окружения: без аутентификации (внутри кластера), имя узла, адреса клиентов (`http://etcd-service:2379`) и пиров |
| 53–59 | порты 2379 (клиенты) и 2380 (пиры) |
| 60–67 | readiness: `GET /health` |
| 68–74 | ресурсы: 50m CPU / 64 МБ, лимит 200m / 128 МБ |
| 76–92 | Service `etcd-service` (ClusterIP): постоянный адрес `etcd-service:2379` для Patroni |

## `services.yaml` — адреса базы данных
Два Service. Они выбирают под **по метке роли**, которую выставляет sidecar Patroni:
- `classapp-db-master` -> под с меткой `patroni-role: master`. Сюда ходит приложение, при смене лидера адрес не меняется;
- `classapp-db-replica` -> поды с `patroni-role: replica` (для чтения).

## `patroni.yaml` — PostgreSQL с автоматическим переключением
| Строки | Что делает |
|---|---|
| 1–8 | ServiceAccount `classapp-patroni` — «учётная запись» подов для доступа к API Kubernetes |
| 10–31 | Role: разрешает читать и менять `pods`, `endpoints`, `services` (нужно Patroni и sidecar для определения лидера и меток) |
| 33–48 | RoleBinding: привязывает роль к ServiceAccount |
| 50–70 | headless Service `classapp-patroni` (`clusterIP: None`): стабильные DNS-имена подов StatefulSet; порты 5432 (PostgreSQL) и 8008 (API Patroni) |
| 72–81 | StatefulSet `classapp-patroni` |
| 82 | `replicas: 1` — на одной ноде реплика на том же диске отказоустойчивости не даёт. Для демонстрации failover поднимают 3 ноды и 2 реплики |
| 83–85 | `OrderedReady` и `RollingUpdate`: поды запускаются и обновляются по одному |
| 91–94 | метки пода; `patroni-role: replica` — стартовое значение, sidecar потом выставит реальное |
| 96 | использует ServiceAccount из строк 1–8 |
| 104–118 | **initContainer** `fix-data-dir-perms`: до старта Postgres создаёт каталог данных и отдаёт его пользователю `postgres` (uid 101). Без этого Postgres не смог бы писать на том, созданный от root |
| 119–128 | основной контейнер: образ Zalando **Spilo** (PostgreSQL 15 + Patroni) |
| 129–138 | `SCOPE`, `NAMESPACE`, `ETCD_HOSTS` — идентификатор кластера в etcd и адрес etcd. **Должны быть одинаковыми на всех подах, иначе «split-brain»** |
| 139–146 | `PGDATA` — каталог данных **внутри смонтированного тома**, иначе данные терялись бы при пересоздании пода |
| 147–165 | пароли суперпользователя, репликации — из секрета |
| 166–173 | имя и пространство имён пода (downward API) |
| 174–183 | порты 5432 и 8008; том данных монтируется в `/data` |
| 184–202 | пробы: готовность через `/health` с задержкой 60 с, живость через `/liveness` с задержкой 90 с (первая инициализация БД долгая) |
| 203–209 | ресурсы: 100m CPU / 128 МБ, лимит 400m / 256 МБ |
| 210–249 | **sidecar `role-labeler`**: каждые 10 с спрашивает API Patroni «кто я: leader или replica?» и вешает на под метку `patroni-role=master/replica`. По этой метке Service `classapp-db-master` находит лидера |
| 250–261 | `volumeClaimTemplates`: каждому поду выделяется постоянный том 10 ГБ (`patroni-data`), данные переживают перезапуск пода |

## `migrate-job.yaml` — миграции Alembic
| Строки | Что делает |
|---|---|
| 1–8 | Job `classapp-migrate` — одноразовая задача |
| 11–12 | `ttlSecondsAfterFinished: 3600` — завершённый Job и логи хранятся час; `backoffLimit: 4` — до 4 повторов при ошибке |
| 19 | `restartPolicy: Never` — ошибочный под не перезапускается на месте, Job создаёт новый |
| 27–52 | **initContainer** `db-ready-check`: ждёт, пока PostgreSQL ответит (`pg_isready`), затем идемпотентно создаёт БД `classapp` (Spilo сам её не создаёт) |
| 53–61 | контейнер из образа приложения выполняет `alembic upgrade head` |
| 62–83 | переменные: `DATABASE_URL` и др. из секрета |

## `classapp-web.yaml` — приложение
| Строки | Что делает |
|---|---|
| 1–13 | Deployment `classapp-web`; `replicas: 2` — две реплики, между ними nginx/Service распределяет запросы |
| 27–35 | initContainer: отдаёт каталоги логов и загрузок пользователю с uid 1000 (`appuser`), иначе приложение не сможет туда писать |
| 37–39 | образ из GHCR (тег подменяется при деплое), `IfNotPresent` — не скачивать, если уже есть |
| 40 | запуск `gunicorn -w 1` (один воркер на под: экономия памяти на 2 ГБ) |
| 41–78 | переменные окружения: адрес БД, пароль, секретный ключ — из секрета; `ADMIN_PHONE`/`ADMIN_PASSWORD` — из секрета (необязательные, `optional: true`); `APP_JSON_LOG_PATH`, `UPLOAD_FOLDER=/uploads` |
| 79–82 | порт 8000 |
| 83–89 | ресурсы: 100m CPU / 128 МБ, лимит 500m / 256 МБ |
| 90–94 | монтируются каталоги логов и загрузок |
| 95–110 | пробы `/healthz`: готовность (с 10 с) и живость (с 30 с) |
| 111–119 | тома: каталоги **на диске ВМ** (`hostPath`): `/var/log/classapp` и `/var/lib/classapp/uploads`. Загрузки и чеки лежат на ВМ, их же архивирует бэкап |
| 120–137 | Service `classapp-web-service` (ClusterIP, порт 8000): единый адрес для всех реплик и балансировка |

## `classapp-nginx.yaml` — единственная точка входа
| Строки | Что делает |
|---|---|
| 1–10 | ConfigMap `classapp-nginx-config` — конфиг nginx как данные (с строки 10 начинается сам `nginx.conf`) |
| 11–13 | `worker_processes auto` — по числу ядер; журнал ошибок и pid-файл |
| 15–17 | блок `events`: до 1024 соединений на воркер |
| 23–32 | JSON-формат лога доступа (читает Promtail): время, IP, метод, URI, статус, размер, время ответа upstream, и запись его в `access.json.log` |
| 33–35 | `sendfile`, `keepalive_timeout 65`, `client_max_body_size 20m` — лимит загружаемого файла |
| 38–41 | `resolver 10.43.0.10` — DNS кластера (CoreDNS); адрес Grafana в переменной, чтобы nginx стартовал, даже если мониторинга ещё нет |
| 43–46 | `map` — служебная настройка для WebSocket (Grafana) |
| 48–49 | `server { listen 8080; }` — внутри контейнера слушает 8080 |
| 52–54 | `/grafana` -> перенаправление на `/grafana/` |
| 56–68 | `location /grafana/` — проксирует в Grafana, передавая реальные адрес клиента и протокол |
| 69–79 | **`location /`** — проксирует всё остальное на `classapp-web-service:8000`. Здесь «nginx распределяет запросы»: `/` в приложение, `/grafana/` в Grafana |
| 83–111 | Deployment `classapp-nginx`: **1 реплика** и стратегия `Recreate`, потому что порт 80 хоста может занять только один под (строки сдвинуты из-за блока `securityContext`) |
| 113–115 | образ `nginx:1.25-alpine` |
| 116–123 | порт `containerPort: 8080` и **`hostPort: 80`**: внешний порт 80 ВМ пробрасывается прямо в под. **Это и есть «один порт снаружи»** |
| 124–130 | ресурсы: 50m CPU / 32 МБ, лимит 200m / 64 МБ |
| 131–136 | монтирование конфига из ConfigMap (`subPath` — подменяет один файл) и каталога логов |
| 137–144 | проба готовности: `GET /` |
| 145–150 | тома: ConfigMap и временный `emptyDir` для логов |
| 151–169 | Service `classapp-nginx` (NodePort 30080): внутренний путь для проверок деплоя (`curl 127.0.0.1:30080/healthz`); снаружи порт закрыт security group |

## `hpa.yaml` — автомасштабирование
HorizontalPodAutoscaler следит за средней загрузкой CPU подов `classapp-web` и держит от **2 до 3 реплик**; добавляет реплику,
если загрузка выше 70% от `requests` (`averageUtilization: 70`). Метрики даёт `metrics-server`, встроенный в K3s.

---

## Усиление безопасности подов (`securityContext`)

Сканер Trivy в CI блокирует манифесты с уровнем HIGH, поэтому все поды, образами которых мы управляем, работают по принципу наименьших привилегий.

| Что | Где задано | Смысл |
|---|---|---|
| `runAsNonRoot: true`, `runAsUser: 1000` (web, migrate), `101` (nginx), `1001` (etcd) | уровень пода | процесс не может быть root |
| `seccompProfile: RuntimeDefault` | уровень пода | ядро блокирует опасные системные вызовы |
| `allowPrivilegeEscalation: false` | каждый контейнер | нельзя получить больше прав, чем у процесса |
| `capabilities.drop: [ALL]` | каждый контейнер | у контейнера нет специальных привилегий Linux |
| `readOnlyRootFilesystem: true` | web, nginx, migrate | корневая ФС только для чтения; писать можно только в явно примонтированные тома (`/tmp`, логи, загрузки, кэш nginx) |
| initContainer `fix-log-dir-perms` | web | **единственное исключение**: ему нужен root только чтобы отдать каталоги пользователю 1000; права урезаны до одной capability `CHOWN` |

Тома `emptyDir` для `/tmp` (web, nginx) и `/var/cache/nginx` существуют из-за read-only корня. CI проверяет это дымовым тестом: образ запускается
с `--read-only --cap-drop ALL --user 1000`, то есть с теми же ограничениями.

**nginx и стратегия `Recreate`.** Порт 80 хоста занимается через `hostPort`; пока старый под жив, новый не может запуститься (порт занят),
поэтому при обычном `RollingUpdate` раскатка зависла бы. Для nginx выбрано `Recreate` (сначала остановить, затем запустить; пауза в секунды).

**Что не усилено и почему** (обосновано в `.trivyignore.yaml`): Patroni/Spilo стартует от root и пишет в корневую ФС; у etcd (bitnami) entrypoint пишет конфиг при
старте; `hostPort` у nginx — единственная публичная точка входа.

## Секреты (не лежат в репозитории)
`classapp-secrets` в `default` содержит `db-password`, `secret-key`, `admin-phone`, `admin-password`, `database-url`. Создаётся один раз
ролью Ansible `bootstrap_secrets`; на шаге 4 деплоя `database-url` пересобирается из `db-password`. Посмотреть значение (на ВМ):
`sudo kubectl get secret classapp-secrets -o jsonpath='{.data.admin-password}' | base64 -d`.

## Типичные команды (на ВМ, с `sudo`)
```
kubectl get pods -A                      все поды
kubectl logs deploy/classapp-web         логи приложения
kubectl describe pod <имя>               события и причины сбоев
kubectl rollout undo deployment/classapp-web   откат на предыдущую версию
kubectl get endpoints classapp-db-master       есть ли лидер БД
```
