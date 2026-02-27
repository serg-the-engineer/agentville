# HARNESS_BASELINE.md

Как принципы из статьи OpenAI "Harness Engineering" применены в этом репозитории.
Источник: [Harness Engineering](https://openai.com/index/harness-engineering/)

## Выбранные принципы
1. Agent-legibility важнее объема документации.
2. Короткий `AGENTS.md` как карта входа, а не длинный монолит.
3. Ограничения и инварианты кодируются в тестах/схемах/CI.
4. Малые PR и stack-подход вместо "больших релизных веток".
5. Регулярная repo hygiene и handoff-дисциплина.

## Практическое внедрение
- Создан `AGENTS.md` с навигацией и обязательным TDD workflow.
- Добавлены process docs:
  - `docs/GIT_WORKFLOW.md`
  - `docs/QUALITY_AND_DOD.md`
  - `docs/AGENT_DELIVERY_FRAMEWORK.md`
  - `docs/EPICS_PLAN.md`
- Зафиксирован подход "test-first" для фич и контрактных изменений.
- Введена структура делегирования через Work Packet + integration PR.

## Что это дает
- Быстрый onboard для новых агентов.
- Предсказуемая интеграция изменений.
- Меньше конфликтов при параллельной разработке.
- Выше качество за счет обязательных quality gates.
