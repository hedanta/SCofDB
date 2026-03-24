"""
Тест для демонстрации РЕШЕНИЯ проблемы race condition.

Этот тест должен ПРОХОДИТЬ, подтверждая, что при использовании
pay_order_safe() заказ оплачивается только один раз.
"""

import asyncio
import pytest
import uuid
import time
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.application.payment_service import PaymentService
from app.domain.exceptions import OrderAlreadyPaidError


# TODO: Настроить подключение к тестовой БД
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/marketplace"


@pytest.fixture(scope="function")
async def engine():
    engine = create_async_engine(DATABASE_URL, echo=True)
    yield engine
    await engine.dispose()


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
                {
                    "order_id": order_id
                }
            )
    
    yield order_id
    async with AsyncSession(engine) as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM order_status_history WHERE order_id = :order_id"),
                {"order_id": order_id}
            )
            await session.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": order_id}
            )
            await session.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id}
            )


@pytest.mark.asyncio
async def test_concurrent_payment_safe_prevents_race_condition(test_order, engine):
    """
    Тест демонстрирует решение проблемы race condition с помощью pay_order_safe().
    
    ОЖИДАЕМЫЙ РЕЗУЛЬТАТ: Тест ПРОХОДИТ, подтверждая, что заказ был оплачен только один раз.
    Это показывает, что метод pay_order_safe() защищен от конкурентных запросов.
    """
    order_id = test_order
    async def payment_attempt_1():
        async with AsyncSession(engine) as session1:
            service1 = PaymentService(session1)
            return await service1.pay_order_safe(order_id)
           
    async def payment_attempt_2():
        async with AsyncSession(engine) as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_safe(order_id)
           
    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )
    await asyncio.sleep(0.5)
    
    success_count = sum(1 for r in results if not isinstance(r, Exception))
    error_count = sum(1 for r in results if isinstance(r, Exception))
       
    assert success_count == 1, "Ожидалась одна успешная оплата"
    assert error_count == 1, "Ожидалась одна неудачная попытка"
    
    async with AsyncSession(engine) as session:
        service = PaymentService(session)
        history = await service.get_payment_history(order_id)

    assert len(history) == 1, "Ожидалась 1 запись об оплате (БЕЗ RACE CONDITION!)"
    print(f"✅ RACE CONDITION PREVENTED!")
    print(f"Order {order_id} was paid only ONCE:")
    print(f"  - {history[0]['changed_at']}: status = {history[0]['status']}")
    print(f"Second attempt was rejected: {results[1]}")


@pytest.mark.asyncio
async def test_concurrent_payment_safe_multiple_orders(engine):
    """
    Дополнительный тест: проверить, что блокировки не мешают разным заказам.
    """
    user_id = uuid.uuid4()
    order_id_1 = uuid.uuid4()
    order_id_2 = uuid.uuid4()

    # Создаем пользователя и два заказа
    async with AsyncSession(engine) as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO users (id, email, name, created_at)
                    VALUES (:user_id, :email, :name, NOW())
                """),
                {
                    "user_id": user_id,
                    "email": f"test-{str(uuid.uuid4())[:8]}@test.com",
                    "name": "multi"
                }
            )

            for order_id in [order_id_1, order_id_2]:
                await session.execute(
                    text("""
                        INSERT INTO orders (id, user_id, status, total_amount, created_at)
                        VALUES (:order_id, :user_id, 'created', 100.00, NOW())
                    """),
                    {
                        "order_id": order_id,
                        "user_id": user_id
                    }
                )

                await session.execute(
                    text("""
                        INSERT INTO order_status_history (id, order_id, status, changed_at)
                        VALUES (gen_random_uuid(), :order_id, 'created', NOW())
                    """),
                    {
                        "order_id": order_id
                    }
                )

    async def payment_attempt_1():
        async with AsyncSession(engine) as session1:
            service1 = PaymentService(session1)
            return await service1.pay_order_safe(order_id_1)

    async def payment_attempt_2():
        async with AsyncSession(engine) as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_safe(order_id_2)

    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    error_count = sum(1 for r in results if isinstance(r, Exception))

    assert success_count == 2, "Ожидались две успешные оплаты"
    assert error_count == 0, "Не ожидались ошибки"

    async with AsyncSession(engine) as session:
        service = PaymentService(session)
        history_1 = await service.get_payment_history(order_id_1)
        history_2 = await service.get_payment_history(order_id_2)

    assert len(history_1) == 1, "Первый заказ должен быть оплачен один раз"
    assert len(history_2) == 1, "Второй заказ должен быть оплачен один раз"

    print("FOR UPDATE блокирует только конкретную строку")
    print(f"Order {order_id_1} paid successfully")
    print(f"Order {order_id_2} paid successfully")


if __name__ == "__main__":
    """
    Запуск теста:
    
    cd backend
    export PYTHONPATH=$(pwd)
    pytest app/tests/test_concurrent_payment_safe.py -v -s
    
    ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
    ✅ test_concurrent_payment_safe_prevents_race_condition PASSED
    
    Вывод должен показывать:
    ✅ RACE CONDITION PREVENTED!
    Order XXX was paid only ONCE:
      - 2024-XX-XX: status = paid
    Second attempt was rejected: OrderAlreadyPaidError(...)
    """
    pytest.main([__file__, "-v", "-s"])
