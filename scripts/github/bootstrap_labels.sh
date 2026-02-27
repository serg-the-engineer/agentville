#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-${GH_REPO:-}}"
if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [[ -z "$REPO" ]]; then
  echo "Cannot determine repo. Pass owner/name as first arg or set GH_REPO." >&2
  exit 1
fi

if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

# name|color|description
LABELS=(
  "type:epic|5319e7|High-level multi-issue stream"
  "type:feature|1f883d|Feature implementation task"
  "type:bug|d73a4a|Functional defect"
  "type:chore|fbca04|Maintenance and housekeeping"
  "type:refactor|bfdadc|Behavior-preserving refactor"
  "type:test|0e8a16|Test-only changes"
  "type:docs|0075ca|Documentation updates"
  "status:triage|ededed|Needs triage"
  "status:ready|c2e0c6|Ready to start"
  "status:in-progress|f9d0c4|Actively being implemented"
  "status:blocked|b60205|Blocked by dependency"
  "status:review|fef2c0|In review"
  "priority:p0|b60205|Critical"
  "priority:p1|d93f0b|High"
  "priority:p2|fbca04|Medium"
  "priority:p3|0e8a16|Low"
  "area:engine|0052cc|Game engine core"
  "area:setup|1d76db|Match setup and generation"
  "area:llm|6f42c1|LLM adapter and prompts"
  "area:api|0366d6|REST APIs"
  "area:runner|9e6a03|Background orchestration"
  "area:ws|0b7285|WebSocket streaming"
  "area:db|a371f7|Database and migrations"
  "area:ui|5319e7|Frontend"
  "area:docs|0052cc|Documentation/process"
  "area:ci|2b3137|CI/CD and automation"
)

for entry in "${LABELS[@]}"; do
  IFS='|' read -r name color description <<<"$entry"
  if gh label create "$name" --repo "$REPO" --color "$color" --description "$description" >/dev/null 2>&1; then
    echo "created: $name"
  else
    gh label edit "$name" --repo "$REPO" --color "$color" --description "$description" >/dev/null
    echo "updated: $name"
  fi
done

echo "Done. Labels synced for $REPO"
