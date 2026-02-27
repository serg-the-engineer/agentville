# GITHUB_TASKS_PLAYBOOK.md

Как вести backlog и delivery в режиме "1 разработчик + много агентов".

## 0) Базовое правило
- Source of truth по эпикам, багам и WP: GitHub Issues/Project.
- Репозиторий хранит правила процесса, но не хранит живой backlog эпиков.

## 1) One-time setup

### 1.1 Авторизация GitHub CLI
```bash
gh auth login
gh auth refresh -s project
```

### 1.2 Привязка к репозиторию
Если в локальном git нет `origin`, укажи репозиторий вручную:
```bash
export GH_REPO="OWNER/REPO"
```

### 1.3 Синхронизация label-матрицы
```bash
scripts/github/bootstrap_labels.sh
# или явно
scripts/github/bootstrap_labels.sh OWNER/REPO
```

### 1.4 Создание Project (board + поля)
```bash
scripts/github/bootstrap_project.sh @me "Arena MVP Backlog" OWNER/REPO
```
Скрипт создаст поля:
- `Status` (`Inbox`, `Ready`, `In Progress`, `In Review`, `Blocked`, `Done`)
- `Priority` (`P0..P3`)
- `Epic`, `Stream`, `Size`, `Agent`

## 2) Типы задач
- `Epic` (`type:epic`): крупный поток работ и зависимостей.
- `Work Packet` (`type:feature` + префикс в title `E*-WP*`): минимальная единица делегирования агенту.
- `Bug` (`type:bug`): дефект с воспроизведением.
- `Chore` (`type:chore`): инфраструктурные и поддерживающие работы.

## 3) Роли и ответственность
- Product Owner:
  - задает приоритеты, принимает scope epic, решает блокеры.
- Planner/Triage Agent:
  - приводит `status:triage` в `status:ready`.
  - режет epic на WP при пустой очереди ready.
- Delivery Agent:
  - берет задачи из `status:in-progress`, ведет TDD и PR до merge.
- Hourly Automation:
  - проверяет активность по `in-progress`.
  - помечает зависшие задачи и подхватывает следующую работу при пустом WIP.

## 4) Подробный флоу

### 4.1 Intake (Epic/Bug/Task)
1. Создать issue через форму или CLI.
2. Поставить labels: `type:*`, `priority:*`, `area:*`, `status:triage`.
3. Проверить обязательные секции:
   - Epic/WP: `Acceptance Criteria`, `Tests First`.
   - Bug: `Reproduction Steps`, ожидаемое/фактическое поведение.

### 4.2 Декомпозиция Epic -> WP
1. Epic остается открытым как контейнер цели.
2. Planner/automation создает WP-issues с префиксом `E*-WP*`.
3. Каждый WP должен быть выполним за 1 логический PR.
4. В одном epic держать одновременно не больше 3 открытых WP.

### 4.3 Формирование очереди ready
1. `status:triage` -> `status:ready` только после проверки AC и тест-плана.
2. Приоритизация очереди:
   - сначала `type:bug`, затем feature/chore.
   - внутри типа `priority:p0 -> p3`.

### 4.4 Взятие задачи в работу
1. Одновременно в работе не более 2 задач (`status:in-progress`).
2. Если уже есть активная работа, новые задачи не стартовать автоматически.
3. Если активной работы нет, берется верхняя задача из `status:ready`.
4. Если `ready` пустой, сначала режем доступный epic на WP, потом берем WP в работу.

### 4.5 Исполнение (TDD)
1. RED: сначала failing tests.
2. GREEN: минимальная реализация.
3. REFACTOR: улучшение без изменения поведения.
4. На PR: перевести задачу в `status:review`.

### 4.6 Завершение
1. После merge закрыть issue.
2. Epic закрывается только когда закрыты все его WP и выполнены AC epic.

### 4.7 Blocked/Stale
1. Если задача в `in-progress` без активности дольше порога, automation пишет комментарий и запрашивает unblock-план.
2. Если стагнация длительная и нет связанного PR, задача переводится в `status:blocked`.
3. После unblock задача возвращается в `status:ready` или `status:in-progress` вручную.

## 5) Hourly automation
Автоматизация запускается каждый час и делает цикл:
1. Проверяет `status:in-progress` non-epic issues.
2. Определяет stale-задачи по времени последнего апдейта issue.
3. Комментирует stale-ветки (ссылки на PR, если есть).
4. Переводит явно зависшие задачи в `status:blocked`.
5. Если активной работы нет:
   - пробует продвинуть валидные `status:triage` в `status:ready`.
   - если `ready` пусто, нарезает следующий доступный epic на WP.
   - берет в работу одну верхнеприоритетную задачу (`ready -> in-progress`).

Файлы автоматизации:
- `scripts/github/hourly_task_loop.sh`
- `.github/workflows/hourly-task-loop.yml`
- `docs/TASK_AUTOMATION.md`

## 6) CLI-примеры
Создать баг:
```bash
scripts/github/create_issue.sh \
  --type bug \
  --title "Search opens wrong number of slots" \
  --body-file /tmp/bug.md \
  --priority p1 \
  --area engine \
  --status triage \
  --project-title "Arena MVP Backlog"
```

Создать WP:
```bash
scripts/github/create_issue.sh \
  --type feature \
  --title "E4-WP2: Implement search slot opening rules" \
  --body-file /tmp/wp.md \
  --priority p2 \
  --area engine \
  --status ready \
  --project-title "Arena MVP Backlog"
```

Запустить hourly loop вручную локально:
```bash
DRY_RUN=1 GH_REPO="OWNER/REPO" scripts/github/hourly_task_loop.sh
```

## 7) Правило "не делать все сразу"
- Эпики не выполняются параллельно "целиком".
- В параллель идем только на уровне маленьких WP.
- WIP ограничен, чтобы задачи реально завершались, а не копились в полуготовом состоянии.
