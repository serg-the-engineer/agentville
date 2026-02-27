# GITHUB_TASKS_PLAYBOOK.md

Как работать с задачами в режиме "1 разработчик + много агентов".

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
- `Status` (`Inbox`, `Ready`, `In Progress`, `In Review`, `Needs Human`, `Blocked`, `Done`)
- `Priority` (`P0..P3`)
- `Epic`, `Stream`, `Size`, `Agent`

## 2) Как заводить задачи

### 2.1 Через GitHub UI (рекомендуется для ручного планирования)
- Используй issue forms:
  - `Epic`
  - `Work Packet`
  - `Bug Report`
- Сразу выставляй labels `type:*`, `priority:*`, `area:*`, `status:*`.

### 2.2 Через CLI (рекомендуется для агентов/быстрого ввода)
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

Создать фичу/WP:
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

## 3) Ежедневный операционный цикл
1. Triage inbox (`status:triage`) -> выставить `priority`, `area`, `stream`.
2. Перевести готовые задачи в `status:ready`.
3. Выбрать 1-2 WP в `in-progress` (не больше для solo).
4. Работать строго по TDD (RED -> GREEN -> REFACTOR).
5. Если нужен ответ человека, переводить задачу в `Needs Human`, а не в `Blocked`.
6. На PR переводить задачу в `review`.
7. После merge закрывать issue (попадает в `done`).

## 4) Как мне (агенту) делегировать создание багов
Когда в ходе работы найден дефект, агент должен:
1. Сформировать воспроизводимое описание.
2. Создать issue с `type:bug`, `priority`, `area`, `status:triage`.
3. Добавить failing test reference в body.
4. Сослаться на issue в PR с фиксом.

## 5) Минимальные правила качества задач
- У любой задачи есть проверяемый `Acceptance Criteria`.
- У бага есть `Reproduction Steps` и ожидаемое/фактическое поведение.
- У WP есть раздел `Tests First`.
- Если нет тестового плана, задача не переводится в `ready`.

## 6) Рекомендуемые фильтры в Project
- `My Focus`: `Status in (Ready, In Progress)` and `Priority in (P0, P1)`
- `Blocked`: `Status = Blocked`
- `Needs Human`: `Status = Needs Human`
- `Bugs`: `label:type:bug`
- `Engine`: `label:area:engine`
- `Current Milestone`: `Stream in (E4, E5, E6)`

## 7) Правило WIP
- В работе одновременно не больше 2 issues.
- Новая задача стартует только после того, как одна из текущих вышла из `In Progress` (`Done`, `Blocked`, `Needs Human` или `In Review`).
