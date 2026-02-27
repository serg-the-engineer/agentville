from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from arena.enums import EffectType, ItemCategory
from arena.models import AgentEffect, AgentState, RoomItem, RoomState, SearchSlot

STARTING_AGENCY = 2
STARTING_STAT_POINTS = 2


@dataclass(frozen=True, slots=True)
class WeaknessSpec:
    code: str
    stat_mods: Mapping[str, int]
    description: str


WEAKNESS_POOL: tuple[WeaknessSpec, ...] = (
    WeaknessSpec(
        code="frail",
        stat_mods={"strength": -1},
        description="Физически слабее обычного.",
    ),
    WeaknessSpec(
        code="distracted",
        stat_mods={"attentiveness": -1},
        description="Сложнее замечать детали.",
    ),
    WeaknessSpec(
        code="clumsy",
        stat_mods={"strength": -1},
        description="Атаки выходят менее точными.",
    ),
    WeaknessSpec(
        code="tunnel_vision",
        stat_mods={"attentiveness": -1},
        description="Фокус сужен, восприятие хуже.",
    ),
)


def distribute_starting_stats(
    rng: random.Random,
    *,
    total_points: int = STARTING_STAT_POINTS,
    min_stat: int = 0,
) -> tuple[int, int]:
    if total_points < min_stat * 2:
        raise ValueError("total_points is too low for min_stat")

    strength = rng.randint(min_stat, total_points - min_stat)
    attentiveness = total_points - strength
    return strength, attentiveness


def initialize_agent_for_match(
    agent: AgentState,
    rng: random.Random,
    *,
    bonus_skill: Literal["strength", "attentiveness"] | None = None,
    total_points: int = STARTING_STAT_POINTS,
) -> None:
    strength, attentiveness = distribute_starting_stats(rng, total_points=total_points)
    agent.base_strength = strength
    agent.base_attentiveness = attentiveness
    agent.base_agency = STARTING_AGENCY

    # Keep non-weakness runtime effects if setup is re-run.
    agent.effects = [effect for effect in agent.effects if not effect.source.startswith("weakness:")]
    agent.weaknesses = []

    apply_random_weaknesses(agent, rng, count=1)

    if bonus_skill is not None:
        if bonus_skill == "strength":
            agent.base_strength += 1
        elif bonus_skill == "attentiveness":
            agent.base_attentiveness += 1
        else:
            raise ValueError(f"unsupported bonus_skill: {bonus_skill}")
        apply_random_weaknesses(agent, rng, count=1)


def apply_random_weaknesses(agent: AgentState, rng: random.Random, *, count: int) -> None:
    available = [spec for spec in WEAKNESS_POOL if spec.code not in set(agent.weaknesses)]
    if not available:
        available = list(WEAKNESS_POOL)

    for _ in range(count):
        if not available:
            available = list(WEAKNESS_POOL)
        spec = rng.choice(available)
        available = [entry for entry in available if entry.code != spec.code]
        agent.weaknesses.append(spec.code)
        agent.effects.append(
            AgentEffect(
                effect_type=EffectType.STAT_DEBUFF,
                stat_mods={key: int(value) for key, value in spec.stat_mods.items()},
                expires_on_turn=None,
                source=f"weakness:{spec.code}",
            )
        )


def generate_room_search_slots(room: RoomState, rng: random.Random) -> None:
    total_slots = room.search_total_slots
    requested_items = room.search_trinket_count + room.search_weapon_count + room.search_special_count
    if requested_items > total_slots:
        raise ValueError("item count exceeds search_total_slots")

    # Rebuild search pool idempotently for repeated room preparations.
    for slot in room.search_slots:
        if slot.item_id is None:
            continue
        old_item = room.items.get(slot.item_id)
        if old_item is not None and old_item.owner_agent_id is None:
            del room.items[slot.item_id]

    by_category: dict[ItemCategory, list[str]] = {
        ItemCategory.TRINKET: [],
        ItemCategory.WEAPON: [],
        ItemCategory.SPECIAL: [],
    }
    for template_id, template in room.item_templates.items():
        try:
            category = ItemCategory(str(template.category))
        except ValueError:
            continue
        by_category[category].append(template_id)

    needs = {
        ItemCategory.TRINKET: room.search_trinket_count,
        ItemCategory.WEAPON: room.search_weapon_count,
        ItemCategory.SPECIAL: room.search_special_count,
    }

    selected_template_ids: list[str] = []
    for category, count in needs.items():
        if count <= 0:
            continue
        options = by_category.get(category, [])
        if not options:
            raise ValueError(f"no templates available for category: {category.value}")
        for _ in range(count):
            selected_template_ids.append(rng.choice(options))

    generated_item_ids: list[str] = []
    seq = 1
    for template_id in selected_template_ids:
        while f"loot-{seq}" in room.items:
            seq += 1
        item_id = f"loot-{seq}"
        seq += 1
        room.items[item_id] = RoomItem(
            id=item_id,
            template_id=template_id,
            obfuscated_name=f"Артефакт-{item_id}",
            appearance=f"Необычный предмет #{item_id}",
            activation_desc="Эффект станет понятнее после inspect.",
            owner_agent_id=None,
        )
        generated_item_ids.append(item_id)

    slot_payloads: list[str | None] = generated_item_ids + [None] * (total_slots - len(generated_item_ids))
    rng.shuffle(slot_payloads)
    room.search_slots = [
        SearchSlot(index=index + 1, item_id=item_id, opened=False)
        for index, item_id in enumerate(slot_payloads)
    ]


def prepare_room_for_match(
    room: RoomState,
    *,
    bonus_skill_by_agent_id: Mapping[str, Literal["strength", "attentiveness"] | None] | None = None,
    rng_seed: int | None = None,
) -> None:
    rng = random.Random(room.rng_seed if rng_seed is None else rng_seed)
    bonus_skill_by_agent_id = bonus_skill_by_agent_id or {}

    for agent_id in sorted(room.agents):
        bonus_skill = bonus_skill_by_agent_id.get(agent_id)
        initialize_agent_for_match(room.agents[agent_id], rng, bonus_skill=bonus_skill)

    generate_room_search_slots(room, rng)
