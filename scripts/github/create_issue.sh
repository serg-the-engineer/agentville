#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage:
  scripts/github/create_issue.sh \
    --type <bug|feature|epic|chore> \
    --title "..." \
    [--body-file path.md] \
    [--project-title "Arena MVP Backlog"] \
    [--priority <p0|p1|p2|p3>] \
    [--area <engine|setup|llm|api|runner|ws|db|ui|docs|ci>] \
    [--status <triage|ready|in-progress|blocked|review>] \
    [--label custom]...

Repo resolution order:
  1) --repo owner/name
  2) GH_REPO env var
  3) gh repo view
USAGE
}

REPO="${GH_REPO:-}"
TYPE=""
TITLE=""
BODY_FILE=""
PRIORITY=""
AREA=""
STATUS="triage"
PROJECT_TITLE=""
EXTRA_LABELS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --type) TYPE="$2"; shift 2 ;;
    --title) TITLE="$2"; shift 2 ;;
    --body-file) BODY_FILE="$2"; shift 2 ;;
    --priority) PRIORITY="$2"; shift 2 ;;
    --area) AREA="$2"; shift 2 ;;
    --status) STATUS="$2"; shift 2 ;;
    --project-title) PROJECT_TITLE="$2"; shift 2 ;;
    --label) EXTRA_LABELS+=("$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$TYPE" || -z "$TITLE" ]]; then
  echo "--type and --title are required." >&2
  usage
  exit 1
fi

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [[ -z "$REPO" ]]; then
  echo "Cannot determine repo. Pass --repo owner/name or set GH_REPO." >&2
  exit 1
fi

if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

case "$TYPE" in
  bug) TYPE_LABEL="type:bug" ;;
  feature) TYPE_LABEL="type:feature" ;;
  epic) TYPE_LABEL="type:epic" ;;
  chore) TYPE_LABEL="type:chore" ;;
  *) echo "Unsupported --type: $TYPE" >&2; exit 1 ;;
esac

LABELS=("$TYPE_LABEL" "status:${STATUS}")
if [[ -n "$PRIORITY" ]]; then
  LABELS+=("priority:${PRIORITY}")
fi
if [[ -n "$AREA" ]]; then
  LABELS+=("area:${AREA}")
fi
if [[ ${#EXTRA_LABELS[@]} -gt 0 ]]; then
  LABELS+=("${EXTRA_LABELS[@]}")
fi

ARGS=(issue create --repo "$REPO" --title "$TITLE")
if [[ -n "$BODY_FILE" ]]; then
  ARGS+=(--body-file "$BODY_FILE")
fi
if [[ -n "$PROJECT_TITLE" ]]; then
  ARGS+=(--project "$PROJECT_TITLE")
fi
for label in "${LABELS[@]}"; do
  ARGS+=(--label "$label")
done

gh "${ARGS[@]}"
