from __future__ import annotations

import json
from typing import Any

from arena.enums import ActionType
from arena.models import Action


ACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["actions", "memory_file"],
    "additionalProperties": False,
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type"],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string"},
                    "target_agent_id": {"type": "string"},
                    "item_id": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
        },
        "memory_file": {"type": "string"},
    },
}


def trim_memory(memory_text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(memory_text)
    if len(memory_text) <= max_chars:
        return memory_text, False

    prefix = "Memory was truncated.\n"
    tail_budget = max(0, max_chars - len(prefix))
    tail = memory_text[-tail_budget:] if tail_budget else ""
    trimmed = f"{prefix}{tail}"
    return trimmed[:max_chars], True


def parse_llm_turn_response(
    raw_text: str,
    effective_agency: int,
    allowed_actions: set[ActionType],
) -> tuple[list[Action], str, list[str]]:
    errors: list[str] = []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return [], "", ["invalid_json"]

    if not isinstance(payload, dict):
        return [], "", ["payload_must_be_object"]

    raw_actions = payload.get("actions")
    memory_file = payload.get("memory_file", "")

    if not isinstance(raw_actions, list):
        errors.append("actions_must_be_array")
        raw_actions = []

    if not isinstance(memory_file, str):
        errors.append("memory_file_must_be_string")
        memory_file = ""

    parsed_actions: list[Action] = []
    for idx, raw_action in enumerate(raw_actions):
        if idx >= effective_agency:
            errors.append("actions_over_effective_agency")
            break
        if not isinstance(raw_action, dict):
            errors.append(f"action_{idx}_must_be_object")
            parsed_actions.append(Action(action_type=ActionType.NO_OP))
            continue

        raw_type = raw_action.get("type")
        try:
            action_type = ActionType(str(raw_type))
        except ValueError:
            errors.append(f"action_{idx}_unknown_type")
            parsed_actions.append(Action(action_type=ActionType.NO_OP))
            continue

        if action_type not in allowed_actions:
            errors.append(f"action_{idx}_not_allowed")
            parsed_actions.append(Action(action_type=ActionType.NO_OP))
            continue

        parsed_actions.append(
            Action(
                action_type=action_type,
                target_agent_id=as_str_or_none(raw_action.get("target_agent_id")),
                item_id=as_str_or_none(raw_action.get("item_id")),
                text=as_str_or_none(raw_action.get("text")),
            )
        )

    return parsed_actions, memory_file, errors


def as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None
