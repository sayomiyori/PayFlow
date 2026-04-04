from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

# Создаём async движок — он управляет пулом соединений
# pool_size=20: держать до 20 соединений открытыми
# max_overflow=10: при пике разрешить ещё 10 сверх pool_size
# pool_pre_ping=True: перед использованием соединения проверить что оно живо
engine = create_async_engine(
    settings.database_url,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=settings.environment == "development",  # логировать SQL запросы в dev
)

# Фабрика сессий — каждый HTTP запрос получает свою сессию
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # не обнулять атрибуты объектов после commit
)


class Base(DeclarativeBase):
    """
    Базовый класс для всех SQLAlchemy моделей.
    Все таблицы наследуются от него — это нужно Alembic
    для автоматического обнаружения изменений в схеме.
    """
    pass


async def get_db() -> AsyncSession:
    """
    Dependency для FastAPI. Использование:
    
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    
    async with гарантирует закрытие сессии даже при ошибке.
    """
    async with AsyncSessionLocal() as session:
        yield session