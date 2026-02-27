#!/usr/bin/env bash
set -euo pipefail

OWNER="${1:-${GH_PROJECT_OWNER:-@me}}"
TITLE="${2:-Arena MVP Backlog}"
REPO="${3:-${GH_REPO:-}}"

if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

# Requires project scope for project operations.
if ! gh auth status -h github.com 2>/dev/null | rg -q "project"; then
  echo "Token may be missing 'project' scope. Run: gh auth refresh -s project" >&2
fi

PROJECT_NUMBER="$(gh project create --owner "$OWNER" --title "$TITLE" --format json --jq '.number')"
if [[ -z "$PROJECT_NUMBER" ]]; then
  echo "Failed to create project." >&2
  exit 1
fi

echo "Created project #$PROJECT_NUMBER for owner '$OWNER' with title '$TITLE'"

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [[ -n "$REPO" ]]; then
  gh project link "$PROJECT_NUMBER" --owner "$OWNER" --repo "$REPO" >/dev/null
  echo "Linked project to repo: $REPO"
fi

create_field() {
  local name="$1"
  local dtype="$2"
  local options="${3:-}"

  if [[ -n "$options" ]]; then
    gh project field-create "$PROJECT_NUMBER" --owner "$OWNER" --name "$name" --data-type "$dtype" --single-select-options "$options" >/dev/null
  else
    gh project field-create "$PROJECT_NUMBER" --owner "$OWNER" --name "$name" --data-type "$dtype" >/dev/null
  fi
  echo "field: $name"
}

create_field "Status" "SINGLE_SELECT" "Inbox,Ready,In Progress,In Review,Needs Human,Blocked,Done"
create_field "Priority" "SINGLE_SELECT" "P0,P1,P2,P3"
create_field "Epic" "TEXT"
create_field "Stream" "SINGLE_SELECT" "E1,E2,E3,E4,E5,E6,E7,E8,E9,E10"
create_field "Size" "SINGLE_SELECT" "XS,S,M,L,XL"
create_field "Agent" "TEXT"

echo "Done. Open project in browser:"
gh project view "$PROJECT_NUMBER" --owner "$OWNER" --web
