# Troubleshooting: Patroni HA в Kubernetes

## Типичные проблемы и решения

### 1. "Neither srv, hosts, host nor url are defined in etcd section of config"

**Симптомы:**
```
Exception: Neither srv, hosts, host nor url are defined in etcd section of config
```

**Причина:**
Patroni (образ Zalando Spilo) не может найти конфигурацию для подключения к etcd.
Для этого образа Spilo (`registry.opensource.zalan.do/acid/spilo-15:3.0-p1`) DCS-настройки
считываются bootstrap-скриптом `configure_spilo.py` из переменных вида `ETCD_HOST`,
`ETCD_HOSTS`, `ETCD3_HOSTS` и т.п. — **без** префикса `PATRONI_`.
Скрипт буквально делает разбор по первому символу `_`, поэтому:
- `ETCD_HOSTS` → распознаётся как секция `etcd`;
- `PATRONI_ETCD_HOSTS` → распознаётся как секция `patroni` и игнорируется;
- `PATRONI_ETCD3_HOSTS` → тоже не попадает в секцию `etcd`.

Из-за этого в итоговом `patroni.yaml` секция `etcd` оставалась пустой, и Patroni
падал с ошибкой `Neither srv, hosts, host nor url are defined in etcd section of config`.
Правильная переменная для данного образа — `ETCD_HOSTS=etcd-service:2379`.

**Решение:**
1. Проверьте переменные окружения в поде:
```bash
kubectl exec -it pod/classapp-patroni-0 -c patroni -- env | grep PATRONI_ETCD
```
   Должна быть установлена именно `ETCD_HOSTS=etcd-service:2379`
   (а не `PATRONI_ETCD_HOSTS` или `PATRONI_ETCD3_HOSTS`).

2. Убедитесь, что `SCOPE` и `NAMESPACE` **одинаковы** на всех подах StatefulSet —
   иначе новый под создаст отдельный кластер в etcd вместо присоединения к
   существующему мастеру (split-brain). Для образа Zalando Spilo эти имена
   читаются именно так, а `PATRONI_SCOPE` / `PATRONI_NAMESPACE` игнорируются на
   этапе генерации Patroni config:
```bash
kubectl get pods -l app.kubernetes.io/name=patroni -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.containers[0].env[?(@.name=="SCOPE")].value}{" / "}{.spec.containers[0].env[?(@.name=="NAMESPACE")].value}{"\n"}{end}'
```

3. Проверьте доступность etcd-сервиса:
```bash
kubectl exec -it pod/classapp-patroni-0 -c patroni -- nc -zv etcd-service 2379
```

4. Если манифест изменился, переприменените его и пересоздайте под (StatefulSet
   не всегда перезапускает уже существующий под только из-за смены env var в
   рамках одного и того же `kubectl apply`):
```bash
kubectl apply -f k8s/patroni.yaml
kubectl delete pod classapp-patroni-0 classapp-patroni-1 --ignore-not-found
```

### 1.1. `Unable to change service endpoints ... is forbidden` / RBAC для Kubernetes Endpoints

**Симптомы:**
```
Warning: Unable to change service endpoints: ... endpoints "classapp-ha" is forbidden: User "system:serviceaccount:default:classapp-patroni" cannot patch resource "endpoints" in API group "" in the namespace "default"
```

**Причина:**
Patroni должен иметь доступ к Kubernetes API для обновления `endpoints` и `services`,
чтобы leader/replica могли правильно маршрутизировать трафик. Если `Role` для
ServiceAccount `classapp-patroni` не включает `endpoints`, то лидер стартует, но второй
pod не присоединяется корректно.

**Решение:**
Убедитесь, что в `k8s/patroni.yaml` Role содержит `endpoints` (и желательно `services`):
```yaml
rules:
  - apiGroups:
      - ""
    resources:
      - pods
      - pods/proxy
      - endpoints
      - services
    verbs:
      - get
      - list
      - watch
      - patch
      - update
```

После правки:
```bash
kubectl apply -f k8s/patroni.yaml
kubectl rollout restart statefulset/classapp-patroni -n default
kubectl rollout status statefulset/classapp-patroni -n default --timeout=300s
```

---

### 2. Pods зависают с "ImagePullBackOff"

**Симптомы:**
```
classapp-patroni-1   0/2     ImagePullBackOff   1 (22h ago)   37h
```

**Причина:**
Образ PostgreSQL-HA недоступен на registry. Это неоднократно происходило с
образами Bitnami (Legacy) из-за архивации/rate-limit registry:
- `bitnami/postgresql-ha:15.6.0-debian-11-r0` (устаревший, удалён)
- `bitnamilegacy/postgresql-ha:15.8.0-debian-12-r22` (тоже периодически недоступен)

**Решение:**
Начиная с текущей версии манифеста используется образ **Zalando Spilo**
(`registry.opensource.zalan.do/acid/spilo-15:3.0-p1`) — это надежный, широко
используемый в продакшене образ (основа Zalando Postgres Operator), который не
зависит от нестабильного bitnamilegacy registry:
```yaml
# В k8s/patroni.yaml:
image: registry.opensource.zalan.do/acid/spilo-15:3.0-p1
imagePullPolicy: IfNotPresent
```

1. Проверьте доступность образа на ноде:
```bash
sudo k3s crictl pull registry.opensource.zalan.do/acid/spilo-15:3.0-p1
```

2. Если вы используете приватный registry, убедитесь, что ImagePullSecret правильно настроен:
```bash
kubectl get secrets -o name | grep -i docker
```

---

### 3. StatefulSet не становится Ready

**Симптомы:**
```
kubectl get statefulset classapp-patroni
# OUTPUT:
# DESIRED   CURRENT   READY   AGE
# 2         1         0       5m
```

**Причина:**
- Первый pod ещё инициализирует БД (может занимать 1-2 минуты)
- Readiness probe может быть слишком агрессивной (низкое `initialDelaySeconds`)
- Недостаточно памяти на ноде для двух pod'ов

**Решение:**
1. Дождитесь инициализации (может занять несколько минут):
```bash
kubectl rollout status statefulset/classapp-patroni --timeout=300s
```

2. Проверьте логи первого pod'а:
```bash
kubectl logs classapp-patroni-0 -c patroni --tail=100
```

3. Если pod никогда не становится Ready, проверьте readiness probe:
```bash
kubectl get pod classapp-patroni-0 -o yaml | grep -A 20 "readinessProbe:"
```

4. Убедитесь, что достаточно памяти:
```bash
kubectl describe node | grep -A 5 "Allocated resources"
```

---

### 3.1. StatefulSet "застрял": pod-0 работает на старом образе, pod-1 не может обновиться

**Симптомы:**
```
classapp-patroni-0   1/1   Running                 ...   controller-revision-hash=classapp-patroni-84964f97ff
classapp-patroni-1   0/2   Init:ImagePullBackOff   ...   controller-revision-hash=classapp-patroni-5dc449c8f
```
Два pod'а с разными `controller-revision-hash` — значит, StatefulSet обновляет
поды по одному, начиная со старшего ordinal, и не переходит к следующему, пока
текущий не станет Ready.

**Причина:**
`updateStrategy: RollingUpdate` обновляет pod'ы по убыванию номера (сначала
`-1`, потом `-0`). Если `classapp-patroni-1` не может стартовать (например,
`ImagePullBackOff`), контроллер никогда не тронет `classapp-patroni-0` — тот
остаётся на старой версии манифеста/образа сколь угодно долго.

**Решение:**
1. Сначала устраните первопричину (недоступный образ, ошибка конфигурации) —
   см. пункты выше. После того как `classapp-patroni-1` станет `1/2` → `2/2`
   Ready, обновление автоматически продолжится и pod-0 будет пересоздан.

2. Проверить прогресс:
```bash
kubectl get pods -l app.kubernetes.io/name=patroni -w
kubectl rollout status statefulset/classapp-patroni --timeout=180s
```

3. Если нужно принудительно пересоздать зависший старый pod (например, для
   диагностики), удалите его вручную — StatefulSet пересоздаст его с новым
   revision:
```bash
kubectl delete pod classapp-patroni-0
```
   ⚠️ Делайте это только когда `classapp-patroni-1` уже здоров (Ready) и
   является репликой/мастером — иначе кластер на короткое время останется
   без единого работающего пода.

---

### 4. classapp-db-master Service не имеет endpoints

**Симптомы:**
```bash
kubectl get endpoints classapp-db-master
# OUTPUT:
# NAME                   ENDPOINTS     AGE
# classapp-db-master     <none>        10m
```

**Причина:**
- Pod'ы не получают label `patroni-role=master` от role-labeler sidecar
- Patroni API (`/health`) недоступен для role-labeler
- etcd недоступен для Patroni (см. выше)

**Решение:**
1. Проверьте labels на pod'ах:
```bash
kubectl get pods -l app.kubernetes.io/name=patroni --show-labels
```

2. Проверьте логи role-labeler sidecar:
```bash
kubectl logs classapp-patroni-0 -c role-labeler --tail=100
```

3. Проверьте доступность Patroni API внутри pod'а:
```bash
kubectl exec -it pod/classapp-patroni-0 -c patroni -- \
  wget -qO- http://127.0.0.1:8008 | jq .role
```

4. Если API возвращает ошибку, это означает, что Patroni не полностью инициализирован.
   Дождитесь готовности pod'а и повторите.

---

### 5. Flask web pods не могут подключиться к БД

**Симптомы:**
```
ERROR: psycopg2.OperationalError: could not translate host name "classapp-db-master" to address
```

**Причина:**
- DNS не разрешает имя сервиса Patroni
- Pod'ы находятся в другом namespace'е
- classapp-db-master Service не имеет endpoints

**Решение:**
1. Проверьте DNS разрешение из pod'а:
```bash
kubectl exec -it pod/classapp-web-xxx -- nslookup classapp-db-master
kubectl exec -it pod/classapp-web-xxx -- nslookup classapp-db-master.default.svc.cluster.local
```

2. Проверьте, что web pods находятся в том же namespace:
```bash
kubectl get pods -A -l app.kubernetes.io/name=web
```

3. Убедитесь, что classapp-db-master имеет endpoints (см. проблему #4)

4. Проверьте environment переменные в web pod'е:
```bash
kubectl exec -it pod/classapp-web-xxx -- env | grep DATABASE_URL
```

---

### 6. Etcd pod падает или недоступен

**Симптомы:**
```bash
kubectl get pod -l app.kubernetes.io/name=etcd
# STATUS: CrashLoopBackOff или Pending
```

**Причина:**
- Недостаточно ресурсов (memory 64Mi может быть мало)
- Конфликт портов (2379, 2380)
- Корруптированные данные etcd

**Решение:**
1. Проверьте логи etcd:
```bash
kubectl logs -l app.kubernetes.io/name=etcd --tail=100
```

2. Проверьте доступность портов:
```bash
kubectl exec -it pod/classapp-patroni-0 -- nc -zv etcd-service 2379
```

3. Если etcd повреждён, можно очистить его (потеря данных):
```bash
kubectl delete pvc --all  # если используются PVC
kubectl delete pod -l app.kubernetes.io/name=etcd
```

4. Увеличьте memory limit, если нужно:
```yaml
# В k8s/etcd.yaml:
resources:
  requests:
    memory: 128Mi  # увеличить
  limits:
    memory: 256Mi  # увеличить
```

---

### 7. Миграция БД (Alembic Job) не запускается

**Симптомы:**
```bash
kubectl get job classapp-migrate
# COMPLETIONS: 0/1  (зависает)
```

**Причина:**
- Migration Job ждёт, что БД будет готова (pg_isready)
- classapp-db-master endpoints пусты (см. проблему #4)
- Secret `classapp-secrets` не существует
- БД `classapp` ещё не создана (актуально для образа Spilo — он не создаёт
  прикладную БД автоматически, в отличие от bitnami-образов)

**Решение:**
1. Проверьте статус Job:
```bash
kubectl describe job classapp-migrate
kubectl logs job/classapp-migrate
```

2. Убедитесь, что classapp-db-master имеет endpoints:
```bash
kubectl get endpoints classapp-db-master
```

3. Проверьте наличие Secret:
```bash
kubectl get secret classapp-secrets
kubectl get secret classapp-secrets -o yaml
```

4. Если Secret отсутствует, создайте его:
```bash
kubectl create secret generic classapp-secrets \
  --from-literal=db-password='CHANGE_ME' \
  --from-literal=secret-key='CHANGE_ME' \
  --from-literal=admin-phone='79990000000' \
  --from-literal=admin-password='CHANGE_ME'
```

5. Проверьте, что БД `classapp` существует (initContainer `db-ready-check`
   в `k8s/migrate-job.yaml` создаёт её автоматически, но можно проверить вручную):
```bash
kubectl exec -it classapp-patroni-0 -c patroni -- \
  psql -U postgres -c "\l" | grep classapp
```

5. Запустите Job снова после устранения проблем:
```bash
kubectl delete job classapp-migrate
kubectl apply -f k8s/migrate-job.yaml
```

---

### 8. Prometheus/Grafana не видят метрики Patroni

**Симптомы:**
```
Grafana dashboard "Patroni DB" показывает "No data"
```

**Причина:**
- ServiceMonitor для Patroni не применён
- Patroni API /metrics не доступен (port 8008)
- Prometheus не имеет доступа к pod'ам

**Решение:**
1. Проверьте ServiceMonitor:
```bash
kubectl get servicemonitor -n monitoring
kubectl describe servicemonitor classapp-patroni -n monitoring
```

2. Проверьте доступность Patroni API:
```bash
kubectl port-forward svc/classapp-patroni 8008:8008
curl -s http://localhost:8008/metrics | head -20
```

3. Проверьте, что Prometheus scrape-конфиг включает Patroni:
```bash
kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n monitoring
# Откройте http://localhost:9090/targets в браузере
```

---

## Диагностические команды

### Быстрая проверка здоровья кластера:
```bash
# 1. Проверьте все pod'ы
kubectl get pods -A -w

# 2. Проверьте статусы Patroni
kubectl get statefulset classapp-patroni
kubectl get pods -l app.kubernetes.io/name=patroni --show-labels

# 3. Проверьте endpoints
kubectl get endpoints classapp-db-master classapp-db-replica

# 4. Проверьте etcd
kubectl get pod -l app.kubernetes.io/name=etcd

# 5. Проверьте secrets
kubectl get secret classapp-secrets

# 6. Посмотрите события
kubectl get events --sort-by='.lastTimestamp'
```

### Логирование:
```bash
# Patroni основной контейнер
kubectl logs -f classapp-patroni-0 -c patroni

# role-labeler sidecar
kubectl logs -f classapp-patroni-0 -c role-labeler

# etcd
kubectl logs -f -l app.kubernetes.io/name=etcd

# Web приложение
kubectl logs -f -l app.kubernetes.io/name=web

# Миграции
kubectl logs -f job/classapp-migrate

# Последние 20 событий кластера
kubectl get events --sort-by='.lastTimestamp' | tail -20
```

### Отладка подключения:
```bash
# Проверить DNS из pod'а
kubectl exec -it pod/classapp-web-xxx -- nslookup classapp-db-master

# Проверить доступность порта
kubectl exec -it pod/classapp-patroni-0 -- nc -zv classapp-db-master 5432

# Проверить Patroni API
kubectl exec -it pod/classapp-patroni-0 -- wget -qO- http://127.0.0.1:8008 | jq .

# Подключиться к БД напрямую
kubectl port-forward svc/classapp-db-master 5432:5432
psql -h localhost -U postgres -d classapp
```

---

## Восстановление после сбоев

### Если Patroni потерял кворум в etcd:
```bash
# 1. Удалите etcd pod и дайте ему переинициализироваться
kubectl delete pod -l app.kubernetes.io/name=etcd

# 2. Дождитесь, пока etcd станет Ready
kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=etcd --timeout=120s

# 3. Перезапустите Patroni pods
kubectl delete pod classapp-patroni-0 classapp-patroni-1

# 4. Дождитесь готовности и проверьте endpoints
kubectl rollout status statefulset/classapp-patroni --timeout=300s
kubectl get endpoints classapp-db-master
```

### Если все pod'ы потеряны:
```bash
# Переприменить все манифесты
kubectl apply -f k8s/etcd.yaml
kubectl apply -f k8s/patroni.yaml

# Дождаться готовности
kubectl rollout status statefulset/classapp-patroni --timeout=300s

# Проверить статус
kubectl get pods -l app.kubernetes.io/name=patroni --show-labels
kubectl get endpoints classapp-db-master
```

---

## Мониторинг состояния

### Рекомендуемые метрики для Prometheus:
- `patroni_info` — информация о Patroni node
- `patroni_postgres_running` — статус PostgreSQL
- `patroni_leader_ip` — IP текущего master node
- `pg_up` — доступность PostgreSQL
- `pg_database_size_bytes` — размер БД

### Рекомендуемые alerts:
```yaml
- alert: PatroniNoLeader
  expr: count(patroni_leader_info) == 0
  for: 1m
  annotations:
    summary: "Нет master node в Patroni кластере"

- alert: PostgresDown
  expr: pg_up == 0
  for: 1m
  annotations:
    summary: "PostgreSQL недоступна"

- alert: PatroniHighReplicationLag
  expr: pg_replication_lag_seconds > 60
  for: 5m
  annotations:
    summary: "Репликация отстаёт на {{ $value }} сек"
```

---

## Контакты и ресурсы

- Документация Patroni: https://patroni.readthedocs.io/
- Kubernetes документация: https://kubernetes.io/docs/
- etcd документация: https://etcd.io/docs/
- Bitnami PostgreSQL-HA: https://github.com/bitnami/charts/tree/main/bitnami/postgresql-ha
