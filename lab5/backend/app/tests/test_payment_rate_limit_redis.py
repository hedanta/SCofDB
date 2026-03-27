"""
LAB 05: Rate limiting endpoint оплаты через Redis.
"""

import asyncio
import uuid
import pytest
import os


from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.sql import text
from httpx import AsyncClient

os.environ["REDIS_URL"] = "redis://localhost:6380/0"

from app.main import app
from app.infrastructure import db
from app.infrastructure.db import get_db
from app.infrastructure.redis_client import get_redis


DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5434/marketplace"


@pytest.fixture()
async def engine():
    engine = create_async_engine(DATABASE_URL, echo=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def override_db(engine):
    async def _get_test_db():
        async with AsyncSession(engine) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def override_sessionlocal(engine):
    test_sessionmaker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    db.SessionLocal = test_sessionmaker
    yield


@pytest.fixture
def override_redis():
    test_redis = Redis.from_url("redis://localhost:6380/0", decode_responses=True)

    async def _get_test_redis():
        return test_redis

    app.dependency_overrides[get_redis] = _get_test_redis
    yield
    app.dependency_overrides.pop(get_redis, None)


@pytest.fixture
async def async_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

async def create_order(engine):
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()
    async with AsyncSession(engine) as test_session:
        async with test_session.begin():
            await test_session.execute(
                text("""
                    INSERT INTO users (id, email, name, created_at)
                    VALUES(:user_id, :email, :name, NOW())
                """),
                {
                    "user_id": user_id,
                    "email": f"test-{str(uuid.uuid4())[:8]}@test.com",
                    "name": 'test'
                }
            )
            await test_session.execute(
                text("""
                    INSERT INTO orders (id, user_id, status, total_amount, created_at)
                    VALUES (:order_id, :user_id, 'created', 123.00, NOW())
                """),
                {
                    "order_id": order_id,
                    "user_id": user_id
                }
            )
            await test_session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (gen_random_uuid(), :order_id, 'created', NOW())
                """),
                {"order_id": order_id}
            )

    return order_id, user_id


@pytest.fixture
async def test_order(engine):
    order_id, user_id = await create_order(engine)
    yield order_id

    async with AsyncSession(engine) as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM order_status_history WHERE order_id = :id"),
                {"id": order_id}
            )
            await session.execute(
                text("DELETE FROM orders WHERE id = :id"),
                {"id": order_id}
            )
            await session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": user_id}
            )
            await session.execute(text("DELETE FROM idempotency_keys"))


@pytest.fixture
async def cleanup_redis_cache():
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await redis.flushall()
    await redis.aclose()
    yield
    redis2 = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await redis2.flushall()
    await redis2.aclose()
    


@pytest.mark.asyncio
async def test_payment_endpoint_rate_limit(
    async_client,
    test_order,
    engine,
    cleanup_redis_cache,
    override_db,
    override_sessionlocal,
    override_redis
):
    client = async_client

    limit = 5

    success_count = 0
    rate_limited_count = 0

    for _ in range(limit + 2):
        order_id, _ = await create_order(engine)
        response = await client.post(
            f"/api/orders/{str(order_id)}/pay"
        )
        
        if response.status_code == 200:
            success_count += 1

            assert response.headers.get("X-RateLimit-Limit") is not None
            assert response.headers.get("X-RateLimit-Remaining") is not None

        elif response.status_code == 429:
            rate_limited_count += 1
            assert success_count == limit, f"Успешные запросы не соответствуют лимиту (success: {success_count}, limited: {rate_limited_count} | {limit})"
            await asyncio.sleep(delay=10)
            response = await client.post(
                f"/api/orders/{str(order_id)}/pay"
            )
            assert response.status_code == 200, "Повторный запрос спустя время выполнился с ошибкой"
