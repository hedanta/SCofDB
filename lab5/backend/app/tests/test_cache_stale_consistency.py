"""
LAB 05: Демонстрация неконсистентности кэша.
"""

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


@pytest.fixture
async def test_order(engine):
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
async def test_stale_order_card_when_db_updated_without_invalidation(
    engine, test_order, cleanup_redis_cache, async_client, override_db, override_sessionlocal
):
    orig_total = 123.0
    new_total = 456.0
    client = async_client
    response1 = await client.get(
        f"/api/cache-demo/orders/{str(test_order)}/card",
        params={"usa_cache": "true"}
    )
    assert response1.status_code == 200
    order_data_orig = response1.json()
    print(f"Исходные данные: total_amount = {order_data_orig['total_amount']}")
    assert order_data_orig['total_amount'] == orig_total

    print(f"Изменим заказ в БД через mutate-without-invalidation")
    print(f"Новый total_amount: {new_total}")

    response2 = await client.post(
        f"/api/cache-demo/orders/{str(test_order)}/mutate-without-invalidation",
        json={"new_total_amount": new_total}
    )

    assert response2.status_code == 200
    print(f"Результат: {response2.json()['message']}")

    async with AsyncSession(engine) as session:
        result = await session.execute(
            text("SELECT total_amount FROM orders WHERE id = :order_id"),
            {
                "order_id": test_order
            }
        )
        row = result.mappings().first()
    print(f"Зачение total_amount в БД: {row.total_amount}")
    assert row.total_amount == new_total

    print("Повторный запрос с use_cache=true без инвалидации")
    response3 = await client.get(
        f"/api/cache-demo/orders/{str(test_order)}/card",
        params={"use_cache": "true"}
    )

    assert response3.status_code == 200
    order_data_new = response3.json()
    print(f"Данные из кэша после изменения в БД: total_amount = {order_data_new['total_amount']}")

    print(f"Проверка консистентности:")
    print(f"  Значение в БД: {row.total_amount}")
    print(f"  Значение из кэша: {order_data_new['total_amount']}")
       
    if order_data_new['total_amount'] == orig_total:
        print(f"STALE DATA DETECTED!")
        print(f" Кэш вернул старые данные ({orig_total})")
        print(f" В БД уже новое значение ({new_total})")
        print(f" Это демонстрирует проблему неконсистентности кэша")
    else:
        print(f"ОШИБКА: Кэш обновился без инвалидации!")
        print(f"Это не соответствует ожидаемому поведению")
        assert False, "Cache was updated without invalidation"

    print(f"Проверка запроса без кэша:")
    response4 = await client.get(
        f"/api/cache-demo/orders/{str(test_order)}/card",
        params={"use_cache": False}
    )
        
    assert response4.status_code == 200
    order_data_no_cache = response4.json()
    print(f"Данные без кэша: total_amount = {order_data_no_cache['total_amount']}")
    assert order_data_no_cache['total_amount'] == new_total
