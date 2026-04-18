.PHONY: dev test lint migrate docker-up docker-down k8s-deploy k8s-status k8s-logs

# Запустить инфраструктуру (PostgreSQL, Redis, Kafka, ClickHouse)
docker-up:
	docker-compose up -d
	@echo "Waiting for services to be ready..."
	@timeout /t 5 /nobreak > NUL || sleep 5
	@docker-compose ps

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

consumer-up:
	docker-compose up -d clickhouse-consumer

prometheus-up:
	docker-compose up -d prometheus

# Запустить приложение в dev режиме
# --reload: автоматически перезапускать при изменении кода
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8088

# Линтер и type checker
lint:
	ruff check app tests
	ruff format --check app tests
	mypy --strict -p app

# Автоматически исправить стиль кода
format:
	ruff format app tests
	ruff check --fix app tests

# Запустить тесты
test:
	python -m pytest $(if $(filter-out $@,$(MAKECMDGOALS)),$(filter-out $@,$(MAKECMDGOALS)),tests/) -v --cov=app --cov-report=html --cov-report=term-missing

# Позволяет передавать путь как аргумент:
# make test tests/integration/test_webhooks.py
%:
	@:

# Запустить только быстрые unit тесты (без Docker контейнеров)
test-unit:
	python -m pytest tests/unit/ -v

# Создать новую миграцию Alembic
# Использование: make migrate-new MSG="add payments table"
migrate-new:
	alembic revision --autogenerate -m "$(MSG)"

# Применить все миграции
migrate:
	alembic upgrade head

# Откатить последнюю миграцию
migrate-down:
	alembic downgrade -1

# Показать историю миграций
migrate-history:
	alembic history --verbose

k8s-deploy:
	kubectl apply -k k8s/

k8s-status:
	kubectl get all -n payflow

k8s-logs:
	kubectl logs -f deployment/payflow-api -n payflow