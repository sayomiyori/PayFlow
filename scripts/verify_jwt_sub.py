"""One-off: register + token, assert JWT sub == merchant_id."""
import asyncio
import uuid

from httpx import ASGITransport, AsyncClient

from app.core.security import decode_token
from app.main import app


async def main() -> None:
    email = f"jwt_check_{uuid.uuid4().hex[:8]}@test.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        reg = await c.post(
            "/auth/register",
            json={
                "name": "JWT Check",
                "email": email,
                "password": "SecurePass123!",
                "plan": "free",
            },
        )
        assert reg.status_code == 201, reg.text
        merchant_id = reg.json()["merchant_id"]
        tok = await c.post(
            "/auth/token",
            json={"email": email, "password": "SecurePass123!"},
        )
        assert tok.status_code == 200, tok.text
        access = tok.json()["access_token"]
        payload = decode_token(access)
        assert payload.get("sub") == str(merchant_id), (payload.get("sub"), str(merchant_id))
        print("OK: JWT sub matches merchant_id")


if __name__ == "__main__":
    asyncio.run(main())
