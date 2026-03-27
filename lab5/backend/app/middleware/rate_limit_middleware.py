"""Rate limiting middleware template for LAB 05."""

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import payment_rate_limit_key


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-based rate limiting для endpoint оплаты.

    Цель:
    - защита от DDoS/шторма запросов;
    - защита от случайных повторных кликов пользователя.
    """

    def __init__(self, app, limit_per_window: int = 5, window_seconds: int = 10):
        super().__init__(app)
        self.limit_per_window = limit_per_window
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        is_payment_endpoint = (
            request.url.path.startswith("/api/orders/") and
            request.url.path.endswith("/pay")
        ) or request.url.path.startswith("/api/payments/retry-demo")
        
        if not is_payment_endpoint:
            return await call_next(request)
        
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        subject = f"ip:{client_ip}"

        redis_key = payment_rate_limit_key(subject)
        redis_client = get_redis()
        curr_cnt = await redis_client.incr(redis_key)

        if curr_cnt == 1:
            await redis_client.expire(redis_key, self.window_seconds)

        headers = {
            "X-RateLimit-Limit": str(self.limit_per_window),
            "X-RateLimit-Remaining": str(max(0, self.limit_per_window - curr_cnt)),
            "X-RateLimit-Window": f"{self.window_seconds}s"
        }

        if curr_cnt > self.limit_per_window:
            return Response(
                content='{"error": "Too many requests"}',
                status_code=429,
                headers=headers,
                media_type="application/json"
            )
        
        response = await call_next(request)
        for k, v in headers.items():
            response.headers[k] = v
        return response
