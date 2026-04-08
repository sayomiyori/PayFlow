# PayFlow

Multi-tenant payment platform with outbox-driven events and real-time analytics.

## Architecture

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

## Local Setup (3 commands)

```bash
make docker-up
make migrate
make dev
```

API docs: `http://localhost:8088/docs`  
Kafka UI: `http://localhost:8080`  
Prometheus: `http://localhost:9090`

## Outbox Pattern

PayFlow writes business state (`payments`) and integration events (`outbox`) in one transaction.  
This guarantees no event loss between OLTP writes and Kafka publication.

```text
Client -> POST /payments
        -> DB Transaction:
           1) INSERT payments
           2) INSERT outbox (payment.created)
        -> COMMIT

Outbox Worker Loop:
  SELECT ... FOR UPDATE SKIP LOCKED
  -> publish to Kafka (payments.events)
  -> UPDATE outbox.processed = true
```

## Kubernetes Manifests

All production manifests are in `k8s/`:

- `namespace.yaml`
- `configmap.yaml`
- `secret.yaml`
- `api-deployment.yaml`
- `api-service.yaml`
- `api-ingress.yaml`
- `celery-worker-deployment.yaml`
- `celery-beat-deployment.yaml`
- `hpa.yaml`

## CI/CD

GitHub Actions workflow: `.github/workflows/ci.yml`

- `lint`: `ruff check` + `mypy --strict`
- `test`: `pytest` with PostgreSQL/Kafka/Redis services and coverage gate `>= 80%`
- `build`: Docker build + push to GHCR
- `deploy` (main only): `kubectl apply -f k8s/`

## Screenshots

Add your environment screenshots here:

- `docs/images/grafana-dashboard.png`
- `docs/images/kafka-ui-topics.png`

Example markdown:

```markdown
![Grafana Dashboard](docs/images/grafana-dashboard.png)
![Kafka UI Topics](docs/images/kafka-ui-topics.png)
```
