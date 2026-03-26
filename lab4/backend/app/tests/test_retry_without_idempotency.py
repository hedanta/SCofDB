import asyncio
from httpx import AsyncClient
import pytest
import uuid
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy import text

from app.application.payment_service import PaymentService
from app.main import app
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
async def test_retry_without_idempotency_can_double_pay(test_order, engine, override_db, override_sessionlocal):
    order_id = test_order
    payload = {
        "order_id": str(order_id),
        "mode": "unsafe"
    }
    async def retry_attempt_1():
        async with AsyncClient(app=app, base_url="http://test") as client:
            response_fu1 = await client.post(
                "/api/payments/retry-demo", 
                json=payload
            )

            data1 = response_fu1.json()
            
            assert response_fu1.status_code == 200
            assert data1.get("success") == True

    async def retry_attempt_2():
        async with AsyncClient(app=app, base_url="http://test") as client:
            response_fu2 = await client.post(
                "/api/payments/retry-demo", 
                json=payload
            )

            data2 = response_fu2.json()
            
            assert response_fu2.status_code == 200
            assert data2.get("success") == False
            assert "already paid" in data2.get("message", "").lower()

    results = await asyncio.gather(
        retry_attempt_1(),
        retry_attempt_2(),
        return_exceptions=True
    )
    
    async with AsyncSession(engine) as session:
        service = PaymentService(session)
        history = await service.get_payment_history(order_id)
    
    assert len(history) >= 2, f"Ожидалось 2 записи об оплате, получено {len(history)}"
    print(f"RETRY PROBLEM DETECTED!")
    print(f"Order {order_id} was paid {len(history)} times, num attempts: {len(results)}:")
    for record in history:
        print(f"  - {record['changed_at']}: status = {record['status']}")

    print("\nПричина:")
    print("Клиент повторил запрос после сетевого сбоя.")
    print("Без Idempotency-Key сервер обработал оба запроса независимо.")
    print("Это привело к двойному списанию.")
