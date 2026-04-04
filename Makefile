.PHONY: dev test lint migrate docker-up docker-down

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

# Запустить приложение в dev режиме
# --reload: автоматически перезапускать при изменении кода
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8088

# Линтер и type checker
lint:
	ruff check app tests
	ruff format --check app tests
	mypy app

# Автоматически исправить стиль кода
format:
	ruff format app tests
	ruff check --fix app tests

# Запустить тесты
test:
	python -m pytest tests/ -v --cov=app --cov-report=html --cov-report=term-missing

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