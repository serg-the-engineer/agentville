from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PRIORITY_RANK = {
    "p0": 0,
    "p1": 1,
    "p2": 2,
    "p3": 3,
}

READY_STATUS = "ready"
IN_PROGRESS_STATUS = "in-progress"


@dataclass(slots=True, frozen=True)
class PullRequestCandidate:
    number: int
    title: str
    priority: str = "p3"
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PullRequestCandidate:
        return cls(
            number=int(payload["number"]),
            title=str(payload["title"]),
            priority=str(payload.get("priority", "p3")).lower(),
            updated_at=str(payload.get("updated_at", "")),
        )


@dataclass(slots=True, frozen=True)
class IssueCandidate:
    number: int
    title: str
    issue_type: str
    priority: str = "p3"
    status: str = READY_STATUS
    parent_epic: int | None = None
    approval_granted: bool = False
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> IssueCandidate:
        parent_epic = payload.get("parent_epic")
        return cls(
            number=int(payload["number"]),
            title=str(payload["title"]),
            issue_type=str(payload.get("issue_type", "task")).lower(),
            priority=str(payload.get("priority", "p3")).lower(),
            status=str(payload.get("status", READY_STATUS)).lower(),
            parent_epic=int(parent_epic) if parent_epic is not None else None,
            approval_granted=bool(payload.get("approval_granted", False)),
            updated_at=str(payload.get("updated_at", "")),
        )


@dataclass(slots=True, frozen=True)
class DeliverySnapshot:
    review_prs: tuple[PullRequestCandidate, ...] = ()
    fix_prs: tuple[PullRequestCandidate, ...] = ()
    issues: tuple[IssueCandidate, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeliverySnapshot:
        return cls(
            review_prs=tuple(
                PullRequestCandidate.from_dict(item) for item in payload.get("review_prs", [])
            ),
            fix_prs=tuple(PullRequestCandidate.from_dict(item) for item in payload.get("fix_prs", [])),
            issues=tuple(IssueCandidate.from_dict(item) for item in payload.get("issues", [])),
        )


@dataclass(slots=True, frozen=True)
class DeliveryDecision:
    action: str
    reason: str
    target_kind: str | None = None
    target_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_next_action(snapshot: DeliverySnapshot) -> DeliveryDecision:
    review_pr = _pick_pr(snapshot.review_prs)
    if review_pr is not None:
        return DeliveryDecision(
            action="review_pr",
            reason="Found pull requests waiting for review; review work always has priority.",
            target_kind="pull_request",
            target_number=review_pr.number,
        )

    fix_pr = _pick_pr(snapshot.fix_prs)
    if fix_pr is not None:
        return DeliveryDecision(
            action="fix_pr",
            reason="No review queue exists, so the next priority is addressing requested PR changes.",
            target_kind="pull_request",
            target_number=fix_pr.number,
        )

    active_epics = _active_epics(snapshot.issues)
    if len(active_epics) > 1:
        return DeliveryDecision(
            action="stop",
            reason="WIP limit exceeded: more than one epic is already in progress.",
        )

    in_progress_tasks = [issue for issue in snapshot.issues if _is_task(issue) and issue.status == IN_PROGRESS_STATUS]
    if len(in_progress_tasks) >= 2:
        return DeliveryDecision(
            action="stop",
            reason="WIP limit exceeded: two tasks are already in progress.",
        )

    active_epic = active_epics[0] if active_epics else None
    issues_by_number = {issue.number: issue for issue in snapshot.issues}
    actionable_issues = [
        issue for issue in snapshot.issues if _is_actionable(issue, issues_by_number, snapshot.issues)
    ]

    if active_epic is not None:
        higher_priority_issues = [
            issue
            for issue in actionable_issues
            if _is_task(issue) and _priority_rank(issue.priority) < _priority_rank(active_epic.priority)
        ]
        if higher_priority_issues:
            chosen_issue = _pick_issue(higher_priority_issues)
            return _decision_for_issue(
                chosen_issue,
                "A higher-priority ready issue takes precedence over the active epic.",
            )

        active_epic_tasks = [
            issue for issue in actionable_issues if issue.parent_epic == active_epic.number
        ]
        if active_epic_tasks:
            chosen_issue = _pick_issue(active_epic_tasks)
            return _decision_for_issue(
                chosen_issue,
                "The active epic stays preferred while no higher-priority issue exists.",
            )

        return DeliveryDecision(
            action="stop",
            reason="An active epic exists, but there is no actionable task to advance it.",
        )

    chosen_issue = _pick_issue(actionable_issues)
    if chosen_issue is None:
        return DeliveryDecision(
            action="stop",
            reason="No actionable pull request or issue was found.",
        )

    return _decision_for_issue(
        chosen_issue,
        "Selected the highest-priority actionable item with all required gates satisfied.",
    )


def _decision_for_issue(issue: IssueCandidate, reason: str) -> DeliveryDecision:
    if issue.issue_type == "epic":
        action = "implement_epic" if issue.approval_granted else "plan_epic"
    else:
        action = "implement_task"

    return DeliveryDecision(
        action=action,
        reason=reason,
        target_kind="issue",
        target_number=issue.number,
    )


def _pick_pr(prs: tuple[PullRequestCandidate, ...]) -> PullRequestCandidate | None:
    if not prs:
        return None
    return min(prs, key=lambda pr: (_priority_rank(pr.priority), pr.updated_at, pr.number))


def _pick_issue(issues: list[IssueCandidate]) -> IssueCandidate | None:
    if not issues:
        return None
    return min(issues, key=lambda issue: (_priority_rank(issue.priority), issue.updated_at, issue.number))


def _active_epics(issues: tuple[IssueCandidate, ...]) -> list[IssueCandidate]:
    return [issue for issue in issues if issue.issue_type == "epic" and issue.status == IN_PROGRESS_STATUS]


def _is_task(issue: IssueCandidate) -> bool:
    return issue.issue_type != "epic"


def _is_actionable(
    issue: IssueCandidate,
    issues_by_number: dict[int, IssueCandidate],
    all_issues: tuple[IssueCandidate, ...],
) -> bool:
    if issue.status != READY_STATUS:
        return False

    if issue.issue_type == "epic":
        return not _epic_has_actionable_children(issue.number, all_issues, issues_by_number)

    if issue.parent_epic is None:
        return True

    parent_epic = issues_by_number.get(issue.parent_epic)
    if parent_epic is None:
        return False

    return parent_epic.approval_granted


def _epic_has_actionable_children(
    epic_number: int,
    all_issues: tuple[IssueCandidate, ...],
    issues_by_number: dict[int, IssueCandidate],
) -> bool:
    return any(
        issue.parent_epic == epic_number and _is_actionable_child(issue, issues_by_number)
        for issue in all_issues
    )


def _is_actionable_child(
    issue: IssueCandidate,
    issues_by_number: dict[int, IssueCandidate],
) -> bool:
    if issue.issue_type == "epic" or issue.status != READY_STATUS or issue.parent_epic is None:
        return False

    parent_epic = issues_by_number.get(issue.parent_epic)
    return parent_epic is not None and parent_epic.approval_granted


def _priority_rank(priority: str) -> int:
    return PRIORITY_RANK.get(priority.lower(), 99)
