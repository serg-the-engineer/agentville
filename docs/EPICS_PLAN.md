# EPICS_PLAN.md

План епиков для MVP Zero-Player LLM-Arena.

## Принципы планирования
- Епики формируют dependency graph, чтобы можно было распараллеливать независимые треки.
- Контракты (DTO, schema, event types) стабилизируются как можно раньше.
- Интеграционные точки фиксируются заранее и проверяются отдельными интеграционными PR.

## Епики
| ID | Epic | Результат | Зависимости |
|---|---|---|---|
| E1 | Domain Contracts | Зафиксированы action/event/log enum, JSON schema, API/WS DTO | - |
| E2 | Persistence | SQLAlchemy модели + Alembic миграции + индексы | E1 |
| E3 | Match Setup | `prepare_room_for_match`: agency=2, stats pool=2, weaknesses, search slots | E1, E2 |
| E4 | Core Engine | Исполнение раундов, D10 checks, visibility logs, scoring | E1 |
| E5 | LLM Adapter | vLLM batch, validation, fallback, memory trimming | E1, E4 |
| E6 | REST Lifecycle | `rooms/join/agent/ready/start/results/admin` | E2, E3, E4, E5 |
| E7 | Runner Orchestration | Background runner + advisory lock + safe resume | E4, E5, E6 |
| E8 | WS Streaming | Public logs stream (+ optional private stream) | E6, E7 |
| E9 | Minimal UI/Admin | Lobby + game logs + results + admin timeline | E6, E8 |
| E10 | Reliability & Perf | Load test 10x12, profiling, bottleneck fixes | E7, E8, E9 |

## Параллельные треки
| Трек | Епики | Комментарий |
|---|---|---|
| Track A (Contracts & Data) | E1, E2 | Блокирует большую часть интеграций, запускать первым |
| Track B (Game Logic) | E4 | Можно вести параллельно с E2 после freeze контрактов E1 |
| Track C (Match Bootstrap) | E3 | Отдельный пакет вокруг стартовых правил и генерации лута |
| Track D (LLM) | E5 | Параллельно с E6 при стабильных интерфейсах E1/E4 |
| Track E (Platform/API) | E6, E7, E8 | Оркестрация и delivery |
| Track F (UI/Validation) | E9, E10 | После готового API/WS |

## Milestone-гейты
- M1: `E1+E2+E4` завершены, engine работает на in-memory и DB-модели готовы.
- M2: `E3+E5+E6` завершены, возможен e2e run без UI.
- M3: `E7+E8+E9` завершены, рабочий MVP с real-time наблюдением.
- M4: `E10` завершен, подтверждены производительность и надежность.

## Правило делегирования епиков агентам
- Один агент = один epic stream в пределах одного PR-stack.
- На стыке епиков интеграция через отдельный "integration PR".
- Если epic меняет публичный контракт, он обязан первым коммитом обновить схему и тесты-контракты.
