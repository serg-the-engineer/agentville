#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage:
  scripts/github/hourly_task_loop.sh [owner/repo]

Env knobs:
  GH_REPO            owner/repo fallback
  DRY_RUN            1 = print actions only (default: 0)
  STALE_HOURS        hours before in-progress issue is considered stale (default: 6)
  BLOCK_AFTER_HOURS  hours before stale issue is moved to blocked (default: 24)
  WIP_LIMIT          max simultaneous in-progress issues (default: 2)
  WP_BATCH_SIZE      max new WP issues per run when decomposing (default: 2)
  MAX_WP_PER_EPIC    max open WP per epic (default: 3)
USAGE
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

comment_issue() {
  local issue_number="$1"
  local body="$2"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[DRY-RUN] comment issue #$issue_number"
    return
  fi
  gh issue comment "$issue_number" --repo "$REPO" --body "$body" >/dev/null
}

move_status() {
  local issue_number="$1"
  local from_status="$2"
  local to_status="$3"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "[DRY-RUN] issue #$issue_number status:$from_status -> status:$to_status"
    return
  fi

  gh issue edit "$issue_number" --repo "$REPO" --add-label "status:${to_status}" >/dev/null
  gh issue edit "$issue_number" --repo "$REPO" --remove-label "status:${from_status}" >/dev/null 2>&1 || true
}

recent_loop_comment_exists() {
  local issue_number="$1"
  local window_seconds="$2"
  local count

  count="$({
    gh api "repos/$REPO/issues/$issue_number/comments?per_page=30" \
      --jq \
      --arg marker "$MARKER" \
      --argjson now "$NOW_EPOCH" \
      --argjson window "$window_seconds" \
      '[.[] | select((.body | contains($marker)) and (($now - (.created_at | fromdateiso8601)) < $window))] | length'
  } 2>/dev/null || echo 0)"

  [[ "$count" != "0" ]]
}

linked_prs_for_issue() {
  local issue_number="$1"
  gh api "repos/$REPO/issues/$issue_number/events?per_page=100" \
    --jq '[.[] | select(.event == "cross-referenced" and ((.source.issue.pull_request.url? // "") != "")) | .source.issue.html_url] | unique | join(", ")' \
    2>/dev/null || true
}

refresh_open_issues() {
  OPEN_ISSUES_JSON="$(gh issue list --repo "$REPO" --state open --limit 200 --json number,title,updatedAt,labels,body,url)"
}

pick_ready_candidate() {
  jq -r '
    def names: [.labels[].name];
    def has($l): (names | index($l)) != null;
    def priority_rank:
      if has("priority:p0") then 0
      elif has("priority:p1") then 1
      elif has("priority:p2") then 2
      elif has("priority:p3") then 3
      else 9 end;
    [
      .[]
      | select(has("status:ready") and (has("type:epic") | not))
      | . + {
          bug_rank: (if has("type:bug") then 0 else 1 end),
          p_rank: priority_rank
        }
    ]
    | sort_by(.bug_rank, .p_rank, .updatedAt)
    | .[0] // empty
    | "\(.number)|\(.title)|\(.url)"
  ' <<<"$OPEN_ISSUES_JSON"
}

promote_triage_candidates() {
  local candidates
  candidates="$(jq -r '
    def names: [.labels[].name];
    def has($l): (names | index($l)) != null;
    [
      .[]
      | select(has("status:triage") and (has("type:epic") | not))
      | select((.body // "") | test("Acceptance Criteria"; "i"))
      | select((.body // "") | test("Tests First|Reproduction Steps"; "i"))
      | .number
    ]
    | .[:2]
    | .[]
  ' <<<"$OPEN_ISSUES_JSON")"

  if [[ -z "$candidates" ]]; then
    return
  fi

  while IFS= read -r issue_number; do
    [[ -z "$issue_number" ]] && continue
    move_status "$issue_number" "triage" "ready"
    comment_issue "$issue_number" "$MARKER\n\nIssue moved from \`status:triage\` to \`status:ready\`: body has required sections for execution."
    log "Promoted triage -> ready for #$issue_number"
  done <<<"$candidates"
}

dependency_issues_closed() {
  local deps="$1"
  local dep

  for dep in $deps; do
    [[ -z "$dep" ]] && continue
    if [[ "$dep" == "$CURRENT_EPIC_NUMBER" ]]; then
      continue
    fi
    local dep_state
    dep_state="$({
      gh issue view "$dep" --repo "$REPO" --json state -q .state
    } 2>/dev/null || echo "OPEN")"
    if [[ "$dep_state" != "CLOSED" ]]; then
      return 1
    fi
  done

  return 0
}

next_epic_for_decomposition() {
  local epic_numbers
  epic_numbers="$(jq -r '
    def names: [.labels[].name];
    def has($l): (names | index($l)) != null;
    [ .[] | select(has("type:epic") and has("status:ready")) | .number ] | sort | .[]
  ' <<<"$OPEN_ISSUES_JSON")"

  local epic_number
  while IFS= read -r epic_number; do
    [[ -z "$epic_number" ]] && continue

    local epic_json
    epic_json="$(jq -c --argjson n "$epic_number" '.[] | select(.number == $n)' <<<"$OPEN_ISSUES_JSON")"
    [[ -z "$epic_json" ]] && continue

    local epic_title
    epic_title="$(jq -r '.title' <<<"$epic_json")"
    local epic_code
    epic_code="$(sed -E -n 's/^(E[0-9]+):.*/\1/p' <<<"$epic_title")"
    [[ -z "$epic_code" ]] && continue

    local open_wp_count
    open_wp_count="$(jq -r --arg code "$epic_code" '[.[] | select((.title | startswith($code + "-WP")) and (([.labels[].name] | index("type:epic")) == null))] | length' <<<"$OPEN_ISSUES_JSON")"
    if (( open_wp_count >= MAX_WP_PER_EPIC )); then
      continue
    fi

    local epic_body
    epic_body="$(jq -r '.body // ""' <<<"$epic_json")"
    local deps
    deps="$(grep -oE '#[0-9]+' <<<"$epic_body" | tr -d '#' | sort -un | tr '\n' ' ' || true)"

    CURRENT_EPIC_NUMBER="$epic_number"
    if dependency_issues_closed "$deps"; then
      echo "$epic_number"
      return 0
    fi
  done <<<"$epic_numbers"

  return 1
}

create_wp_from_epic() {
  local epic_number="$1"
  local epic_json
  epic_json="$(jq -c --argjson n "$epic_number" '.[] | select(.number == $n)' <<<"$OPEN_ISSUES_JSON")"

  local epic_title
  epic_title="$(jq -r '.title' <<<"$epic_json")"
  local epic_code
  epic_code="$(sed -E -n 's/^(E[0-9]+):.*/\1/p' <<<"$epic_title")"

  local area
  area="$(jq -r '[.labels[].name | select(startswith("area:"))][0] // "area:engine"' <<<"$epic_json")"
  area="${area#area:}"

  local priority
  priority="$(jq -r '[.labels[].name | select(startswith("priority:"))][0] // "priority:p2"' <<<"$epic_json")"
  priority="${priority#priority:}"

  local epic_body
  epic_body="$(jq -r '.body // ""' <<<"$epic_json")"
  local epic_result
  epic_result="$(awk '/^## Result/{getline; print; exit}' <<<"$epic_body")"
  if [[ -z "$epic_result" ]]; then
    epic_result="$epic_title"
  fi

  local max_wp_index
  max_wp_index="$({
    gh issue list --repo "$REPO" --state all --limit 200 --json title \
      --jq --arg code "$epic_code" '[.[].title | (match("^" + $code + "-WP([0-9]+):")? | .captures[0].string | tonumber)] | max // 0'
  } 2>/dev/null || echo 0)"

  local open_wp_count
  open_wp_count="$(jq -r --arg code "$epic_code" '[.[] | select((.title | startswith($code + "-WP")) and (([.labels[].name] | index("type:epic")) == null))] | length' <<<"$OPEN_ISSUES_JSON")"

  local create_count="$WP_BATCH_SIZE"
  local remaining=$((MAX_WP_PER_EPIC - open_wp_count))
  if (( remaining < create_count )); then
    create_count="$remaining"
  fi

  if (( create_count <= 0 )); then
    return
  fi

  local idx
  for ((idx = 1; idx <= create_count; idx++)); do
    local wp_number=$((max_wp_index + idx))
    local wp_title_suffix
    local wp_objective

    case "$wp_number" in
      1)
        wp_title_suffix="Contract tests and scaffolding"
        wp_objective="Подготовить тестовый каркас и минимальные контракты для старта реализации epic без изменения внешнего поведения."
        ;;
      2)
        wp_title_suffix="Minimal implementation"
        wp_objective="Реализовать минимальный рабочий срез epic под существующие тесты и acceptance criteria."
        ;;
      3)
        wp_title_suffix="Integration and hardening"
        wp_objective="Закрыть интеграционные сценарии, стабилизацию и документирование результата."
        ;;
      *)
        wp_title_suffix="Follow-up slice #$wp_number"
        wp_objective="Выполнить следующий минимальный срез epic с проверяемым AC и тест-планом."
        ;;
    esac

    local wp_title="${epic_code}-WP${wp_number}: ${wp_title_suffix}"
    local body_file
    body_file="$(mktemp "/tmp/${epic_code}-wp.XXXXXX")"

    cat > "$body_file" <<BODY
# ${wp_title}

## Parent Epic
- #${epic_number}

## Objective
${wp_objective}

## Context
${epic_result}

## Scope
- In scope: минимальный вертикальный срез, нужный для продвижения epic.
- Out of scope: полное завершение всего epic в одном WP.

## Acceptance Criteria
- [ ] Реализован один проверяемый срез результата.
- [ ] Нет регрессий по существующим тестам.
- [ ] Изменения ограничены scope этого WP.

## Tests First
- [ ] Добавить failing tests перед реализацией (RED -> GREEN -> REFACTOR).

## Validation Commands
- uv run --with pytest pytest -q
BODY

    if [[ "$DRY_RUN" == "1" ]]; then
      log "[DRY-RUN] create issue: $wp_title (priority:$priority area:$area)"
    else
      scripts/github/create_issue.sh \
        --repo "$REPO" \
        --type feature \
        --title "$wp_title" \
        --body-file "$body_file" \
        --priority "$priority" \
        --area "$area" \
        --status ready >/dev/null
      log "Created WP issue: $wp_title"
    fi
  done
}

claim_issue() {
  local issue_number="$1"
  local issue_title="$2"

  move_status "$issue_number" "ready" "in-progress"
  comment_issue "$issue_number" "$MARKER\n\nQueue claim: issue moved to \`status:in-progress\` for execution.\n\nTitle: ${issue_title}"
  log "Claimed issue #$issue_number -> in-progress"
}

require_cmd gh
require_cmd jq

REPO="${1:-${GH_REPO:-}}"
if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [[ -z "$REPO" ]]; then
  usage
  echo "Cannot determine repo. Pass owner/repo or set GH_REPO." >&2
  exit 1
fi

if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

MARKER="[hourly-task-loop]"
NOW_EPOCH="$(date -u +%s)"

DRY_RUN="${DRY_RUN:-0}"
STALE_HOURS="${STALE_HOURS:-6}"
BLOCK_AFTER_HOURS="${BLOCK_AFTER_HOURS:-24}"
WIP_LIMIT="${WIP_LIMIT:-2}"
WP_BATCH_SIZE="${WP_BATCH_SIZE:-2}"
MAX_WP_PER_EPIC="${MAX_WP_PER_EPIC:-3}"

log "Starting hourly task loop for $REPO (dry_run=$DRY_RUN)"

refresh_open_issues

in_progress_json="$(jq '
  def names: [.labels[].name];
  def has($l): (names | index($l)) != null;
  [ .[] | select(has("status:in-progress") and (has("type:epic") | not)) ]
' <<<"$OPEN_ISSUES_JSON")"
in_progress_count="$(jq 'length' <<<"$in_progress_json")"
log "Open in-progress non-epic issues: $in_progress_count"

stale_seconds=$((STALE_HOURS * 3600))
block_seconds=$((BLOCK_AFTER_HOURS * 3600))

stale_json="$(jq --argjson now "$NOW_EPOCH" --argjson stale "$stale_seconds" '
  def names: [.labels[].name];
  def has($l): (names | index($l)) != null;
  [
    .[]
    | select(has("status:in-progress") and (has("type:epic") | not))
    | . + { age_seconds: ($now - (.updatedAt | fromdateiso8601)) }
    | select(.age_seconds >= $stale)
  ]
' <<<"$OPEN_ISSUES_JSON")"

stale_count="$(jq 'length' <<<"$stale_json")"
if (( stale_count > 0 )); then
  log "Stale in-progress issues: $stale_count"
fi

while IFS='|' read -r issue_number age_seconds issue_title; do
  [[ -z "$issue_number" ]] && continue
  age_hours=$((age_seconds / 3600))
  linked_prs="$(linked_prs_for_issue "$issue_number")"
  recent_window="$stale_seconds"

  if recent_loop_comment_exists "$issue_number" "$recent_window"; then
    log "Skip comment for #$issue_number (recent loop comment exists)"
    continue
  fi

  if (( age_seconds >= block_seconds )) && [[ -z "$linked_prs" ]]; then
    move_status "$issue_number" "in-progress" "blocked"
    comment_issue "$issue_number" "$MARKER\n\nIssue appears stalled for ~${age_hours}h without linked PR activity. Moved to \`status:blocked\`.\n\nPlease add unblock plan or return to \`status:ready\` with updated scope."
    log "Moved stale issue #$issue_number to blocked"
  else
    if [[ -n "$linked_prs" ]]; then
      comment_issue "$issue_number" "$MARKER\n\nIssue has no updates for ~${age_hours}h. Linked PR(s): ${linked_prs}\n\nPlease post a short progress update or unblock plan."
    else
      comment_issue "$issue_number" "$MARKER\n\nIssue has no updates for ~${age_hours}h and no linked PR found.\n\nPlease post a short progress update or mark blocker."
    fi
    log "Commented stale issue #$issue_number"
  fi
done < <(jq -r '.[] | "\(.number)|\(.age_seconds)|\(.title)"' <<<"$stale_json")

refresh_open_issues
in_progress_count="$(jq '
  def names: [.labels[].name];
  def has($l): (names | index($l)) != null;
  [ .[] | select(has("status:in-progress") and (has("type:epic") | not)) ] | length
' <<<"$OPEN_ISSUES_JSON")"

if (( in_progress_count >= WIP_LIMIT )); then
  log "WIP limit reached ($in_progress_count/$WIP_LIMIT). Exit."
  exit 0
fi

if (( in_progress_count > 0 )); then
  log "Active work exists ($in_progress_count issue(s)). New claim is skipped by policy."
  exit 0
fi

promote_triage_candidates
refresh_open_issues

candidate_line="$(pick_ready_candidate || true)"
if [[ -z "$candidate_line" ]]; then
  log "No ready non-epic issue found. Trying to decompose next eligible epic."
  if epic_number="$(next_epic_for_decomposition)"; then
    log "Decomposing epic #$epic_number"
    create_wp_from_epic "$epic_number"
    refresh_open_issues
    candidate_line="$(pick_ready_candidate || true)"
  else
    log "No eligible epic found for decomposition. Nothing to claim."
    exit 0
  fi
fi

if [[ -z "$candidate_line" ]]; then
  log "Ready queue is still empty after decomposition. Exit."
  exit 0
fi

IFS='|' read -r candidate_number candidate_title candidate_url <<<"$candidate_line"
claim_issue "$candidate_number" "$candidate_title"

log "Done. Claimed: #$candidate_number ($candidate_url)"
