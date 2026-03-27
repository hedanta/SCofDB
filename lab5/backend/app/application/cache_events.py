from dataclasses import dataclass
from typing import Callable, Awaitable, List

from app.application.cache_service import CacheService


@dataclass
class OrderUpdatedEvent:
    """Событие изменения заказа."""
    order_id: str


class CacheInvalidationEventBus:
    """
    Простой in-memory event bus для инвалидции кэша.
    """

    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
        self._subscribers: List[Callable[[OrderUpdatedEvent], Awaitable[None]]] = []

        self.subscribe(self._handle_order_updated)

    def subscribe(
        self,
        handler: Callable[[OrderUpdatedEvent], Awaitable[None]]
    ) -> None:
        self._subscribers.append(handler)

    async def publish_order_updated(self, event: OrderUpdatedEvent) -> None:
        for handler in self._subscribers:
            await handler(event)

    async def _handle_order_updated(self, event: OrderUpdatedEvent) -> None:
        await self.cache.invalidate_order_card(event.order_id)
        await self.cache.invalidate_catalog()