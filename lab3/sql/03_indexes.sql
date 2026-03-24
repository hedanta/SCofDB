\timing on
\echo '=== APPLY INDEXES ==='

-- ============================================
-- TODO: Создайте индексы на основе ваших EXPLAIN ANALYZE
-- ============================================

-- Индекс 1
-- TODO:
-- CREATE INDEX ... ON ... USING BTREE (...);
-- Обоснование:
-- - какой запрос ускоряет
-- - почему выбран именно этот тип индекса
CREATE INDEX idx_orders_created_at ON orders (created_at);

-- Индекс 2
-- TODO:
-- CREATE INDEX ... ON ... USING ... (...);
-- Обоснование:
-- - какой запрос ускоряет
-- - почему выбран именно этот тип индекса
CREATE INDEX idx_orders_status_created_at ON orders (status, created_at);

-- Индекс 3
-- TODO:
-- CREATE INDEX ... ON ... USING ... (...);
-- Обоснование:
-- - какой запрос ускоряет
-- - почему выбран именно этот тип индекса
CREATE INDEX idx_order_items_order_id ON order_items (order_id);

CREATE INDEX idx_osh_order_status_changed
ON order_status_history (order_id, status, changed_at DESC);

CREATE INDEX idx_orders_paid_user
ON orders (user_id)
INCLUDE (total_amount)
WHERE status = 'paid';
