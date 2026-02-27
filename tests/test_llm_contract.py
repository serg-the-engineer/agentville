from __future__ import annotations

from arena.enums import ActionType
from arena.llm_contract import ACTION_JSON_SCHEMA


def test_action_schema_lists_only_supported_llm_action_types() -> None:
    variants = ACTION_JSON_SCHEMA["properties"]["actions"]["items"]["oneOf"]
    action_types = {
        variant["properties"]["type"]["const"]
        for variant in variants
    }

    assert action_types == {
        ActionType.DEFEND.value,
        ActionType.ATTACK.value,
        ActionType.STEAL.value,
        ActionType.SEARCH.value,
        ActionType.INSPECT_ITEM.value,
        ActionType.ACTIVATE_ITEM.value,
        ActionType.DROP_ITEM.value,
        ActionType.PICKUP_ITEM.value,
        ActionType.BROADCAST.value,
    }
    assert ActionType.NO_OP.value not in action_types


def test_action_schema_requires_payload_fields_per_action_type() -> None:
    variants = {
        variant["properties"]["type"]["const"]: variant
        for variant in ACTION_JSON_SCHEMA["properties"]["actions"]["items"]["oneOf"]
    }

    assert variants[ActionType.ATTACK.value]["required"] == ["type", "target_agent_id"]
    assert variants[ActionType.STEAL.value]["required"] == ["type", "target_agent_id"]
    assert variants[ActionType.BROADCAST.value]["required"] == ["type", "text"]

    for action_type in (
        ActionType.INSPECT_ITEM.value,
        ActionType.ACTIVATE_ITEM.value,
        ActionType.DROP_ITEM.value,
        ActionType.PICKUP_ITEM.value,
    ):
        assert variants[action_type]["required"] == ["type", "item_id"]

    for action_type in (ActionType.DEFEND.value, ActionType.SEARCH.value):
        assert variants[action_type]["required"] == ["type"]
