"""
Тест для демонстрации ПРОБЛЕМЫ race condition.

Этот тест должен ПРОХОДИТЬ, подтверждая, что при использовании
pay_order_unsafe() возникает двойная оплата.
"""

import asyncio
import pytest
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.application.payment_service import PaymentService


DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/marketplace"


@pytest.fixture()
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
    await test_session.rollback()


@pytest.mark.asyncio
async def test_concurrent_payment_unsafe_demonstrates_race_condition(test_order, engine):
    """
    Тест демонстрирует проблему race condition при использовании pay_order_unsafe().
    
    ОЖИДАЕМЫЙ РЕЗУЛЬТАТ: Тест ПРОХОДИТ, подтверждая, что заказ был оплачен дважды.
    Это показывает, что метод pay_order_unsafe() НЕ защищен от конкурентных запросов.
    """
    order_id = test_order
    async def payment_attempt_1():
        async with AsyncSession(engine) as session1:
            service1 = PaymentService(session1)
            return await service1.pay_order_unsafe(order_id)
           
    async def payment_attempt_2():
        async with AsyncSession(engine) as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_unsafe(order_id)
           
    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )

    async with AsyncSession(engine) as session:
        service = PaymentService(session)
        history = await service.get_payment_history(order_id)
    
    assert len(history) == 2, "Ожидалось 2 записи об оплате (RACE CONDITION!)"
    print(f"RACE CONDITION DETECTED!")
    print(f"Order {order_id} was paid TWICE:")
    for record in history:
        print(f"  - {record['changed_at']}: status = {record['status']}")

    print(f"Попытка 1: {'Успешно' if not isinstance(results[0], Exception) else f'Ошибка: {type(results[0]).__name__}'}")
    print(f"Попытка 2: {'Успешно' if not isinstance(results[1], Exception) else f'Ошибка: {type(results[1]).__name__}'}")


if __name__ == "__main__":
    """
    Запуск теста:
    
    cd backend
    export PYTHONPATH=$(pwd)
    pytest app/tests/test_concurrent_payment_unsafe.py -v -s
    
    ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
    ✅ test_concurrent_payment_unsafe_demonstrates_race_condition PASSED
    
    Вывод должен показывать:
    ⚠️ RACE CONDITION DETECTED!
    Order XXX was paid TWICE:
      - 2024-XX-XX: status = paid
      - 2024-XX-XX: status = paid
    """
    pytest.main([__file__, "-v", "-s"])
