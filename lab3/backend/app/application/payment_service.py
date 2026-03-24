"""Сервис для демонстрации конкурентных оплат.

Этот модуль содержит два метода оплаты:
1. pay_order_unsafe() - небезопасная реализация (READ COMMITTED без блокировок)
2. pay_order_safe() - безопасная реализация (REPEATABLE READ + FOR UPDATE)
"""
import asyncio
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import OrderAlreadyPaidError, OrderNotFoundError


class PaymentService:
    """Сервис для обработки платежей с разными уровнями изоляции."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def pay_order_unsafe(self, order_id: uuid.UUID) -> dict:
        """
        НЕБЕЗОПАСНАЯ реализация оплаты заказа.
        
        Использует READ COMMITTED (по умолчанию
        ) без блокировок.
        ЛОМАЕТСЯ при конкурентных запросах - может привести к двойной оплате!
        
        Args:
            order_id: ID заказа для оплаты
            
        Returns:
            dict с информацией о заказе после оплаты
            
        Raises:
            OrderNotFoundError: если заказ не найден
            OrderAlreadyPaidError: если заказ уже оплачен
        """
        async with self.session.begin():
            res = await self.session.execute(
                text("SELECT status FROM orders WHERE id = :order_id"),
                {
                    "order_id": order_id
                }
            )
            order = res.mappings().first()
            await asyncio.sleep(0.3)

            if order is None:
                raise OrderNotFoundError(order_id)
            
            if order['status'] != 'created':
                raise OrderAlreadyPaidError(order_id)
            
            await self.session.execute(
                text("""
                    UPDATE orders SET status = 'paid' 
                    WHERE id = :order_id
                """), 
                {"order_id": order_id}
            )

            await self.session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (gen_random_uuid(), :order_id, 'paid', NOW())
                """), 
                {"order_id": order_id}
            )
            
            return {
                "order_id": order_id,
                "status": 'paid',
                "message": "Order paid successfully (unsafe method)"
            }
            

    async def pay_order_safe(self, order_id: uuid.UUID) -> dict:
        """
        БЕЗОПАСНАЯ реализация оплаты заказа.
        
        Использует REPEATABLE READ + FOR UPDATE для предотвращения race condition.
        Корректно работает при конкурентных запросах.
        
        Args:
            order_id: ID заказа для оплаты
            
        Returns:
            dict с информацией о заказе после оплаты
            
        Raises:
            OrderNotFoundError: если заказ не найден
            OrderAlreadyPaidError: если заказ уже оплачен
        """
        async with self.session.begin():
            await self.session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
            res = await self.session.execute(
                text("SELECT status FROM orders WHERE id = :order_id FOR UPDATE"),
                {
                    "order_id": order_id
                }
            )
            order = res.mappings().first()
            if order is None:
                raise OrderNotFoundError(order_id)
            
            if order['status'] != 'created':
                raise OrderAlreadyPaidError(order_id)
            
            await self.session.execute(
                text("""
                    UPDATE orders SET status = 'paid' 
                    WHERE id = :order_id AND status = 'created'
                """), 
                {"order_id": order_id}
            )
            #не делаем insert в order_status_history
            #так как есть триггер в бд на лог изменений

            return {
                "order_id": order_id,
                "status": 'paid',
                "message": "Order paid successfully (safe method)"
            }

        
    async def get_payment_history(self, order_id: uuid.UUID) -> list[dict]:
        """
        Получить историю оплат для заказа.
        
        Используется для проверки, сколько раз был оплачен заказ.
        
        Args:
            order_id: ID заказа
            
        Returns:
            Список словарей с записями об оплате
        """
        res = await self.session.execute(
            text("""
                SELECT id, order_id, status, changed_at
                FROM order_status_history
                WHERE order_id = :order_id AND status = 'paid'
                ORDER BY changed_at
            """),
            {"order_id": order_id}
        )
        log_rows = res.mappings().all()
        logs = [
            {
                "id": row['id'],
                "order_id": row['order_id'],
                "status": row['status'],
                "changed_at": row['changed_at']
            }
            for row in log_rows
        ]
        return logs
