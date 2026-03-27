from typing import Any
import json
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import catalog_key, order_card_key



class CacheService:
    """
    Сервис кэширования каталога и карточки заказа.
    """
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.redis = get_redis()
        self.ttl_seconds = 600

    async def get_catalog(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        cache_key = catalog_key()
        if use_cache:
            cached_data = await self.redis.get(cache_key)
            if cached_data is not None:
                return json.loads(cached_data)
            
        result = await self.db.execute(
            text("""
                SELECT
                    oi.product_name,
                    count(*) AS order_lines,
                    sum(oi.quantity) AS sold_qty,
                    round(avg(oi.price)::numeric, 2) AS avg_price
                FROM order_items oi
                GROUP BY oi.product_name
                ORDER BY sold_qty DESC
                LIMIT 100;
            """)
        )
        rows = result.mappings().all()
        catalog_data = [
            {
                "product_name": row.product_name,
                "order_lines": row.order_lines,
                "sold_qty": row.sold_qty,
                "avg_price": float(row.avg_price)
            }
            for row in rows
        ]

        if use_cache:
            await self.redis.setex(
                cache_key,
                self.ttl_seconds,
                json.dumps(catalog_data, default=str)
            )
        
        return catalog_data


    async def get_order_card(self, order_id: str, *, use_cache: bool = True) -> dict[str, Any] | None:
        cache_key = order_card_key(order_id)
        if use_cache:
            cached_data = await self.redis.get(cache_key)
            if cached_data is not None:
                return json.loads(cached_data)

        order_result = await self.db.execute(
            text("""
                SELECT 
                 o.id, 
                 o.user_id, o.status, o.total_amount, o.created_at,
                 u.email, u.name
                FROM orders o
                JOIN users u ON o.user_id = u.id
                WHERE o.id = :order_id
            """),
            {
                "order_id": order_id
            }
        )
        order_row = order_result.mappings().first()
        if order_row is None:
            return None
        
        items_result = await self.db.execute(
            text("""
                SELECT id, product_name, price, quantity
                FROM order_items
                WHERE order_id = :order_id
            """), 
            {
                "order_id": order_id
            }
        )
        items_rows = items_result.mappings().all()
        items = [
            {
                "id": str(row.id),
                "product_name": row.product_name,
                "price": float(row.price),
                "quantity": row.quantity
            } 
            for row in items_rows 
        ]

        order_data = {
            "id": str(order_row.id),
            "user_id": str(order_row.user_id),
            "status": order_row.status,
            "total_amount": float(order_row.total_amount),
            "created_at": order_row.created_at.isoformat(),
            "user": {
                "email": order_row.email,
                "name": order_row.name
            },
            "items": items
        }

        if use_cache:
            await self.redis.setex(
                cache_key,
                self.ttl_seconds,
                json.dumps(order_data, default=str)
            )

        return order_data

        
    async def invalidate_order_card(self, order_id: str) -> None:
        await self.redis.delete(order_card_key(order_id))

    async def invalidate_catalog(self) -> None:
        await self.redis.delete(catalog_key())
