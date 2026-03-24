\timing on
\echo '=== AFTER PARTITIONING ==='

SET max_parallel_workers_per_gather = 0;
SET work_mem = '32MB';

-- TODO:
-- Выполните ANALYZE для партиционированной таблицы/таблиц
-- Пример:
-- ANALYZE orders;

-- ============================================
-- TODO:
-- Скопируйте сюда те же запросы, что в:
--   02_explain_before.sql
--   04_explain_after_indexes.sql
-- и выполните EXPLAIN (ANALYZE, BUFFERS) после партиционирования.
-- ============================================

\echo '--- Q1 ---'
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, user_id, status, total_amount, created_at
FROM orders
WHERE status = 'completed' 
ORDER BY total_amount DESC
LIMIT 10;

\echo '--- Q2 ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, user_id, status, total_amount, created_at
FROM orders
WHERE status = 'paid'
    AND created_at BETWEEN '2024-01-01' AND '2024-06-01';

\echo '--- Q3 ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT 
    o.user_id,
    COUNT(DISTINCT o.id) AS orders_count,
    SUM(oi.quantity) AS total_items,
    SUM(total_amount) AS total_spent
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.status = 'paid'
GROUP BY o.user_id
ORDER BY total_spent DESC
LIMIT 10;


-- (Опционально) Q4: полный агрегат по периоду, который сложно ускорить индексами
-- доставленные заказы, сделанные осенью и зимой.
\echo '--- Q4 ---'
EXPLAIN (ANALYZE, BUFFERS)
SELECT 
    o.id,
    o.user_id,
    o.total_amount,
    o.created_at,
    (
        SELECT osh.changed_at
        FROM order_status_history osh
        WHERE osh.order_id = o.id 
          AND osh.status = 'paid'
        ORDER BY osh.changed_at DESC
        LIMIT 1
    ) AS paid_at,
    (
        SELECT COUNT(*)
        FROM order_items oi
        WHERE oi.order_id = o.id
    ) AS items_count

FROM orders_new o
WHERE o.status = 'shipped'
  AND EXTRACT(MONTH FROM o.created_at) IN (1,2,3,9,10,11,12)
ORDER BY o.created_at;