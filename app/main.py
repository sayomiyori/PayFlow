import structlog
import sentry_sdk
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.core.config import get_settings
from app.core.database import engine
from app.api.routers import health
from app.api.routers import auth

logger = structlog.get_logger()
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan — это код который выполняется при старте и остановке приложения.
    Заменяет устаревшие @app.on_event("startup") / ("shutdown").
    
    Всё до yield = startup
    Всё после yield = shutdown
    """
    #Startup
    logger.info("starting_payflow", environment=settings.environment)

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
        )

    yield # App working

    #Shutdown
    await engine.dispose()
    logger.info("payflow_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PayFlow API",
        description="Multi-tenant Payment SaaS Platform",
        version="0.1.0",
        lifespan=lifespan,
        #In production hide docs and redoc (security)
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    #CORS - accepting requests from all domains in development
    # In production need to point out specific domains
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)


    #Prometheus metrics available at /metrics
    #Prometheus server will scrape these metrics
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    #Connect routers
    app.include_router(health.router, tags=["system"])

    return app

app = create_app()