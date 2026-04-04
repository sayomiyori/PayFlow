import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.main import app
from app.core.database import Base, get_db

#Using other test db
TEST_DATABASE_URL="postgresql+asyncpg://payflow:payflow@localhost:5432/payflow_test"

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """
    Making engine for testing DB
    scope ="session" means it will be created once for the entire test session
    NullPool: the tests do not need a pool — each test runs in a transaction.
    """

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)

    #Creating all tables in the test DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    #Deleting all tables in the test DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    """
    Each test will get its own session
    Using ROLLBACK instead of COMMIT to roll back the transaction after the test
    """
    async with async_sessionmaker(test_engine, class_=AsyncSession)() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """
    HTTP client for testing API
    Redefining get_db dependency to use the test session
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()