from __future__ import annotations

import random

from arena.enums import EffectType, ItemCategory
from arena.models import AgentState, ItemTemplate, RoomState
from arena.setup import (
    STARTING_AGENCY,
    generate_room_search_slots,
    initialize_agent_for_match,
    prepare_room_for_match,
)


def make_agent(agent_id: str) -> AgentState:
    return AgentState(
        id=agent_id,
        name=agent_id,
        base_strength=1,
        base_attentiveness=1,
        base_agency=5,
    )


def test_initialize_agent_for_match_sets_fixed_agency_and_weakness() -> None:
    rng = random.Random(11)
    agent = make_agent("a1")

    initialize_agent_for_match(agent, rng)

    assert agent.base_agency == STARTING_AGENCY
    assert len(agent.weaknesses) == 1
    assert sum(1 for effect in agent.effects if effect.source.startswith("weakness:")) == 1
    assert agent.base_strength + agent.base_attentiveness == 2


def test_bonus_skill_adds_extra_weakness() -> None:
    rng = random.Random(12)
    agent = make_agent("a2")

    initialize_agent_for_match(agent, rng, bonus_skill="strength")

    assert agent.base_agency == STARTING_AGENCY
    assert len(agent.weaknesses) == 2
    assert sum(1 for effect in agent.effects if effect.source.startswith("weakness:")) == 2
    # 2 base pool + 1 optional bonus.
    assert agent.base_strength + agent.base_attentiveness == 3


def test_generate_room_search_slots_respects_distribution() -> None:
    room = RoomState(id="room-setup")
    room.search_total_slots = 20
    room.search_trinket_count = 5
    room.search_weapon_count = 3
    room.search_special_count = 1
    room.item_templates["tpl-trinket"] = ItemTemplate(
        id="tpl-trinket",
        effect_type=EffectType.STAT_BUFF,
        category=ItemCategory.TRINKET,
    )
    room.item_templates["tpl-weapon"] = ItemTemplate(
        id="tpl-weapon",
        effect_type=EffectType.STAT_BUFF,
        category=ItemCategory.WEAPON,
    )
    room.item_templates["tpl-special"] = ItemTemplate(
        id="tpl-special",
        effect_type=EffectType.STAT_BUFF,
        category=ItemCategory.SPECIAL,
    )

    generate_room_search_slots(room, random.Random(13))

    assert len(room.search_slots) == 20
    non_empty_slots = [slot for slot in room.search_slots if slot.item_id is not None]
    assert len(non_empty_slots) == 9

    categories = [
        str(room.item_templates[room.items[slot.item_id].template_id].category)
        for slot in non_empty_slots
        if slot.item_id is not None
    ]
    assert categories.count(ItemCategory.TRINKET.value) == 5
    assert categories.count(ItemCategory.WEAPON.value) == 3
    assert categories.count(ItemCategory.SPECIAL.value) == 1


def test_prepare_room_for_match_applies_stats_and_generates_slots() -> None:
    room = RoomState(id="room-ready", rng_seed=101)
    room.agents["a"] = make_agent("a")
    room.agents["b"] = make_agent("b")
    room.item_templates["tpl-trinket"] = ItemTemplate(
        id="tpl-trinket",
        effect_type=EffectType.STAT_BUFF,
        category=ItemCategory.TRINKET,
    )
    room.item_templates["tpl-weapon"] = ItemTemplate(
        id="tpl-weapon",
        effect_type=EffectType.STAT_BUFF,
        category=ItemCategory.WEAPON,
    )
    room.item_templates["tpl-special"] = ItemTemplate(
        id="tpl-special",
        effect_type=EffectType.STAT_BUFF,
        category=ItemCategory.SPECIAL,
    )

    prepare_room_for_match(room, bonus_skill_by_agent_id={"a": "strength"})

    assert room.agents["a"].base_agency == STARTING_AGENCY
    assert room.agents["b"].base_agency == STARTING_AGENCY
    assert len(room.agents["a"].weaknesses) == 2
    assert len(room.agents["b"].weaknesses) == 1
    assert len(room.search_slots) == room.search_total_slots
