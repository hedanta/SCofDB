"""Cache consistency demo endpoints for LAB 05."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.infrastructure.db import get_db
from app.application.cache_service import CacheService
from app.application.cache_events import CacheInvalidationEventBus, OrderUpdatedEvent


router = APIRouter(prefix="/api/cache-demo", tags=["cache-demo"])


class UpdateOrderRequest(BaseModel):
    """Payload для изменения заказа в demo-сценариях."""

    new_total_amount: float


@router.get("/catalog")
async def get_catalog(use_cache: bool = True, db: AsyncSession = Depends(get_db)) -> Any:
    cache_service = CacheService(db)
    return await cache_service.get_catalog(use_cache=use_cache)


@router.get("/orders/{order_id}/card")
async def get_order_card(
    order_id: uuid.UUID,
    use_cache: bool = True,
    db: AsyncSession = Depends(get_db),
) -> Any:
    cache_service = CacheService(db)
    order_data = await cache_service.get_order_card(str(order_id), use_cache=use_cache)
    if order_data is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order_data


@router.post("/orders/{order_id}/mutate-without-invalidation")
async def mutate_without_invalidation(
    order_id: uuid.UUID,
    payload: UpdateOrderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Намеренно сломанный сценарий консистентности.
    """
    result = await db.execute(
        text("""
            SELECT id FROM orders WHERE id = :order_id
        """),
        {
            "order_id": order_id
        }
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Order not found")
    
    await db.execute(
        text("""
            UPDATE orders
            SET total_amount = :new_total_amount
            WHERE id = :order_id
        """),
        {
            "order_id": order_id,
            "new_total_amount": payload.new_total_amount
        }
    )
    await db.commit()
    return {
        "message": "Order was updated in DB, cache was not invalidated",
        "order_id": str(order_id),
        "new_total_amount": payload.new_total_amount
    }

@router.post("/orders/{order_id}/mutate-with-event-invalidation")
async def mutate_with_event_invalidation(
    order_id: uuid.UUID,
    payload: UpdateOrderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        text("""
            SELECT id FROM orders WHERE id = :order_id
        """),
        {
            "order_id": order_id
        }
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Order not found")
    
    await db.execute(
        text("""
            UPDATE orders
            SET total_amount = :new_total_amount
            WHERE id = :order_id
        """),
        {
            "order_id": order_id,
            "new_total_amount": payload.new_total_amount
        }
    )
    await db.commit()
    cache_service = CacheService(db)
    event_bus = CacheInvalidationEventBus(cache_service)

    await event_bus.publish_order_updated(
        OrderUpdatedEvent(order_id=str(order_id))
    )

    return {
        "message": "Order was updated in DB and cache was invalidated",
        "order_id": str(order_id),
        "new_total_amount": payload.new_total_amount,
        "cache_invalidated": ["order_card", "catalog"]
    }