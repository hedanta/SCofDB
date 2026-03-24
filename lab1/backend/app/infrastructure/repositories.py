"""Реализация репозиториев с использованием SQLAlchemy."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.user import User
from app.domain.order import Order, OrderItem, OrderStatus, OrderStatusChange


class UserRepository:
    """Репозиторий для User."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # TODO: Реализовать save(user: User) -> None
    # Используйте INSERT ... ON CONFLICT DO UPDATE
    async def save(self, user: User) -> None:
        await self.session.execute(
            text("""
                INSERT INTO users (id, email, name, created_at)
                VALUES (:id, :email, :name, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    name = EXCLUDED.name
                RETURNING id
            """),
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "created_at": user.created_at
            },
        )

        await self.session.commit()

    # TODO: Реализовать find_by_id(user_id: UUID) -> Optional[User]
    async def find_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        res = await self.session.execute(
            text("SELECT * FROM users WHERE id = :user_id"),
            {
                "user_id": user_id
            }
        )
        row = res.fetchone()
        if not row:
            return None
        
        return User(
            id=row.id,
            email=row.email,
            name=row.name,
            created_at=row.created_at
        )

    # TODO: Реализовать find_by_email(email: str) -> Optional[User]
    async def find_by_email(self, email: str) -> Optional[User]:
        res = await self.session.execute(
            text("SELECT * FROM users WHERE email = :email"),
            {
                "email": email
            }
        )
        row = res.fetchone()
        if not row:
            return None
        
        return User(
            id=row.id,
            email=row.email,
            name=row.name,
            created_at=row.created_at
        )

    # TODO: Реализовать find_all() -> List[User]
    async def find_all(self) -> List[User]:
        res = await self.session.execute(
            text("SELECT * FROM users")
        )
        rows = res.fetchall()
        return [
            User(
                id=row.id,
                email=row.email,
                name=row.name,
                created_at=row.created_at
            )
            for row in rows
        ]


class OrderRepository:
    """Репозиторий для Order."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # TODO: Реализовать save(order: Order) -> None
    # Сохранить заказ, товары и историю статусов
    async def save(self, order: Order) -> None:
        await self.session.execute(
            text("""
                INSERT INTO orders (user_id, id, status, total_amount, created_at)
                VALUES (:user_id, :id, :status, :total_amount, :created_at)
                ON CONFLICT (id)
                DO UPDATE SET 
                    status = EXCLUDED.status,
                    total_amount = EXCLUDED.total_amount
                RETURNING id
            """),
            {
                "user_id": order.user_id,
                "id": order.id,
                "status": order.status,
                "total_amount": order.total_amount,
                "created_at": order.created_at
            }
        )

        for item in order.items:
            await self.session.execute(
                text("""
                    INSERT INTO order_items (product_name, price, quantity, id, order_id)
                    VALUES (:product_name, :price, :quantity, :id, :order_id)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "product_name": item.product_name,
                    "price": item.price,
                    "quantity": item.quantity,
                    "id": item.id,
                    "order_id": item.order_id
                }
            )
        
        for log in order.status_history:
            await self.session.execute(
                text("""
                    INSERT INTO order_status_history (order_id, status, changed_at, id)
                    VALUES (:order_id, :status, :changed_at, :id)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "order_id": log.order_id,
                    "status": log.status,
                    "changed_at": log.changed_at,
                    "id": log.id
                }
            )

        await self.session.commit()


    # TODO: Реализовать find_by_id(order_id: UUID) -> Optional[Order]
    # Загрузить заказ со всеми товарами и историей
    # Используйте object.__new__(Order) чтобы избежать __post_init__
    async def find_by_id(self, order_id: uuid.UUID) -> Optional[Order]:
        order_res = await self.session.execute(
            text("SELECT * FROM orders WHERE id = :order_id"),
            {
                "order_id": order_id
            }
        )
        order = order_res.mappings().fetchone()
        if order is None:
            return None

        items_res = await self.session.execute(
            text("SELECT * FROM order_items WHERE order_id = :order_id"),
            {
                "order_id": order_id
            }
        )
        items_rows = items_res.mappings().all()
        items = [
            OrderItem(
                product_name=row.product_name,
                price=Decimal(str(row.price)),
                quantity=row.quantity,
                id=row.id,
                order_id=row.order_id
            )
            for row in items_rows
        ]

        history_res = await self.session.execute(
            text("SELECT * FROM order_status_history WHERE order_id = :order_id"),
            {
                "order_id": order_id
            }
        )
        history_rows = history_res.mappings().all()
        history = [
            OrderStatusChange(
                order_id=row.order_id,
                status=OrderStatus(row.status),
                changed_at=row.changed_at,
                id=row.id
            )
            for row in history_rows
        ]

        order_obj = object.__new__(Order)
        order_obj.id = order['id']
        order_obj.user_id = order['user_id']
        order_obj.status = OrderStatus(order['status'])
        order_obj.total_amount = Decimal(str(order['total_amount']))
        order_obj.created_at = order['created_at']
        order_obj.items = items
        order_obj.status_history = history

        return order_obj

    # TODO: Реализовать find_by_user(user_id: UUID) -> List[Order]
    async def find_by_user(self, user_id: uuid.UUID) -> List[Order]:
        user_orders = await self.session.execute(
            text("SELECT * FROM orders WHERE user_id = :user_id"),
            {
                "user_id": user_id
            }
        )
        user_orders_rows = user_orders.mappings().all()

        all_user_orders = []
        
        for order in user_orders_rows:
            order_id = order['id']
            items_res = await self.session.execute(
                text("SELECT * FROM order_items WHERE order_id = :order_id"),
                {
                    "order_id": order_id
                }
            )
            items_rows = items_res.mappings().all()
            items = [
                OrderItem(
                    product_name=row.product_name,
                    price=Decimal(str(row.price)),
                    quantity=row.quantity,
                    id=row.id,
                    order_id=row.order_id
                )
                for row in items_rows
            ]

            history_res = await self.session.execute(
                text("SELECT * FROM order_status_history WHERE order_id = :order_id"),
                {
                    "order_id": order_id
                }
            )
            history_rows = history_res.mappings().all()
            history = [
                OrderStatusChange(
                    order_id=row.order_id,
                    status=OrderStatus(row.status),
                    changed_at=row.changed_at,
                    id=row.id
                )
                for row in history_rows
            ]

            order_obj = object.__new__(Order)
            order_obj.id = order['id']
            order_obj.user_id = order['user_id']
            order_obj.status = OrderStatus(order['status'])
            order_obj.total_amount = Decimal(str(order['total_amount']))
            order_obj.created_at = order['created_at']
            order_obj.items = items
            order_obj.status_history = history

            all_user_orders.append(order_obj)

        return all_user_orders


    # TODO: Реализовать find_all() -> List[Order]
    async def find_all(self) -> List[Order]:
        orders_res = await self.session.execute(
            text("SELECT * FROM orders")
        )
        orders_rows = orders_res.mappings().all()
        all_orders = []

        for order in orders_rows:
            order_id = order['id']
            items_res = await self.session.execute(
                text("SELECT * FROM order_items WHERE order_id = :order_id"),
                {
                    "order_id": order_id
                }
            )
            items_rows = items_res.mappings().all()
            items = [
                OrderItem(
                    product_name=row.product_name,
                    price=Decimal(str(row.price)),
                    quantity=row.quantity,
                    id=row.id,
                    order_id=row.order_id
                )
                for row in items_rows
            ]

            history_res = await self.session.execute(
                text("SELECT * FROM order_status_history WHERE order_id = :order_id"),
                {
                    "order_id": order_id
                }
            )
            history_rows = history_res.mappings().all()
            history = [
                OrderStatusChange(
                    order_id=row.order_id,
                    status=OrderStatus(row.status),
                    changed_at=row.changed_at,
                    id=row.id
                )
                for row in history_rows
            ]

            order_obj = object.__new__(Order)
            order_obj.id = order['id']
            order_obj.user_id = order['user_id']
            order_obj.status = OrderStatus(order['status'])
            order_obj.total_amount = Decimal(str(order['total_amount']))
            order_obj.created_at = order['created_at']
            order_obj.items = items
            order_obj.status_history = history

            all_orders.append(order_obj)

        return all_orders