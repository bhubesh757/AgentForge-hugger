"""Backend test config.

DB tests use an alembic-migrated Postgres (TEST_DATABASE_URL) and skip if unavailable."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://agentforge:agentforge@localhost:55432/agentforge_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/0")
os.environ["LLM_MOCK_MODE"] = "true"
os.environ["EXECUTION_DISPATCH"] = "inline"
os.environ.setdefault("APP_ENV", "test")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

KEEP = {"alembic_version", "roles", "permissions", "role_permissions"}
_db_state: dict[str, object] = {}


def _migrate() -> str | None:
    if "err" not in _db_state:
        r = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ.copy(),
        )
        _db_state["err"] = None if r.returncode == 0 else (r.stderr.strip().splitlines() or ["unknown"])[-1]
    return _db_state["err"]  # type: ignore[return-value]


@pytest.fixture
async def client(monkeypatch):
    err = _migrate()
    if err:
        pytest.skip(f"test database unavailable: {err[:200]}")
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import app.messaging.dispatch as dispatch
    from app.database.session import async_session_factory
    from app.main import app

    async def _enqueue(session, execution):  # no background runtime in API tests
        return None

    monkeypatch.setattr(dispatch, "enqueue_execution", _enqueue)
    async with async_session_factory() as s:
        tables = (
            await s.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        ).scalars()
        names = [t for t in tables if t not in KEEP]
        if names:
            await s.execute(text("TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " CASCADE"))
            await s.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def plain_client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def register(client, email: str, org: str | None = "Acme") -> dict:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "S3cure-password!",
            "full_name": "Test User",
            "organization_name": org,
        },
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    if me["memberships"]:
        h["X-Organization-ID"] = str(me["memberships"][0]["organization_id"])
    return {"tokens": tokens, "headers": h, "me": me}
