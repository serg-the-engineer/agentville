from __future__ import annotations

from collections.abc import Iterator

from arena.engine import GameEngine
from arena.enums import ActionType, EffectType, LogVisibility, RoomStatus
from arena.models import (
    Action,
    AgentEffect,
    AgentState,
    ItemTemplate,
    RoomItem,
    RoomState,
    SearchSlot,
)


def dice_from(values: list[int]) -> Iterator[int]:
    for value in values:
        yield value


def make_room(*, inventory_slots: int = 2) -> RoomState:
    return RoomState(
        id="room-1",
        status=RoomStatus.PLAYING,
        current_turn=1,
        max_turns=10,
        inventory_slots=inventory_slots,
        rng_seed=42,
    )


def add_agent(
    room: RoomState,
    agent_id: str,
    *,
    strength: int = 1,
    attentiveness: int = 1,
    agency: int = 1,
) -> None:
    room.agents[agent_id] = AgentState(
        id=agent_id,
        name=agent_id,
        base_strength=strength,
        base_attentiveness=attentiveness,
        base_agency=agency,
    )


def add_template(room: RoomState, template_id: str, *, price: int = 1) -> None:
    room.item_templates[template_id] = ItemTemplate(
        id=template_id,
        effect_type=EffectType.STAT_BUFF,
        effect_payload={},
        price=price,
        is_noticeable=False,
    )


def add_item(
    room: RoomState,
    item_id: str,
    owner_agent_id: str | None,
    template_id: str = "tpl-1",
) -> None:
    room.items[item_id] = RoomItem(
        id=item_id,
        template_id=template_id,
        obfuscated_name=item_id,
        appearance="shape",
        activation_desc="desc",
        owner_agent_id=owner_agent_id,
    )


def test_slot_then_priority_then_next_slot_order() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", agency=2)
    add_agent(room, "b", agency=2)
    add_item(room, "item-b", owner_agent_id="b")

    dice = dice_from([10, 1])
    engine = GameEngine(seed=123, dice_roller=lambda: next(dice))
    result = engine.execute_round(
        room,
        {
            "a": [
                Action(ActionType.ATTACK, target_agent_id="b"),
                Action(ActionType.BROADCAST, text="a second"),
            ],
            "b": [
                Action(ActionType.DEFEND),
                Action(ActionType.BROADCAST, text="b second"),
            ],
        },
    )

    event_types = [event.event_type for event in result.events if event.slot_index > 0]
    assert event_types == ["defend_applied", "attack_resolved", "broadcast", "broadcast"]
    assert [e.payload["agent_id"] for e in result.events if e.event_type == "broadcast"] == ["a", "b"]


def test_attack_tie_favors_defender() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "attacker", strength=1)
    add_agent(room, "target", strength=1)
    add_item(room, "item-target", owner_agent_id="target")

    dice = dice_from([5, 5])
    engine = GameEngine(seed=7, dice_roller=lambda: next(dice))
    result = engine.execute_round(
        room,
        {"attacker": [Action(ActionType.ATTACK, target_agent_id="target")]},
    )

    attack_event = next(event for event in result.events if event.event_type == "attack_resolved")
    assert attack_event.payload["success"] is False
    assert room.items["item-target"].owner_agent_id == "target"


def test_steal_uses_attentiveness_not_strength() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "thief", strength=1, attentiveness=5)
    add_agent(room, "target", strength=9, attentiveness=1)
    add_item(room, "item-target", owner_agent_id="target")

    dice = dice_from([3, 3])
    engine = GameEngine(seed=77, dice_roller=lambda: next(dice))
    result = engine.execute_round(
        room,
        {"thief": [Action(ActionType.STEAL, target_agent_id="target")]},
    )

    steal_event = next(event for event in result.events if event.event_type == "steal_resolved")
    assert steal_event.payload["success"] is True
    assert room.items["item-target"].owner_agent_id == "thief"


def test_stunned_reduces_only_next_round_effective_agency_by_one() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "attacker", strength=10, agency=1)
    add_agent(room, "target", strength=1, agency=2)
    add_item(room, "item-target", owner_agent_id="target")

    dice_1 = dice_from([10, 1])
    engine = GameEngine(seed=88, dice_roller=lambda: next(dice_1))
    engine.execute_round(
        room,
        {"attacker": [Action(ActionType.ATTACK, target_agent_id="target")]},
    )

    dice_2 = dice_from([1, 1])
    engine._dice_roller = lambda: next(dice_2)  # noqa: SLF001 - test setup
    round_2 = engine.execute_round(
        room,
        {
            "target": [
                Action(ActionType.BROADCAST, text="first"),
                Action(ActionType.BROADCAST, text="second"),
            ]
        },
    )
    assert round_2.effective_agency["target"] == 1

    dice_3 = dice_from([1, 1])
    engine._dice_roller = lambda: next(dice_3)  # noqa: SLF001 - test setup
    round_3 = engine.execute_round(room, {})
    assert round_3.effective_agency["target"] == 2


def test_conditional_logs_for_steal_depend_on_perception_rolls() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", attentiveness=2)  # thief
    add_agent(room, "b", attentiveness=1)  # target
    add_agent(room, "c", attentiveness=1)  # observer success
    add_agent(room, "d", attentiveness=1)  # observer fail
    add_item(room, "item-target", owner_agent_id="b")

    dice = dice_from([8, 1, 8, 1])
    engine = GameEngine(seed=91, dice_roller=lambda: next(dice))
    result = engine.execute_round(
        room,
        {"a": [Action(ActionType.STEAL, target_agent_id="b")]},
    )

    conditional_recipients = {
        log.recipient_agent_id
        for log in result.logs
        if log.visibility == LogVisibility.CONDITIONAL
    }
    assert conditional_recipients == {"c"}


def test_inventory_overflow_to_floor_and_pickup_respects_slots() -> None:
    room = make_room(inventory_slots=1)
    add_template(room, "tpl-1")
    add_agent(room, "a", strength=10, agency=2)
    add_agent(room, "b", strength=1, agency=1)
    add_item(room, "item-a", owner_agent_id="a")
    add_item(room, "item-b", owner_agent_id="b")

    dice = dice_from([10, 1])
    engine = GameEngine(seed=100, dice_roller=lambda: next(dice))
    result = engine.execute_round(
        room,
        {
            "a": [
                Action(ActionType.ATTACK, target_agent_id="b"),
                Action(ActionType.PICKUP_ITEM, item_id="item-b"),
            ]
        },
    )

    assert room.items["item-b"].owner_agent_id is None
    assert any(
        log.visibility == LogVisibility.PRIVATE
        and log.recipient_agent_id == "a"
        and "слотов" in log.message
        for log in result.logs
    )


def test_results_are_sum_of_item_prices() -> None:
    room = make_room()
    add_template(room, "cheap", price=1)
    add_template(room, "expensive", price=5)
    add_agent(room, "a")
    add_agent(room, "b")
    add_item(room, "item-1", owner_agent_id="a", template_id="cheap")
    add_item(room, "item-2", owner_agent_id="a", template_id="expensive")
    add_item(room, "item-3", owner_agent_id="b", template_id="cheap")

    engine = GameEngine(seed=1)
    scores = engine.calculate_results(room)

    assert [(score.agent_id, score.total_price) for score in scores] == [("a", 6), ("b", 1)]


def test_search_total_up_to_six_opens_zero_slots() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", attentiveness=0, agency=1)
    add_item(room, "loot-1", owner_agent_id=None)
    room.search_slots = [SearchSlot(index=1, item_id="loot-1", opened=False)]

    dice = dice_from([6])
    engine = GameEngine(seed=1, dice_roller=lambda: next(dice))
    result = engine.execute_round(room, {"a": [Action(ActionType.SEARCH)]})

    event = next(event for event in result.events if event.event_type == "search_resolved")
    assert event.payload["opened_slots"] == 0
    assert event.payload["found_item_ids"] == []
    assert room.items["loot-1"].owner_agent_id is None


def test_search_total_seven_to_nine_opens_one_slot() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", attentiveness=0, agency=1)
    add_item(room, "loot-1", owner_agent_id=None)
    room.search_slots = [SearchSlot(index=1, item_id="loot-1", opened=False)]

    dice = dice_from([7])
    engine = GameEngine(seed=2, dice_roller=lambda: next(dice))
    result = engine.execute_round(room, {"a": [Action(ActionType.SEARCH)]})

    event = next(event for event in result.events if event.event_type == "search_resolved")
    assert event.payload["opened_slots"] == 1
    assert event.payload["found_item_ids"] == ["loot-1"]
    assert room.items["loot-1"].owner_agent_id == "a"


def test_search_total_ten_or_more_opens_two_slots() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", attentiveness=0, agency=1)
    add_item(room, "loot-1", owner_agent_id=None)
    add_item(room, "loot-2", owner_agent_id=None)
    room.search_slots = [
        SearchSlot(index=1, item_id="loot-1", opened=False),
        SearchSlot(index=2, item_id="loot-2", opened=False),
    ]

    dice = dice_from([10])
    engine = GameEngine(seed=3, dice_roller=lambda: next(dice))
    result = engine.execute_round(room, {"a": [Action(ActionType.SEARCH)]})

    event = next(event for event in result.events if event.event_type == "search_resolved")
    assert event.payload["opened_slots"] == 2
    assert sorted(event.payload["found_item_ids"]) == ["loot-1", "loot-2"]
    assert room.items["loot-1"].owner_agent_id == "a"
    assert room.items["loot-2"].owner_agent_id == "a"


def test_search_uses_attentiveness_modifier() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", attentiveness=1, agency=1)
    add_item(room, "loot-1", owner_agent_id=None)
    room.search_slots = [SearchSlot(index=1, item_id="loot-1", opened=False)]

    dice = dice_from([6])  # 6 + 1 = 7 -> one slot
    engine = GameEngine(seed=4, dice_roller=lambda: next(dice))
    result = engine.execute_round(room, {"a": [Action(ActionType.SEARCH)]})

    event = next(event for event in result.events if event.event_type == "search_resolved")
    assert event.payload["search_total"] == 7
    assert event.payload["opened_slots"] == 1


def test_temporary_effect_applies_for_one_attack_only() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", strength=1, agency=1)
    add_agent(room, "b", strength=1, agency=1)
    room.agents["a"].effects.append(
        AgentEffect(
            effect_type=EffectType.STAT_BUFF,
            stat_mods={"strength": 4},
            remaining_attacks=1,
            source="item:test",
        )
    )

    dice1 = dice_from([1, 1])
    engine = GameEngine(seed=5, dice_roller=lambda: next(dice1))
    round_1 = engine.execute_round(room, {"a": [Action(ActionType.ATTACK, target_agent_id="b")]})
    event_1 = next(event for event in round_1.events if event.event_type == "attack_resolved")
    assert event_1.payload["success"] is True

    dice2 = dice_from([1, 1])
    engine._dice_roller = lambda: next(dice2)  # noqa: SLF001 - test setup
    round_2 = engine.execute_round(room, {"a": [Action(ActionType.ATTACK, target_agent_id="b")]})
    event_2 = next(event for event in round_2.events if event.event_type == "attack_resolved")
    assert event_2.payload["success"] is False


def test_permanent_effect_persists_between_attacks() -> None:
    room = make_room()
    add_template(room, "tpl-1")
    add_agent(room, "a", strength=1, agency=1)
    add_agent(room, "b", strength=1, agency=1)
    room.agents["a"].effects.append(
        AgentEffect(
            effect_type=EffectType.STAT_BUFF,
            stat_mods={"strength": 2},
            expires_on_turn=None,
            remaining_attacks=None,
            source="weapon:permanent",
        )
    )

    dice1 = dice_from([1, 1])
    engine = GameEngine(seed=6, dice_roller=lambda: next(dice1))
    round_1 = engine.execute_round(room, {"a": [Action(ActionType.ATTACK, target_agent_id="b")]})
    event_1 = next(event for event in round_1.events if event.event_type == "attack_resolved")
    assert event_1.payload["success"] is True

    dice2 = dice_from([1, 1])
    engine._dice_roller = lambda: next(dice2)  # noqa: SLF001 - test setup
    round_2 = engine.execute_round(room, {"a": [Action(ActionType.ATTACK, target_agent_id="b")]})
    event_2 = next(event for event in round_2.events if event.event_type == "attack_resolved")
    assert event_2.payload["success"] is True
