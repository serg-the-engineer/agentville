from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_AUTOMATION_DIR = Path(__file__).resolve().parents[1] / "scripts" / "automation"
if str(SCRIPTS_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_AUTOMATION_DIR))

from work_queue_selector import DeliverySnapshot, IssueCandidate, PullRequestCandidate, select_next_action


def make_issue(
    number: int,
    *,
    issue_type: str = "task",
    priority: str = "p2",
    status: str = "ready",
    parent_epic: int | None = None,
    approval_granted: bool = False,
    updated_at: str = "2026-02-27T09:00:00Z",
) -> IssueCandidate:
    return IssueCandidate(
        number=number,
        title=f"issue-{number}",
        issue_type=issue_type,
        priority=priority,
        status=status,
        parent_epic=parent_epic,
        approval_granted=approval_granted,
        updated_at=updated_at,
    )


def make_pr(
    number: int,
    *,
    priority: str = "p2",
    updated_at: str = "2026-02-27T09:00:00Z",
) -> PullRequestCandidate:
    return PullRequestCandidate(
        number=number,
        title=f"pr-{number}",
        priority=priority,
        updated_at=updated_at,
    )


def test_review_prs_preempt_other_work() -> None:
    snapshot = DeliverySnapshot(
        review_prs=(make_pr(11, priority="p1"),),
        issues=(make_issue(21, priority="p0"),),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "review_pr"
    assert decision.target_number == 11


def test_fix_pr_is_selected_when_no_review_prs() -> None:
    snapshot = DeliverySnapshot(
        fix_prs=(make_pr(12, priority="p1"),),
        issues=(make_issue(22, priority="p0"),),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "fix_pr"
    assert decision.target_number == 12


def test_wip_limit_stops_new_work() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(30, issue_type="epic", status="in-progress"),
            make_issue(31, issue_type="epic", status="in-progress"),
            make_issue(32, status="ready"),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "stop"
    assert "epic" in decision.reason


def test_two_in_progress_tasks_also_stop_new_work() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(33, status="in-progress"),
            make_issue(34, status="in-progress"),
            make_issue(35, status="ready"),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "stop"
    assert "two tasks" in decision.reason


def test_higher_priority_task_beats_active_epic() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(40, issue_type="epic", priority="p2", status="in-progress"),
            make_issue(41, priority="p1"),
            make_issue(42, priority="p2", parent_epic=40, approval_granted=True),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "implement_task"
    assert decision.target_number == 41


def test_active_epic_does_not_start_second_epic() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(45, issue_type="epic", priority="p2", status="in-progress"),
            make_issue(46, issue_type="epic", priority="p0"),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "stop"
    assert "active epic" in decision.reason


def test_active_epic_prefers_child_task_when_no_higher_priority_exists() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(
                50,
                issue_type="epic",
                priority="p1",
                status="in-progress",
                approval_granted=True,
            ),
            make_issue(51, priority="p1", parent_epic=50, approval_granted=True),
            make_issue(52, priority="p2"),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "implement_task"
    assert decision.target_number == 51


def test_unapproved_epic_is_selected_for_planning_when_it_is_top_priority() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(60, issue_type="epic", priority="p0"),
            make_issue(61, priority="p1"),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "plan_epic"
    assert decision.target_number == 60


def test_task_under_unapproved_epic_is_not_actionable() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(70, issue_type="epic", priority="p1"),
            make_issue(71, priority="p0", parent_epic=70),
            make_issue(72, priority="p2"),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "plan_epic"
    assert decision.target_number == 70


def test_approved_epic_with_ready_child_prefers_child_task() -> None:
    snapshot = DeliverySnapshot(
        issues=(
            make_issue(80, issue_type="epic", priority="p1", approval_granted=True),
            make_issue(81, priority="p1", parent_epic=80, approval_granted=True),
        ),
    )

    decision = select_next_action(snapshot)

    assert decision.action == "implement_task"
    assert decision.target_number == 81
