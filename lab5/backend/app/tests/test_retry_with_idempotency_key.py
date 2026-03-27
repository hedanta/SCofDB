import uuid
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.sql import text
from httpx import AsyncClient
from app.main import app
from app.application.payment_service import PaymentService
from app.infrastructure import db
from app.infrastructure.db import get_db


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
async def async_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
async def test_order(engine):
    """
    Создать тестовый заказ со статусом 'created'.
    """
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


@pytest.mark.asyncio
async def test_retry_with_same_key_returns_cached_response(async_client, test_order, engine, override_db, override_sessionlocal):
    key = "fixed-key-123"
    payload = {"order_id": str(test_order), "mode": "unsafe"}

    response_first = await async_client.post(
        "/api/payments/retry-demo",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert response_first.status_code == 200

    response_second = await async_client.post(
        "/api/payments/retry-demo",
        json=payload,
        headers={"Idempotency-Key": key},
    )

    assert response_second.headers.get("X-Idempotency-Replayed") == "true"
    assert response_second.json() == response_first.json()

    async with AsyncSession(engine) as session:
        service = PaymentService(session)
        history = await service.get_payment_history(test_order)

    assert len(history) == 1, "Оплата должна произойти только один раз"
    print(response_first.json())
    print(response_second.json())

    async with AsyncSession(engine) as session:
        async with session.begin():
            key_record = await session.execute(
                text("SELECT * FROM idempotency_keys WHERE idempotency_key = :key"),
                {"key": key}
            )
            key_data = key_record.fetchone()
            assert key_data is not None, "Запись в idempotency_keys не найдена"
            assert key_data.status_code == 200


@pytest.mark.asyncio
async def test_same_key_different_payload_returns_conflict(async_client, test_order, engine, override_db, override_sessionlocal):
    key = "fixed-key-123"

    payload1 = {"order_id": str(test_order), "mode": "unsafe"}
    response1 = await async_client.post(
        "/api/payments/retry-demo",
        json=payload1,
        headers={"Idempotency-Key": key},
    )
    assert response1.status_code == 200
    print(response1.json())

    payload2 = {"order_id": str(test_order), "mode": "safe"}
    response2 = await async_client.post(
        "/api/payments/retry-demo",
        json=payload2,
        headers={"Idempotency-Key": key},
    )
    assert response2.status_code == 409
    print(response2.json())