# ARCHITECTURE: Zero-Player LLM-Arena (MVP)

## 1. Цели архитектуры
- Детерминированно исполнять матч по серверным правилам без вмешательства игроков после `start`.
- Гарантировать, что backend - единственный источник истины по состоянию игры.
- Быть устойчивым к LLM-сбоям, невалидному JSON и переполнению контекста.
- Давать наблюдаемость: полная история действий, событий, логов и итогового скоринга.

## 2. Компоненты системы
- `API Service` (FastAPI): REST/WS, авторизация, lifecycle комнат.
- `Game Runner`: фоновый процесс исполнения матчей по раундам.
- `Game Engine Core`: чистая бизнес-логика (D10, эффекты, инвентарь, логи).
- `LLM Adapter` (vLLM): батч-запросы по агентам, structured output, retry/fallback.
- `PostgreSQL`: состояние, события, логи, запросы/ответы LLM.
- `WS Broadcaster`: доставка публичных логов наблюдателям в реальном времени.

## 3. Lifecycle комнаты
1. `POST /rooms` создает комнату со статусом `lobby`.
2. Участники подключаются через `join`, создают/обновляют агента до старта.
3. Участники выставляют `ready`.
4. Создатель вызывает `POST /rooms/{id}/start`.
5. До первого раунда движок:
   - фиксирует `agency=2` для всех агентов;
   - случайно распределяет стартовый пул `2` очков между `strength/attentiveness` в любой комбинации;
   - выдает 1 случайную слабость каждому агенту (и еще 1, если выбран опциональный `+1` к стату);
   - генерирует поисковые слоты комнаты (`search_slots`) и предметы для них.
6. Статус комнаты меняется на `playing`, запускается `Game Runner`.
7. После `max_turns` раннер фиксирует `finished` и сохраняет результаты.

## 4. Модель исполнения матча

### 4.1 Эксклюзивность раннера
- На `room_id` берется Postgres advisory lock.
- В каждый момент времени комнату исполняет только один раннер.
- Потеря воркера безопасна: следующий воркер может продолжить с сохраненного `current_turn`.

### 4.2 Алгоритм раунда
Для каждого `turn`:
1. Применить переходящие эффекты к текущему раунду (`agent_effects`), вычислить `effective_agency`.
2. Собрать индивидуальный контекст агентам.
3. Батчем запросить LLM по всем активным агентам.
4. Провалидировать ответы и нормализовать действия.
5. Исполнить действия по слотам и приоритетам.
6. Записать `game_events` и производные `game_logs`.
7. Пушить `public` логи в WS.
8. Обновить `current_turn` и истечения эффектов.

### 4.3 Слоты и приоритеты
Исполнение строго по слотам:
- `slot_index = 1..max_effective_agency_among_agents`
- Берется i-е действие каждого агента (если есть)
- Действия сортируются по приоритету:
  1. `defend`
  2. `drop_item`, `pickup_item`, `broadcast`
  3. `attack`, `steal`
  4. `search`, `inspect_item`, `activate_item`
- Тайбрейк детерминированный: `agent_id ASC` (или `initiative_roll`, фиксируемый от `rng_seed` на раунд)
- Действия исполняются последовательно в отсортированном порядке

## 5. Игровой движок и правила

### 5.1 Статы и формулы
- Базовые статы агента: `strength`, `attentiveness`, `agency=2`.
- Формула проверки: `D10 + stat + mods` vs `D10 + stat + mods`.
- Ничья всегда в пользу защищающейся стороны.

### 5.2 Действия
- `defend`: баф текущего раунда `+1 strength`, `+1 attentiveness`.
- `attack(target_agent_id, item_id?)`: проверка силы; успех - забрать 1 предмет; крит (`>=5`) - `stunned` на следующий раунд.
- `steal(target_agent_id, item_id?)`: проверка внимательности; успех - забрать 1 предмет; само действие не публичное.
- `search`: бросок `D10` открывает слоты поиска:
  - вычисляется `search_total = D10 + attentiveness + mods`
  - `search_total <= 6`: 0 слотов
  - `search_total 7..9`: 1 слот
  - `search_total >= 10`: 2 слота
  В открытом слоте может быть предмет или пусто; найденный предмет уходит в инвентарь или на пол при overflow.
- `inspect_item(item_id)`: приватное раскрытие `activation_desc` и `is_noticeable`.
- `activate_item(item_id)`: применяет `effect_type`, может расходовать предмет.
  - временный `stat_buff/stat_debuff`: `duration_mode=next_attack` (одна атака владельца);
  - постоянный эффект оружия: `duration_mode=permanent`.
- `drop_item(item_id)`: на пол (`owner_agent_id=NULL`), публичный лог.
- `pickup_item(item_id)`: с пола в инвентарь при наличии слота, иначе no-op + приватный лог.
- `broadcast(text)`: публичный лог без механических эффектов.

### 5.3 Оглушение
- Хранится эффектом: `actions_penalty_next_round=1`, `expires_on_turn=turn+1`.
- На старте следующего раунда: `effective_agency = max(0, base_agency - penalties)`.
- Если агент вернул действия при `effective_agency=0`, движок их игнорирует и пишет приватный лог отказа.

## 6. Поисковые слоты и генерация лута
- На комнату создается `search_slots` фиксированного размера.
- Слоты заполняются предметами по конфигу распределения категорий и пустыми слотами.
- MVP defaults:
  - `20` total slots
  - `5` trinkets
  - `3` weapons
  - `1` special
  - остальные пустые
- Слот можно открыть только один раз, повторно он не участвует в поиске.

## 7. Visibility и система логов

### 7.1 Истина vs представление
- `game_events` - структурированные факты, не зависят от аудитории.
- `game_logs` - текстовые представления фактов с адресацией видимости.

### 7.2 Типы логов
- `public`: всем.
- `private`: одному агенту через `recipient_agent_id`.
- `conditional`: одному агенту через `recipient_agent_id` после проверки восприятия.

### 7.3 MVP perception для `steal`
Для каждого наблюдателя (`observer != thief && observer != target`):
- проверка `D10 + observer.attentiveness` vs `perception_threshold` (дефолт 8)
- при успехе создается `conditional` лог наблюдателю

## 8. LLM Adapter и устойчивость

### 8.1 Контекст в запросе LLM
- Видимые логи с последнего хода агента.
- Инвентарь и пол в room-scoped идентификаторах.
- Текущие статы/эффекты (снимок).
- `memory_file_trimmed`.
- `allowed_actions` и JSON Schema ответа.

### 8.2 Контракт ответа
- `actions`: массив длиной `<= effective_agency`
- `memory_file`: новая версия

### 8.3 Валидация
Каждый action валидируется на:
- JSON-схему
- допустимость action type
- существование и видимость `agent_id/item_id`
- preconditions (слоты, владение предметом, доступность предмета на полу)

Невалидные action деградируют в `no-op` + `private` лог ошибки.

### 8.4 Fallback
- Ошибка инференса/таймаут: `actions=[]`, память не обновляется, `llm_error` event.
- Ошибка `context length exceeded`: один ретрай с уменьшенным бюджетом памяти (`/2`), затем пропуск хода.
- Structured output используется как вспомогательная гарантия формата, но не считается полной гарантией корректности.

## 9. Управление памятью
Серверные лимиты:
- `max_base_prompt_chars=6000` (проверка в `ready`)
- `max_memory_chars_sent=4000` (перед каждым запросом)

Политика trimming:
- детерминированный `take_last_n_chars`
- системный префикс: `Memory was truncated`

Хранение:
- `memory_file_raw` - как вернул агент
- `memory_file_trimmed` - что попадет в следующий контекст

## 10. Модель данных (PostgreSQL)

### 10.1 Таблицы
- `users`
- `rooms`
  - `id`, `creator_id`, `status`, `current_turn`, `max_turns`, `inventory_slots`, `allowed_actions`, `rng_seed`, `model_config`, `created_at`, `updated_at`
- `agents`
  - `id`, `room_id`, `user_id`, `name`, `base_prompt`, `memory_file_raw`, `memory_file_trimmed`, `base_strength`, `base_attentiveness`, `base_agency=2`, `weaknesses_json`, `is_ready`, `created_at`, `updated_at`
- `agent_effects`
  - `id`, `room_id`, `agent_id`, `effect_type`, `actions_penalty`, `stat_mods_json`, `expires_on_turn NULL`, `remaining_attacks NULL`, `source`, `created_at`
- `item_templates`
  - `id`, `effect_type`, `effect_payload_json`, `price`, `is_noticeable`, `category`, `created_at`
- `room_item_dictionary`
  - `id`, `room_id`, `template_id`, `obfuscated_name`, `appearance`, `activation_desc`
- `room_items`
  - `id`, `room_id`, `dictionary_id`, `owner_agent_id NULL`, `state_json`, `created_at`, `updated_at`
- `room_search_slots`
  - `id`, `room_id`, `slot_index`, `item_id NULL`, `is_opened`, `created_at`, `updated_at`
- `turn_actions`
  - `id`, `room_id`, `turn_number`, `agent_id`, `request_json`, `response_json`, `raw_text`, `is_valid`, `validation_errors_json`, `created_at`
- `game_events`
  - `id`, `room_id`, `turn_number`, `slot_index`, `event_type`, `payload_json`, `created_at`
- `game_logs`
  - `id`, `room_id`, `turn_number`, `event_id`, `visibility`, `recipient_agent_id NULL`, `message`, `created_at`

### 10.2 Ключевые ограничения
- В API/LLM наружу не передавать `template_id`.
- `room_items.owner_agent_id IS NULL` означает, что предмет на полу.
- Индексы минимум:
  - `rooms(status)`
  - `agents(room_id)`
  - `room_items(room_id, owner_agent_id)`
  - `room_search_slots(room_id, slot_index, is_opened)`
  - `turn_actions(room_id, turn_number)`
  - `game_events(room_id, turn_number, id)`
  - `game_logs(room_id, turn_number, visibility, recipient_agent_id)`

## 11. API и WS

### 11.1 REST
- `POST /rooms`
- `POST /rooms/{id}/join`
- `POST /rooms/{id}/agent`
- `POST /rooms/{id}/ready`
- `POST /rooms/{id}/start`
- `GET /rooms/{id}`
- `GET /rooms/{id}/results`
- `GET /admin/rooms`
- `GET /admin/rooms/{id}`

### 11.2 WebSocket
- `WS /ws/rooms/{id}/public_logs`
- Опционально: `WS /ws/rooms/{id}/private_logs?agent_id=...` (права: owner/admin)

WS payload должен быть event-driven и содержать:
- `room_id`, `turn_number`, `event_id`
- `visibility`
- `message`
- `ts`

## 12. Безопасность и приватность
- Промпты агентов и приватные логи доступны только владельцу и админу.
- Публичные каналы не содержат внутренних идентификаторов шаблонов предметов.
- Для приватных WS-каналов обязательна проверка владения `agent_id`.

## 13. Observability
Минимум метрик:
- `turn_duration_ms`
- `llm_batch_duration_ms`
- `llm_errors_total` (по типам)
- `invalid_actions_total`
- `events_written_total`
- `public_logs_pushed_total`

Минимум структурных событий для аналитики:
- `llm_error`
- `action_validated`
- `action_noop`
- `combat_resolved`
- `item_moved`
- `effect_applied`
- `game_finished`

## 14. План реализации
1. Зафиксировать enums/схемы (`action_type`, `priority`, `event_type`, JSON schema).
2. Поднять миграции и ORM-модели.
3. Реализовать core engine (без LLM) и покрыть юнит-тестами.
4. Добавить LLM-adapter + fallback + trimming.
5. Добавить lifecycle API + runner + WS.
6. Собрать минимальный UI (lobby + game view) и админку.
7. Нагрузочный прогон (`10x12`) и профилирование.

## 15. Acceptance (technical)
- Игра не падает при невалидных ответах LLM.
- Порядок исполнения действий соответствует slot/priority модели.
- Оглушение уменьшает только следующий раунд на 1 действие.
- Conditional logs для `steal` корректно зависят от perception-броска.
- Финальный скоринг равен сумме `price` у предметов в инвентаре агента.
- Поиск открывает `0/1/2` слота строго по диапазонам `D10`.
- Временный баф от эффекта расходуется после первой атаки владельца.
