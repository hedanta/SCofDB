# Отчёт по лабораторной работе №4
## Идемпотентность платежных запросов в FastAPI

**Студент:** Лебкова Марина
**Группа:** БПМ-22-ПО-1  
**Дата:** 26.03.2026

## 1. Постановка сценария
1. Пользователь отправляет POST-запрос на оплату заказа
2. На стороне сервера происходит обработка, но из-за сетевого сбоя пользователь не получает подтверждения
3. Пользователь снова пытается оплатить заказ

Без защиты:
- Сервер не знает, что это повторный запрос
- Оба запроса обрабатываются независимо, что приводит к двойному списанию средств с одного заказа

Почему возможна повторная обработка:
- Отсутствие механизма идемпотентности на уровне API
- Сервер не может отличить новый запрос от повторного без специального идентификатора
- Сетевая инфраструктура не гарантирует доставку ответа

## 2. Реализация таблицы idempotency_keys
```
CREATE TABLE idempotency_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    idempotency_key VARCHAR(255) NOT NULL,
    request_method VARCHAR(16) NOT NULL,
    request_path TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'processing',
    status_code INTEGER,
    response_body JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    
    CONSTRAINT idempotency_status_check CHECK (status IN ('processing', 'completed', 'failed')),
    CONSTRAINT idempotency_unique_key UNIQUE (idempotency_key, request_method, request_path)
);
```

- `idempotency_key`: сам ключ идемпотентности из заголовка запроса.
- `request_method` и `request_path`: идентифицируют конкретный endpoint (POST /api/payments/retry-demo).
- `request_hash`: SHA256 хэш тела запроса для обнаружения повторного использования ключа с другим payload.
- `status`: состояние обработки (`processing` - в обработке, `completed` - завершено, `failed` - ошибка).
- `status_code` и `response_body`: кэш ответа для повторных запросов.
- `expires_at`: время жизни записи (7 дней) для автоматической очистки.

Ограничения:
- `uniq_idempotency_key_method_path`: уникальность ключа в рамках endpoint - защита от дубликатов на вставке.

Индексы:
- `idx_idempotency_keys_expires_at` - индекс для эффективной очистки просроченных записей
- `idx_idempotency_keys_key` - индекс для быстрого поиска по ключу
- `idx_idempotency_keys_lookup` - составной индекс для быстрого поиска по ключу + методу + пути
- Триггер `trig_idempotency_updated_at`: автоматическое обновление `updated_at` при изменении записи

## 3. Реализация middleware

1. Из заголовка читается `Idempotency-Key`
2. Для тела запроса вычисляется SHA256-хэш `request_hash`
3. Проверка существующей записи в БД:
    - Выполняется SELECT ... FOR UPDATE для блокировки строки с этим ключом.
    - Если запись найдена:
    - - Хэш не совпадает -- `409 Conflict` с ошибкой о повторном использовании ключа
    - - Статус `completed` -- возвращается сохранённый ответ с заголовком X-Idempotency-Replayed: true.
    - - Статус `processing` -- `409 Conflict`, запрос уже обрабатывается.
    - Если записи нет -- создаётся новая запись со статусом `processing` и сроком жизни (TTL).
4. Вызывается следующий обработчик `call_next`.
5. Сохраняется ответ в БД
- Считывается тело ответа и преобразуется в JSON
- в БД обновляеся запись ключа
6. Клиенту возвращается ответ 
- Либо реальный ответ запроса, либо кэшированный для повторного запроса

## 4. Демонстрация без защиты
Тест: `app/tests/test_retry_without_idempotency.py`
Запуск: `pytest app/tests/test_retry_without_idempotency.py -v -s`

Результат:
```
RETRY PROBLEM DETECTED!
Order 88512709-9a67-4b27-9ac0-07d1d144fe21 was paid 2 times, num attempts: 2:
  - 2026-03-26 10:13:18.924487+00:00: status = paid
  - 2026-03-26 10:13:18.967548+00:00: status = paid

Причина:
Клиент повторил запрос после сетевого сбоя.
Без Idempotency-Key сервер обработал оба запроса независимо.
Это привело к двойному списанию.
```

## 5. Демонстрация с Idempotency-Key
Тест: `app/tests/test_retry_with_idempotency_key.py`
Запуск: `pytest app/tests/test_retry_with_idempotency_key.py -v -s`

Результат (`test_retry_with_same_key_returns_cached_response`):
```json
{
    "success": true, 
    "message": "Retry demo payment succeeded (unsafe)", 
    "order_id": "19e401d3-c30b-4fed-b59f-4d908fe0d9f7", 
    "status": "paid"
}, 
'fixed-key-123'
```
Повторный запрос:
```json
{
    "success": true, 
    "message": "Retry demo payment succeeded (unsafe)", 
    "order_id": "19e401d3-c30b-4fed-b59f-4d908fe0d9f7", 
    "status": "paid"
}, 
```

Признаки кэширования:
- В логах отсутствуют повторные записи с `UPDATE` и `INSERT`

Результат: `completed`, 200, сохранённый JSON ответа.


Результат ():
первый запрос:
```json
{
    "success": true, 
    "message": "Retry demo payment succeeded (unsafe)", 
    "order_id": "819b5852-c664-49d3-914d-2dcf32458e94", 
    "status": "paid"
}
```
повторный запрос с другим payload:
```json
{
    "error": "Idempotency-Key переиспользуется с другим payload"
}
```

## 7. Сравнение с решением из ЛР2 (FOR UPDATE)
_TODO: Сравните подходы по сути и по UX._

`FOR UPDATE`:
- Цель: обеспечить корректную последовательную работу с данными при конкурентном запросе
- Поведение при повторе: повтор блокирует поток до завершения транзакции, затем выполняет обновление
- Гарантия на уровне БД
- UX: пользователь ждёт завершения транзакции

`Idempotency Middleware`:
- Цель: Обеспечить идемпотентность запросов: повторный запрос с тем же ключом возвращает один и тот же результат
- Поведение при повторе: При совпадении ключа и тела возвращается кэшированный ответ, при расхождениях 409 Conflict
- Гарантия на уровне API и отдельной таблицы идемпотентности
- UX: пользователь сразу получает сохранённый результат без повторного выполнения логики

Нужно ли использовать оба механизма вместе:
Да. Эти подходы решают разные задачи и дополняют друг друга:
- `FOR UPDATE` защищает от ситуации, когда два запроса (возможно, с разными ключами идемпотентности) пытаются одновременно оплатить один заказ.
- `Idempotency-Key` защищает от повторных отправок одного и того же запроса одним клиентом.

## 8. Выводы
1. Middleware идемпотентности улучшает UX без дублирования бизнес-логики

2. Защита данных остаётся при любых сбоях

3. Для чистоты данных достаточно триггеров и транзакций (FOR UPDATE + REPEATABLE READ при конкуренции).
Для удобства API и предсказуемого поведения клиента полезен middleware идемпотентности.