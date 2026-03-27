-- wrk script: GET order card endpoint
-- Usage:
-- wrk -t4 -c100 -d30s -s loadtest/wrk/order_card.lua http://localhost:8082
--
-- TODO: перед запуском подставьте валидный order_id в path.

wrk.method = "GET"
wrk.path = "/api/cache-demo/orders/e82aa6e9-7dc2-4418-b73a-d7de989aa6e9/card?use_cache=true"
