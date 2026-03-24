\timing on
\echo '=== PARTITION ORDERS BY DATE ==='


CREATE TABLE orders_new (
    id UUID,
    user_id UUID,
    status VARCHAR(20),
    total_amount DECIMAL(10, 2),
    created_at TIMESTAMPTZ
) PARTITION BY RANGE (created_at);

CREATE TABLE orders_demo_2024_q1 PARTITION OF orders_new
FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');

CREATE TABLE orders_demo_2024_q2 PARTITION OF orders_new
FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');

CREATE TABLE orders_demo_2024_q3 PARTITION OF orders_new
FOR VALUES FROM ('2024-07-01') TO ('2024-10-01');

CREATE TABLE orders_demo_2024_q4 PARTITION OF orders_new
FOR VALUES FROM ('2024-10-01') TO ('2025-01-01');

CREATE TABLE orders_demo_2025_q1 PARTITION OF orders_new
FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');

CREATE TABLE orders_demo_2025_q2 PARTITION OF orders_new
FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');

CREATE TABLE orders_demo_2025_q3 PARTITION OF orders_new
FOR VALUES FROM ('2025-07-01') TO ('2025-10-01');

CREATE TABLE orders_demo_2025_q4 PARTITION OF orders_new
FOR VALUES FROM ('2025-10-01') TO ('2026-01-01');

CREATE TABLE orders_demo_2026_q1 PARTITION OF orders_new
FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');

CREATE TABLE orders_demo_default PARTITION OF orders_new DEFAULT;

\echo 'Заполнение таблицы с партициями'
INSERT INTO orders_new (id, user_id, status, total_amount, created_at)
SELECT id, user_id, status, total_amount, created_at FROM orders;

\echo 'Создание индексов на таблице с партициями'
CREATE INDEX idx_orders_demo_created_at ON orders_new (created_at);
CREATE INDEX idx_orders_demo_status_created ON orders_new (status, created_at);

ANALYZE orders_new;

\echo 'Запрос к исходной таблице'
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), AVG(total_amount)
FROM orders
WHERE created_at >= '2024-01-01' AND created_at < '2024-06-01';

\echo 'Запрос к таблице с партициями'
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), AVG(total_amount)
FROM orders_new
WHERE created_at >= '2024-01-01' AND created_at < '2024-06-01';