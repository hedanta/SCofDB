-- ============================================
-- Схема базы данных маркетплейса
-- ============================================

-- Включаем расширение UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- TODO: Создать таблицу order_statuses
-- Столбцы: status (PK), description
CREATE TABLE IF NOT EXISTS order_statuses (
    status VARCHAR(9) PRIMARY KEY,
    description VARCHAR(100)
);


-- TODO: Вставить значения статусов
-- created, paid, cancelled, shipped, completed
INSERT INTO order_statuses(status, description)
VALUES 
('created', 'Order is created.'),
('paid', 'Order is paid.'),
('cancelled', 'Order is cancelled.'),
('shipped', 'Order is shipped.'),
('completed', 'Order is completed.');


-- TODO: Создать таблицу users
-- Столбцы: id (UUID PK), email, name, created_at
-- Ограничения:
--   - email UNIQUE
--   - email NOT NULL и не пустой
--   - email валидный (regex через CHECK)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(50) UNIQUE NOT NULL CHECK (email <> ''),
    CONSTRAINT email_format CHECK (
        email ~ '^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+$'
    ),
    name VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);


-- TODO: Создать таблицу orders
-- Столбцы: id (UUID PK), user_id (FK), status (FK), total_amount, created_at
-- Ограничения:
--   - user_id -> users(id)
--   - status -> order_statuses(status)
--   - total_amount >= 0
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    status VARCHAR(9) NOT NULL REFERENCES order_statuses(status),
    total_amount DECIMAL(10, 2) NOT NULL CHECK (total_amount >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- TODO: Создать таблицу order_items
-- Столбцы: id (UUID PK), order_id (FK), product_name, price, quantity
-- Ограничения:
--   - order_id -> orders(id) CASCADE
--   - price >= 0
--   - quantity > 0
--   - product_name не пустой
CREATE TABLE IF NOT EXISTS order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name VARCHAR(50) NOT NULL CHECK (TRIM(product_name) <> ''),
    price DECIMAL(10, 2) NOT NULL CHECK (price >= 0),
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);


-- TODO: Создать таблицу order_status_history
-- Столбцы: id (UUID PK), order_id (FK), status (FK), changed_at
-- Ограничения:
--   - order_id -> orders(id) CASCADE
--   - status -> order_statuses(status)
CREATE TABLE IF NOT EXISTS order_status_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status VARCHAR(9) NOT NULL REFERENCES order_statuses(status),
    changed_at TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================
-- КРИТИЧЕСКИЙ ИНВАРИАНТ: Нельзя оплатить заказ дважды
-- ============================================
-- TODO: Создать функцию триггера check_order_not_already_paid()
-- При изменении статуса на 'paid' проверить что его нет в истории
-- Если есть - RAISE EXCEPTION
CREATE OR REPLACE FUNCTION check_order_not_already_paid()
RETURNS trigger AS $$
BEGIN 
    IF EXISTS (
        SELECT 1 FROM order_status_history 
        WHERE order_id = NEW.id AND status = 'paid'
    ) THEN
        RAISE EXCEPTION 'Order % is already paid', NEW.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- TODO: Создать триггер trigger_check_order_not_already_paid
-- BEFORE UPDATE ON orders FOR EACH ROW
CREATE TRIGGER trigger_check_order_not_already_paid
BEFORE UPDATE OF status ON orders
FOR EACH ROW
WHEN (NEW.status = 'paid')
EXECUTE FUNCTION check_order_not_already_paid();

-- ============================================
-- БОНУС (опционально)
-- ============================================
-- TODO: Триггер автоматического пересчета total_amount
CREATE OR REPLACE FUNCTION update_total_amount()
RETURNS trigger AS $$
BEGIN
    UPDATE orders
    SET total_amount = (
        SELECT COALESCE(SUM(price * quantity), 0)
        FROM order_items
        WHERE order_id = NEW.order_id
    )
    WHERE id = NEW.order_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_total_amount
AFTER INSERT OR UPDATE ON order_items
FOR EACH ROW
EXECUTE FUNCTION update_total_amount();

-- TODO: Триггер автоматической записи в историю при изменении статуса
CREATE OR REPLACE FUNCTION log_change_status()
RETURNS trigger AS $$
BEGIN
    INSERT INTO order_status_history(order_id, status, changed_at)
    VALUES (NEW.id, NEW.status, NOW());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_log_change_status
AFTER UPDATE OF status ON orders
FOR EACH ROW
WHEN (NEW.status <> OLD.status)
EXECUTE FUNCTION log_change_status();

-- TODO: Триггер записи начального статуса при создании заказа
CREATE OR REPLACE FUNCTION log_create_order_status()
RETURNS trigger AS $$
BEGIN
    INSERT INTO order_status_history(order_id, status, changed_at)
    VALUES (NEW.id, NEW.status, NEW.created_at);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_log_create_order_status
AFTER INSERT ON orders
FOR EACH ROW
EXECUTE FUNCTION log_create_order_status();