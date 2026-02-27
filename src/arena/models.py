from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arena.enums import ActionType, EffectType, ItemCategory, LogVisibility, RoomStatus


@dataclass(slots=True)
class AgentEffect:
    effect_type: EffectType | str
    actions_penalty: int = 0
    stat_mods: dict[str, int] = field(default_factory=dict)
    expires_on_turn: int | None = None
    remaining_attacks: int | None = None
    source: str = "unknown"


@dataclass(slots=True)
class AgentState:
    id: str
    name: str
    base_strength: int
    base_attentiveness: int
    base_agency: int
    base_prompt: str = ""
    is_ready: bool = False
    memory_file_raw: str = ""
    memory_file_trimmed: str = ""
    effects: list[AgentEffect] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ItemTemplate:
    id: str
    effect_type: EffectType | str
    effect_payload: dict[str, Any] = field(default_factory=dict)
    price: int = 0
    is_noticeable: bool = False
    category: ItemCategory | str = ItemCategory.TRINKET


@dataclass(slots=True)
class RoomItem:
    id: str
    template_id: str
    obfuscated_name: str
    appearance: str
    activation_desc: str
    owner_agent_id: str | None = None


@dataclass(slots=True)
class SearchSlot:
    index: int
    item_id: str | None = None
    opened: bool = False


@dataclass(slots=True)
class Action:
    action_type: ActionType
    target_agent_id: str | None = None
    item_id: str | None = None
    text: str | None = None


@dataclass(slots=True)
class GameEvent:
    id: str
    turn_number: int
    slot_index: int
    event_type: str
    payload: dict[str, Any]


@dataclass(slots=True)
class GameLog:
    visibility: LogVisibility
    message: str
    recipient_agent_id: str | None
    event_id: str | None = None


@dataclass(slots=True)
class RoundExecutionResult:
    events: list[GameEvent]
    logs: list[GameLog]
    effective_agency: dict[str, int]


@dataclass(slots=True)
class FinalScore:
    agent_id: str
    total_price: int


@dataclass(slots=True)
class RoomState:
    id: str
    status: RoomStatus = RoomStatus.LOBBY
    current_turn: int = 1
    max_turns: int = 12
    inventory_slots: int = 4
    rng_seed: int = 0
    perception_threshold: int = 8
    search_total_slots: int = 20
    search_trinket_count: int = 5
    search_weapon_count: int = 3
    search_special_count: int = 1
    allowed_actions: set[ActionType] = field(
        default_factory=lambda: {
            ActionType.DEFEND,
            ActionType.ATTACK,
            ActionType.STEAL,
            ActionType.SEARCH,
            ActionType.INSPECT_ITEM,
            ActionType.ACTIVATE_ITEM,
            ActionType.DROP_ITEM,
            ActionType.PICKUP_ITEM,
            ActionType.BROADCAST,
        }
    )
    agents: dict[str, AgentState] = field(default_factory=dict)
    item_templates: dict[str, ItemTemplate] = field(default_factory=dict)
    items: dict[str, RoomItem] = field(default_factory=dict)
    search_slots: list[SearchSlot] = field(default_factory=list)
