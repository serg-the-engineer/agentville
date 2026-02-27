from __future__ import annotations

from enum import IntEnum, StrEnum


class ActionType(StrEnum):
    DEFEND = "defend"
    ATTACK = "attack"
    STEAL = "steal"
    SEARCH = "search"
    INSPECT_ITEM = "inspect_item"
    ACTIVATE_ITEM = "activate_item"
    DROP_ITEM = "drop_item"
    PICKUP_ITEM = "pickup_item"
    BROADCAST = "broadcast"
    NO_OP = "no_op"


class LogVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    CONDITIONAL = "conditional"


class RoomStatus(StrEnum):
    LOBBY = "lobby"
    PLAYING = "playing"
    FINISHED = "finished"


class EffectType(StrEnum):
    STUNNED = "stunned"
    STAT_BUFF = "stat_buff"
    STAT_DEBUFF = "stat_debuff"
    STUN_ON_HIT = "stun_on_hit"


class ItemCategory(StrEnum):
    TRINKET = "trinket"
    WEAPON = "weapon"
    SPECIAL = "special"


class ActionPriority(IntEnum):
    DEFEND = 10
    SOCIAL = 20
    AGGRESSIVE = 30
    EXPLORE = 40
    INTERNAL = 100


ACTION_TYPE_PRIORITY: dict[ActionType, int] = {
    ActionType.DEFEND: ActionPriority.DEFEND,
    ActionType.DROP_ITEM: ActionPriority.SOCIAL,
    ActionType.PICKUP_ITEM: ActionPriority.SOCIAL,
    ActionType.BROADCAST: ActionPriority.SOCIAL,
    ActionType.ATTACK: ActionPriority.AGGRESSIVE,
    ActionType.STEAL: ActionPriority.AGGRESSIVE,
    ActionType.SEARCH: ActionPriority.EXPLORE,
    ActionType.INSPECT_ITEM: ActionPriority.EXPLORE,
    ActionType.ACTIVATE_ITEM: ActionPriority.EXPLORE,
    ActionType.NO_OP: ActionPriority.INTERNAL,
}
