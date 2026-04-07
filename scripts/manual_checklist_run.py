"""Run manual checklist scenarios against ASGI app."""

import asyncio
import os
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import ALGORITHM
from app.main import app

TEST_DATABASE_URL = "postgresql+asyncpg://payflow:payflow@localhost:5432/payflow_test"


async def run() -> None:
    settings = get_settings()
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession)
    results: list[tuple[str, bool, object]] = []

    async with session_factory() as db_session:
        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                email1 = f"manual_a_{uuid.uuid4().hex[:8]}@test.com"
                reg1 = await client.post(
                    "/auth/register",
                    json={
                        "name": "Manual A",
                        "email": email1,
                        "password": "SecurePass123!",
                        "plan": "free",
                    },
                )
                ok = reg1.status_code == 201
                results.append(("POST /auth/register -> 201", ok, reg1.status_code))

                schema1 = reg1.json().get("schema_name") if ok else None
                if schema1:
                    rs = await db_session.execute(
                        text(
                            "SELECT schema_name FROM information_schema.schemata "
                            "WHERE schema_name = :s"
                        ),
                        {"s": schema1},
                    )
                    schema_ok = rs.scalar_one_or_none() == schema1
                else:
                    schema_ok = False
                results.append(("Schema merchant_<uuid> exists", schema_ok, schema1))

                rs = await db_session.execute(
                    text(
                        "SELECT schema_name FROM information_schema.schemata "
                        "WHERE schema_name='public' OR schema_name LIKE 'merchant_%'"
                    )
                )
                schemas = {row[0] for row in rs.fetchall()}
                dn_ok = "public" in schemas and any(s.startswith("merchant_") for s in schemas)
                results.append(("psql \\\\dn has public + merchant_*", dn_ok, len(schemas)))

                tok = await client.post(
                    "/auth/token",
                    json={"email": email1, "password": "SecurePass123!"},
                )
                token_ok = tok.status_code == 200
                results.append(("POST /auth/token -> 200", token_ok, tok.status_code))

                sub_ok = False
                if token_ok:
                    payload = jwt.decode(
                        tok.json()["access_token"],
                        settings.secret_key,
                        algorithms=[ALGORITHM],
                    )
                    sub_ok = payload.get("sub") == reg1.json().get("merchant_id")
                results.append(("JWT sub == merchant_id", sub_ok, None))

                email2 = f"manual_b_{uuid.uuid4().hex[:8]}@test.com"
                reg2 = await client.post(
                    "/auth/register",
                    json={
                        "name": "Manual B",
                        "email": email2,
                        "password": "SecurePass123!",
                        "plan": "free",
                    },
                )
                isolation_ok = (
                    reg2.status_code == 201
                    and reg1.json().get("schema_name") != reg2.json().get("schema_name")
                )
                results.append(("Two merchants isolated by schema", isolation_ok, reg2.status_code))

                tok2 = await client.post(
                    "/auth/token",
                    json={"email": email1, "password": "SecurePass123!"},
                )
                access = tok2.json()["access_token"]
                headers = {"Authorization": f"Bearer {access}"}
                codes = []
                for _ in range(101):
                    resp = await client.get("/protected/limited-ping", headers=headers)
                    codes.append(resp.status_code)
                counts = Counter(codes)
                rl_ok = counts.get(429, 0) >= 1
                results.append(("Free plan 101 req/min -> 429", rl_ok, dict(counts)))

                expired = jwt.encode(
                    {
                        "sub": "expired-user",
                        "type": "access",
                        "exp": datetime.now(UTC) - timedelta(minutes=1),
                    },
                    settings.secret_key,
                    algorithm=ALGORITHM,
                )
                exp_resp = await client.get(
                    "/protected/me",
                    headers={"Authorization": f"Bearer {expired}"},
                )
                exp_ok = exp_resp.status_code == 401
                results.append(("Expired token -> 401", exp_ok, exp_resp.status_code))

                file_exists = os.path.exists("tests/unit/test_auth.py")
                results.append(("tests/unit/test_auth.py exists", file_exists, file_exists))
        finally:
            app.dependency_overrides.clear()
            await db_session.rollback()

    await engine.dispose()

    print("MANUAL CHECKLIST RESULTS")
    for title, ok, extra in results:
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {title} :: {extra}")


if __name__ == "__main__":
    asyncio.run(run())
