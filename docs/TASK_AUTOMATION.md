# TASK_AUTOMATION.md

Почасовая автоматизация управления задачами в GitHub.

## Цель
Стабильно продвигать backlog без ручного микроменеджмента:
- обнаруживать зависшие `in-progress` задачи;
- поддерживать заполненную очередь `ready`;
- при пустом WIP автоматически брать следующую задачу в работу;
- при пустом `ready` нарезать epic на WP.

## Где реализовано
- Скрипт: `scripts/github/hourly_task_loop.sh`
- Workflow: `.github/workflows/hourly-task-loop.yml`

## Алгоритм hourly loop
1. Загрузить открытые issues (`limit=200`).
2. Найти `status:in-progress` non-epic issues.
3. Определить stale по `updatedAt`.
4. Для stale issue:
- добавить комментарий о необходимости обновления статуса;
- если давно нет активности и нет связанного PR, перевести в `status:blocked`.
5. Если в работе есть хотя бы одна задача, новых задач не брать.
6. Если активных задач нет:
- перевести валидные triage-задачи в `ready`;
- выбрать top `ready` (bug first, потом по priority);
- если `ready` пустой, создать WP из доступного epic;
- перевести выбранную задачу в `status:in-progress`.

## Правила безопасности
- WIP limit по умолчанию: 2.
- Автоматика берет новую задачу только когда активных задач 0.
- За один прогон создается ограниченное число новых WP (по умолчанию 2).
- Для одного epic одновременно не больше 3 открытых WP.
- Любое изменение traceable через комментарий-маркер `[hourly-task-loop]`.

## Конфигурация (env vars)
- `GH_REPO` - `OWNER/REPO`.
- `DRY_RUN` - `1` для пробного запуска без изменений.
- `STALE_HOURS` - порог "подвисла" (по умолчанию `6`).
- `BLOCK_AFTER_HOURS` - через сколько переводить в `blocked` (по умолчанию `24`).
- `WIP_LIMIT` - верхняя граница in-progress (по умолчанию `2`).
- `WP_BATCH_SIZE` - сколько WP создавать за один запуск (по умолчанию `2`).
- `MAX_WP_PER_EPIC` - максимум открытых WP на один epic (по умолчанию `3`).

## Ручной запуск
```bash
DRY_RUN=1 GH_REPO="OWNER/REPO" scripts/github/hourly_task_loop.sh
```

## GitHub Actions
Workflow запускается:
- по расписанию `17 * * * *` (каждый час);
- вручную через `workflow_dispatch` (с опцией `dry_run`).

## Что важно держать в issue-телах
Чтобы автоматизация могла triage/decompose корректно:
- у WP/feature - секции `Acceptance Criteria` и `Tests First`;
- у bug - `Reproduction Steps`;
- у epic - секции `Result` и `Dependencies` с ссылками `#<issue_number>`.
