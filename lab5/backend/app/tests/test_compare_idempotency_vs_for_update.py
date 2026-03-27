"""
LAB 04: Сравнение подходов
1) FOR UPDATE (решение из lab_02)
2) Idempotency-Key + middleware (lab_04)
"""

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


@pytest.mark.asyncio
async def test_compare_for_update_and_idempotency_behaviour(engine, async_client, override_db, override_sessionlocal):
    order_fu, _ = await create_order(engine)
    order_ik, _ = await create_order(engine)
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        
        print("FOR UPDATE")
        
        payload = {
            "order_id": str(order_fu),
            "mode": "for_update"
        }

        response_fu1 = await client.post(
            "/api/payments/retry-demo", 
            json=payload
        )

        data1 = response_fu1.json()
        
        assert response_fu1.status_code == 200
        assert data1.get("success") == True

        response_fu2 = await client.post(
            "/api/payments/retry-demo", 
            json=payload
        )

        data2 = response_fu2.json()
        
        assert response_fu2.status_code == 200
        assert data2.get("success") == False
        assert "already paid" in data2.get("message", "").lower()

        key = "fixed-key-234"
        payload = {"order_id": str(order_ik), "mode": "unsafe"}

        print("IDEMPOTENCY KEY")
        
        response_idemp1 = await async_client.post(
            "/api/payments/retry-demo",
            json=payload,
            headers={"Idempotency-Key": key},
        )
        assert response_idemp1.status_code == 200

        response_idemp2 = await async_client.post(
            "/api/payments/retry-demo",
            json=payload,
            headers={"Idempotency-Key": key},
        )

        assert response_idemp2.headers.get("X-Idempotency-Replayed") == "true"
        assert response_idemp2.json() == response_idemp1.json()

    async with AsyncSession(engine) as session:
        service = PaymentService(session)
        history_idemp = await service.get_payment_history(order_ik)
        history_fu = await service.get_payment_history(order_fu)

    assert len(history_fu) == 1, "FOR UPDATE: Оплата должна произойти только один раз"
    assert len(history_idemp) == 1, "Idempotency Key: Оплата должна произойти только один раз"

    print("РЕЗУЛЬТАТЫ СРАВНЕНИЯ")
   
    print("\n   FOR UPDATE подход:")
    print(f"  - Первый запрос: УСПЕХ (success=True)")
    print(f"  - Второй запрос: ОШИБКА (success=False, сообщение: {data2.get('message')})")
    print(f"  - Записей об оплате: {len(history_fu)}")
       
    print("\n   Idempotency-Key подход:")
    print(f"  - Первый запрос: УСПЕХ (success=True)")
    print(f"  - Второй запрос: УСПЕХ (success=True, из кэша)")
    print(f"  - Заголовок X-Idempotency-Replayed: {response_idemp2.headers.get('X-Idempotency-Replayed')}")
    print(f"  - Записей об оплате: {len(history_idemp)}")