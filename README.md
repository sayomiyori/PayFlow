# PayFlow

Multi-tenant payment platform with outbox-driven events, Celery background jobs, and analytics.

## Architecture (logical)

```text
                         +----------------------+
                         |      Nginx Ingress   |
                         +----------+-----------+
                                    |
                                    v
+---------------------+    +--------------------+    +----------------------+
|     Clients/API     +--->|   FastAPI (API)    +--->|   PostgreSQL (OLTP)  |
+---------------------+    +----------+---------+    +----------------------+
                                      |
                                      | Outbox Pattern
                                      v
                              +--------------------+
                              |       Kafka        |
                              |   payments.events  |
                              +----+----------+----+
                                   |          |
                                   |          v
                                   |   +------------------+
                                   |   | ClickHouse Sink  |
                                   |   +--------+---------+
                                   |            |
                                   |            v
                                   |   +------------------+
                                   |   |   ClickHouse     |
                                   |   |   Analytics DB   |
                                   |   +--------+---------+
                                   |            |
                                   |            v
                                   |   +------------------+
                                   |   | Analytics API    |
                                   |   +------------------+
                                   |
                                   v
                            +---------------+
                            | Celery Worker |
                            +-------+-------+
                                    |
                                    v
                            +---------------+
                            | Celery Beat   |
                            +---------------+
```

## Architecture (Kubernetes)

```text
                    Internet
                        |
                        v
               +-----------------+
               | Ingress (TLS)   |
               |  nginx class    |
               +--------+--------+
                        |
                        v
               +-----------------+       +------------------+
               | Service :80     |------>| payflow-api      |
               | ClusterIP       |       | Deployment x3    |
               +-----------------+       | HPA 2..10 @70% |
                        |                 +--------+-------+
                        |                          |
                        v                          v
               +------------------+        +------------------+
               | ConfigMap        |        | Secret           |
               | (non-secret env) |        | DB/Redis/JWT...  |
               +------------------+        +------------------+

        +------------------+    +------------------+
        | celery-worker    |    | celery-beat      |
        | Deployment x2    |    | Deployment x1    |
        | concurrency=4    |    | single scheduler |
        +------------------+    +------------------+
```

## Local setup (3 commands)

```bash
make docker-up
make migrate
make dev
```

- API: `http://localhost:8088/docs`
- Kafka UI: `http://localhost:8080`
- Prometheus: `http://localhost:9090`

## Outbox pattern

PayFlow commits **payment row** and **outbox event** in one DB transaction so OLTP and Kafka publication cannot diverge.

```text
  Client                    PostgreSQL (tenant schema)
    |                                |
    | POST /payments                 |
    v                                v
+------------+              +---------------------------+
| FastAPI    |  BEGIN       | INSERT payments           |
| handler    +------------->| INSERT outbox (created)   |
+------------+              +---------------------------+
    |                                |
    |                                | COMMIT
    v                                v
+------------+              +---------------------------+
| HTTP 201   |              | durable on disk           |
+------------+              +---------------------------+
                                       |
                                       v
                            +----------------------+
                            | Celery: outbox task  |
                            | SKIP LOCKED batch    |
                            +----------+-----------+
                                       |
                         publish Kafka  +  mark processed
                                       v
                            +----------------------+
                            | Kafka topic          |
                            +----------------------+
```

## Kubernetes (`k8s/`)

Применение через **Kustomize** (порядок ресурсов фиксирован в `kustomization.yaml`):

| Файл | Назначение |
|------|------------|
| `kustomization.yaml` | Список ресурсов и namespace |
| `namespace.yaml` | Namespace `payflow` |
| `configmap.yaml` | Несекретные переменные (`ENVIRONMENT`, `KAFKA_*`, ClickHouse host, …) |
| `secret.yaml` | `stringData`: `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`, `SECRET_KEY`, ключи ЮKassa (замените перед продом) |
| `api-deployment.yaml` | API: **3** реплики, CPU/memory requests & limits, **readiness** `GET /health` каждые **10s**, **liveness** каждые **30s**, `envFrom` ConfigMap+Secret |
| `api-service.yaml` | `ClusterIP` :80 → pod **8088** |
| `api-ingress.yaml` | **Ingress NGINX** (`ingressClassName: nginx`) + **TLS** (секрет `payflow-api-tls`; при cert-manager раскомментируйте аннотацию в манифесте) |
| `celery-worker-deployment.yaml` | **2** реплики, `celery worker --concurrency=4` |
| `celery-beat-deployment.yaml` | **1** реплика, `celery beat`, стратегия `Recreate` |
| `hpa.yaml` | **HPA** для API: min **2**, max **10**, CPU **70%** |

Образ по умолчанию: `ghcr.io/sayomiyori/payflow:latest` (см. CI `build`). В кластере должны существовать сервисы Postgres / Redis / Kafka / ClickHouse с DNS из ConfigMap/Secret или поправьте значения.

### Make targets

```bash
make k8s-deploy   # kubectl apply -k k8s/
make k8s-status   # kubectl get all -n payflow
make k8s-logs     # kubectl logs -f deployment/payflow-api -n payflow
```

## CI/CD (GitHub Actions)

Файл: `.github/workflows/ci.yml`

```text
on: push main | pull_request
              |
              v
       +-------------+
       |    lint     |  ruff check + ruff format --check
       |             |  mypy --strict -p app
       +------+------+
              |
              v
       +-------------+
       |    test     |  services: Postgres, Redis, Kafka
       |             |  pytest --cov=app --cov-fail-under=80
       +------+------+  (покрытие по всему `app/`: unit + integration, порог 80%)
              |
              v
       +-------------+
       |   build     |  docker buildx → GHCR
       +------+------+
              |  (только main)
              v
       +-------------+
       |   deploy    |  kubectl apply -k k8s/
       |  (optional) |  пропуск, если secret KUBE_CONFIG пуст
       +-------------+
```

Локальная сборка образа:

```bash
docker build -t payflow:local .
```

## Screenshots (Grafana / Kafka UI)

Добавьте PNG в `docs/screenshots/` (см. `docs/screenshots/README.md`), затем вставьте в этот README, например:

```markdown
![Grafana — PayFlow overview](docs/screenshots/grafana-dashboard.png)
![Kafka UI — topics](docs/screenshots/kafka-ui-topics.png)
```

Пока файлов нет, блок выше можно не включать — CI от скриншотов не зависит.
