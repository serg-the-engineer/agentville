from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from arena.enums import ACTION_TYPE_PRIORITY, ActionType, EffectType, LogVisibility, RoomStatus
from arena.models import (
    Action,
    AgentEffect,
    FinalScore,
    GameEvent,
    GameLog,
    RoomItem,
    RoomState,
    RoundExecutionResult,
)


class GameEngine:
    def __init__(self, seed: int, dice_roller: Callable[[], int] | None = None) -> None:
        self._rng = random.Random(seed)
        self._event_seq = 0
        self._dice_roller = dice_roller

    def execute_round(
        self,
        room: RoomState,
        planned_actions: Mapping[str, Sequence[Action]],
    ) -> RoundExecutionResult:
        if room.status == RoomStatus.FINISHED:
            raise ValueError("room is already finished")

        room.status = RoomStatus.PLAYING

        events: list[GameEvent] = []
        logs: list[GameLog] = []
        effective_agency = self._compute_effective_agency(room)
        normalized_actions, validation_events, validation_logs = self._normalize_actions(
            room=room,
            planned_actions=planned_actions,
            effective_agency=effective_agency,
        )
        events.extend(validation_events)
        logs.extend(validation_logs)

        round_mods: dict[str, dict[str, int]] = {
            agent_id: {"strength": 0, "attentiveness": 0}
            for agent_id in room.agents
        }

        max_slots = max(effective_agency.values(), default=0)
        for slot_index in range(1, max_slots + 1):
            slot_actions: list[tuple[str, Action]] = []
            for agent_id in sorted(room.agents):
                actions = normalized_actions.get(agent_id, [])
                if slot_index <= len(actions):
                    slot_actions.append((agent_id, actions[slot_index - 1]))

            slot_actions.sort(
                key=lambda pair: (
                    ACTION_TYPE_PRIORITY[pair[1].action_type],
                    pair[0],
                )
            )

            for agent_id, action in slot_actions:
                action_events, action_logs = self._execute_single_action(
                    room=room,
                    agent_id=agent_id,
                    slot_index=slot_index,
                    action=action,
                    round_mods=round_mods,
                )
                events.extend(action_events)
                logs.extend(action_logs)

        self._expire_effects(room)
        room.current_turn += 1
        if room.current_turn > room.max_turns:
            room.status = RoomStatus.FINISHED

        return RoundExecutionResult(
            events=events,
            logs=logs,
            effective_agency=effective_agency,
        )

    def calculate_results(self, room: RoomState) -> list[FinalScore]:
        totals: list[FinalScore] = []
        for agent_id in sorted(room.agents):
            total = 0
            for item in self._inventory(room, agent_id):
                template = room.item_templates.get(item.template_id)
                if template is None:
                    continue
                total += template.price
            totals.append(FinalScore(agent_id=agent_id, total_price=total))

        totals.sort(key=lambda score: (-score.total_price, score.agent_id))
        return totals

    def _compute_effective_agency(self, room: RoomState) -> dict[str, int]:
        effective_agency: dict[str, int] = {}
        for agent_id, agent in room.agents.items():
            penalty = sum(
                effect.actions_penalty
                for effect in agent.effects
                if self._is_effect_active(effect, room.current_turn)
            )
            effective_agency[agent_id] = max(0, agent.base_agency - penalty)
        return effective_agency

    def _normalize_actions(
        self,
        room: RoomState,
        planned_actions: Mapping[str, Sequence[Action]],
        effective_agency: Mapping[str, int],
    ) -> tuple[dict[str, list[Action]], list[GameEvent], list[GameLog]]:
        normalized: dict[str, list[Action]] = {}
        events: list[GameEvent] = []
        logs: list[GameLog] = []

        for agent_id in sorted(room.agents):
            raw_actions = list(planned_actions.get(agent_id, []))
            allowed_count = effective_agency.get(agent_id, 0)

            if allowed_count == 0:
                normalized[agent_id] = []
                if raw_actions:
                    event = self._new_event(
                        turn_number=room.current_turn,
                        slot_index=0,
                        event_type="action_rejected",
                        payload={
                            "agent_id": agent_id,
                            "reason": "effective_agency_zero",
                            "submitted_actions": len(raw_actions),
                        },
                    )
                    events.append(event)
                    logs.append(
                        self._new_log(
                            visibility=LogVisibility.PRIVATE,
                            recipient_agent_id=agent_id,
                            message="Действия проигнорированы: effective_agency = 0.",
                            event_id=event.id,
                        )
                    )
                continue

            if len(raw_actions) > allowed_count:
                event = self._new_event(
                    turn_number=room.current_turn,
                    slot_index=0,
                    event_type="action_rejected",
                    payload={
                        "agent_id": agent_id,
                        "reason": "actions_over_limit",
                        "submitted_actions": len(raw_actions),
                        "effective_agency": allowed_count,
                    },
                )
                events.append(event)
                logs.append(
                    self._new_log(
                        visibility=LogVisibility.PRIVATE,
                        recipient_agent_id=agent_id,
                        message=(
                            f"Лишние действия отброшены: {len(raw_actions)} > {allowed_count}."
                        ),
                        event_id=event.id,
                    )
                )

            accepted = []
            for index, action in enumerate(raw_actions[:allowed_count], start=1):
                if action.action_type not in room.allowed_actions:
                    event = self._new_event(
                        turn_number=room.current_turn,
                        slot_index=index,
                        event_type="action_rejected",
                        payload={
                            "agent_id": agent_id,
                            "reason": "action_not_allowed",
                            "action_type": action.action_type.value,
                        },
                    )
                    events.append(event)
                    logs.append(
                        self._new_log(
                            visibility=LogVisibility.PRIVATE,
                            recipient_agent_id=agent_id,
                            message=f"Недопустимое действие: {action.action_type.value}.",
                            event_id=event.id,
                        )
                    )
                    accepted.append(Action(action_type=ActionType.NO_OP))
                else:
                    accepted.append(action)

            normalized[agent_id] = accepted

        return normalized, events, logs

    def _execute_single_action(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
        round_mods: dict[str, dict[str, int]],
    ) -> tuple[list[GameEvent], list[GameLog]]:
        if action.action_type == ActionType.NO_OP:
            event = self._new_event(
                turn_number=room.current_turn,
                slot_index=slot_index,
                event_type="action_noop",
                payload={"agent_id": agent_id, "reason": "noop_action"},
            )
            return [event], []

        if action.action_type == ActionType.DEFEND:
            return self._execute_defend(room, agent_id, slot_index, round_mods)
        if action.action_type == ActionType.BROADCAST:
            return self._execute_broadcast(room, agent_id, slot_index, action)
        if action.action_type == ActionType.DROP_ITEM:
            return self._execute_drop_item(room, agent_id, slot_index, action)
        if action.action_type == ActionType.PICKUP_ITEM:
            return self._execute_pickup_item(room, agent_id, slot_index, action)
        if action.action_type == ActionType.ATTACK:
            return self._execute_attack(room, agent_id, slot_index, action, round_mods)
        if action.action_type == ActionType.STEAL:
            return self._execute_steal(room, agent_id, slot_index, action, round_mods)
        if action.action_type == ActionType.SEARCH:
            return self._execute_search(room, agent_id, slot_index, round_mods)
        if action.action_type == ActionType.INSPECT_ITEM:
            return self._execute_inspect_item(room, agent_id, slot_index, action)
        if action.action_type == ActionType.ACTIVATE_ITEM:
            return self._execute_activate_item(room, agent_id, slot_index, action)

        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="action_noop",
            payload={
                "agent_id": agent_id,
                "reason": "unknown_action_type",
                "action_type": action.action_type.value,
            },
        )
        return [event], [
            self._new_log(
                visibility=LogVisibility.PRIVATE,
                recipient_agent_id=agent_id,
                message=f"Неизвестный тип действия: {action.action_type.value}.",
                event_id=event.id,
            )
        ]

    def _execute_defend(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        round_mods: dict[str, dict[str, int]],
    ) -> tuple[list[GameEvent], list[GameLog]]:
        round_mods[agent_id]["strength"] += 1
        round_mods[agent_id]["attentiveness"] += 1
        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="defend_applied",
            payload={"agent_id": agent_id, "strength_bonus": 1, "attentiveness_bonus": 1},
        )
        log = self._new_log(
            visibility=LogVisibility.PUBLIC,
            recipient_agent_id=None,
            message=f"{room.agents[agent_id].name} занял оборону.",
            event_id=event.id,
        )
        return [event], [log]

    def _execute_broadcast(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
    ) -> tuple[list[GameEvent], list[GameLog]]:
        text = (action.text or "").strip()
        if not text:
            event = self._new_event(
                turn_number=room.current_turn,
                slot_index=slot_index,
                event_type="action_noop",
                payload={"agent_id": agent_id, "reason": "empty_broadcast"},
            )
            return [event], [
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message="Пустой broadcast пропущен.",
                    event_id=event.id,
                )
            ]

        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="broadcast",
            payload={"agent_id": agent_id, "text": text},
        )
        log = self._new_log(
            visibility=LogVisibility.PUBLIC,
            recipient_agent_id=None,
            message=f"{room.agents[agent_id].name}: {text}",
            event_id=event.id,
        )
        return [event], [log]

    def _execute_drop_item(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
    ) -> tuple[list[GameEvent], list[GameLog]]:
        if action.item_id is None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_id_required",
                message="Для drop_item нужен item_id.",
            )

        item = room.items.get(action.item_id)
        if item is None or item.owner_agent_id != agent_id:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_not_owned",
                message="Нельзя выбросить предмет, которым вы не владеете.",
            )

        item.owner_agent_id = None
        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="drop_item",
            payload={"agent_id": agent_id, "item_id": item.id},
        )
        log = self._new_log(
            visibility=LogVisibility.PUBLIC,
            recipient_agent_id=None,
            message=f"{room.agents[agent_id].name} бросил предмет на пол.",
            event_id=event.id,
        )
        return [event], [log]

    def _execute_pickup_item(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
    ) -> tuple[list[GameEvent], list[GameLog]]:
        if action.item_id is None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_id_required",
                message="Для pickup_item нужен item_id.",
            )

        item = room.items.get(action.item_id)
        if item is None or item.owner_agent_id is not None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_not_on_floor",
                message="Нельзя поднять предмет: его нет на полу.",
            )

        if not self._has_free_slot(room, agent_id):
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="inventory_full",
                message="Нельзя поднять предмет: нет свободных слотов.",
            )

        item.owner_agent_id = agent_id
        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="pickup_item",
            payload={"agent_id": agent_id, "item_id": item.id},
        )
        log = self._new_log(
            visibility=LogVisibility.PUBLIC,
            recipient_agent_id=None,
            message=f"{room.agents[agent_id].name} поднял предмет с пола.",
            event_id=event.id,
        )
        return [event], [log]

    def _execute_attack(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
        round_mods: dict[str, dict[str, int]],
    ) -> tuple[list[GameEvent], list[GameLog]]:
        target_id = action.target_agent_id
        if target_id is None or target_id not in room.agents or target_id == agent_id:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="invalid_target",
                message="Некорректная цель для attack.",
            )

        selected_item, select_reason = self._select_target_item(
            room=room,
            target_id=target_id,
            requested_item_id=action.item_id,
        )
        if select_reason == "requested_item_not_owned":
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_not_in_target_inventory",
                message="У цели нет указанного предмета.",
            )

        attack_total = self._roll_d10() + self._agent_stat(
            room, agent_id, "strength", round_mods
        )
        defend_total = self._roll_d10() + self._agent_stat(
            room, target_id, "strength", round_mods
        )
        success = attack_total > defend_total
        diff = attack_total - defend_total

        payload = {
            "attacker_id": agent_id,
            "target_id": target_id,
            "attack_total": attack_total,
            "defend_total": defend_total,
            "success": success,
        }

        logs: list[GameLog] = []
        if not success:
            event = self._new_event(
                turn_number=room.current_turn,
                slot_index=slot_index,
                event_type="attack_resolved",
                payload=payload,
            )
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PUBLIC,
                    recipient_agent_id=None,
                    message=(
                        f"{room.agents[agent_id].name} атаковал "
                        f"{room.agents[target_id].name}, но неудачно."
                    ),
                    event_id=event.id,
                )
            )
            self._consume_on_attack_effects(room, agent_id)
            return [event], logs

        overflow_to_floor = False
        transferred_item_id = None
        if selected_item is not None:
            transferred_item_id = selected_item.id
            overflow_to_floor = self._transfer_item(room, selected_item, agent_id)
        payload.update(
            {
                "diff": diff,
                "transferred_item_id": transferred_item_id,
                "overflow_to_floor": overflow_to_floor,
                "stunned_applied": diff >= 5,
            }
        )
        if diff >= 5:
            self._apply_stun(room, target_id)

        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="attack_resolved",
            payload=payload,
        )
        if transferred_item_id is None:
            message = (
                f"{room.agents[agent_id].name} успешно атаковал "
                f"{room.agents[target_id].name}, но у цели не было предметов."
            )
        elif overflow_to_floor:
            message = (
                f"{room.agents[agent_id].name} отобрал предмет у "
                f"{room.agents[target_id].name}, но предмет упал на пол."
            )
        else:
            message = (
                f"{room.agents[agent_id].name} отобрал предмет у "
                f"{room.agents[target_id].name}."
            )
        logs.append(
            self._new_log(
                visibility=LogVisibility.PUBLIC,
                recipient_agent_id=None,
                message=message,
                event_id=event.id,
            )
        )
        self._consume_on_attack_effects(room, agent_id)
        return [event], logs

    def _execute_steal(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
        round_mods: dict[str, dict[str, int]],
    ) -> tuple[list[GameEvent], list[GameLog]]:
        target_id = action.target_agent_id
        if target_id is None or target_id not in room.agents or target_id == agent_id:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="invalid_target",
                message="Некорректная цель для steal.",
            )

        selected_item, select_reason = self._select_target_item(
            room=room,
            target_id=target_id,
            requested_item_id=action.item_id,
        )
        if select_reason == "requested_item_not_owned":
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_not_in_target_inventory",
                message="У цели нет указанного предмета.",
            )

        steal_total = self._roll_d10() + self._agent_stat(
            room, agent_id, "attentiveness", round_mods
        )
        defend_total = self._roll_d10() + self._agent_stat(
            room, target_id, "attentiveness", round_mods
        )
        success = steal_total > defend_total
        diff = steal_total - defend_total
        payload = {
            "thief_id": agent_id,
            "target_id": target_id,
            "steal_total": steal_total,
            "defend_total": defend_total,
            "success": success,
        }
        logs: list[GameLog] = []

        if not success:
            event = self._new_event(
                turn_number=room.current_turn,
                slot_index=slot_index,
                event_type="steal_resolved",
                payload=payload,
            )
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message="Попытка воровства не удалась.",
                    event_id=event.id,
                )
            )
            return [event], logs

        overflow_to_floor = False
        transferred_item_id = None
        if selected_item is not None:
            transferred_item_id = selected_item.id
            overflow_to_floor = self._transfer_item(room, selected_item, agent_id)

        payload.update(
            {
                "diff": diff,
                "transferred_item_id": transferred_item_id,
                "overflow_to_floor": overflow_to_floor,
            }
        )
        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="steal_resolved",
            payload=payload,
        )

        if transferred_item_id is None:
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message="Кража успешна, но у цели не было предметов.",
                    event_id=event.id,
                )
            )
        else:
            if overflow_to_floor:
                thief_message = "Вы украли предмет, но он упал на пол из-за нехватки слотов."
            else:
                thief_message = "Вы успешно украли предмет."
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message=thief_message,
                    event_id=event.id,
                )
            )
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=target_id,
                    message="Вы заметили пропажу предмета из инвентаря.",
                    event_id=event.id,
                )
            )

        logs.extend(
            self._steal_conditional_logs(
                room=room,
                thief_id=agent_id,
                target_id=target_id,
                event_id=event.id,
                round_mods=round_mods,
            )
        )
        return [event], logs

    def _execute_search(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        round_mods: dict[str, dict[str, int]],
    ) -> tuple[list[GameEvent], list[GameLog]]:
        roll = self._roll_d10()
        search_mod = self._agent_stat(room, agent_id, "attentiveness", round_mods)
        search_total = roll + search_mod
        slots_to_open = self._resolve_search_open_count(search_total)
        selected_slots = self._choose_closed_search_slots(room, slots_to_open)
        opened_slots = 0
        found_items: list[str] = []
        overflowed_items: list[str] = []
        empty_opened_slots = 0

        for slot in selected_slots:
            slot.opened = True
            opened_slots += 1
            if slot.item_id is None:
                empty_opened_slots += 1
                continue
            item = room.items.get(slot.item_id)
            if item is None:
                empty_opened_slots += 1
                continue
            overflowed = self._transfer_item(room, item, agent_id)
            found_items.append(item.id)
            if overflowed:
                overflowed_items.append(item.id)

        payload = {
            "agent_id": agent_id,
            "roll": roll,
            "search_mod": search_mod,
            "search_total": search_total,
            "slots_to_open": slots_to_open,
            "opened_slots": opened_slots,
            "found_item_ids": found_items,
            "overflow_item_ids": overflowed_items,
            "empty_opened_slots": empty_opened_slots,
        }
        logs: list[GameLog] = []
        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="search_resolved",
            payload=payload,
        )
        if opened_slots == 0:
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message="Поиск не удался: вы не открыли ни одного слота.",
                    event_id=event.id,
                )
            )
            return [event], logs

        if not found_items:
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message="Вы открыли слоты, но не нашли предметов.",
                    event_id=event.id,
                )
            )
            return [event], logs

        message = (
            f"{room.agents[agent_id].name} нашел {len(found_items)} предмет(а) "
            f"через поиск."
        )
        logs.append(
            self._new_log(
                visibility=LogVisibility.PUBLIC,
                recipient_agent_id=None,
                message=message,
                event_id=event.id,
            )
        )
        if overflowed_items:
            logs.append(
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message=(
                        f"{len(overflowed_items)} предмет(а) упали на пол "
                        "из-за нехватки слотов."
                    ),
                    event_id=event.id,
                )
            )
        return [event], logs

    def _execute_inspect_item(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
    ) -> tuple[list[GameEvent], list[GameLog]]:
        if action.item_id is None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_id_required",
                message="Для inspect_item нужен item_id.",
            )

        item = room.items.get(action.item_id)
        if item is None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_not_found",
                message="Предмет не найден.",
            )

        if item.owner_agent_id not in (None, agent_id):
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_not_visible",
                message="Нельзя изучить невидимый предмет.",
            )

        template = room.item_templates.get(item.template_id)
        if template is None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="template_not_found",
                message="Шаблон предмета не найден.",
            )

        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="inspect_item",
            payload={"agent_id": agent_id, "item_id": item.id},
        )
        log = self._new_log(
            visibility=LogVisibility.PRIVATE,
            recipient_agent_id=agent_id,
            message=(
                f"Предмет: {item.obfuscated_name}. "
                f"Активация: {item.activation_desc}. "
                f"Заметность: {template.is_noticeable}."
            ),
            event_id=event.id,
        )
        return [event], [log]

    def _execute_activate_item(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        action: Action,
    ) -> tuple[list[GameEvent], list[GameLog]]:
        if action.item_id is None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_id_required",
                message="Для activate_item нужен item_id.",
            )

        item = room.items.get(action.item_id)
        if item is None or item.owner_agent_id != agent_id:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="item_not_owned",
                message="Нельзя активировать предмет, которым вы не владеете.",
            )

        template = room.item_templates.get(item.template_id)
        if template is None:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="template_not_found",
                message="Шаблон предмета не найден.",
            )

        try:
            effect_type = EffectType(str(template.effect_type))
        except ValueError:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="unsupported_effect_type",
                message=f"Неизвестный тип эффекта: {template.effect_type}.",
            )
        if effect_type not in (EffectType.STAT_BUFF, EffectType.STAT_DEBUFF):
            event = self._new_event(
                turn_number=room.current_turn,
                slot_index=slot_index,
                event_type="activate_item",
                payload={
                    "agent_id": agent_id,
                    "item_id": item.id,
                    "status": "unsupported_effect",
                    "effect_type": effect_type.value,
                },
            )
            return [event], [
                self._new_log(
                    visibility=LogVisibility.PRIVATE,
                    recipient_agent_id=agent_id,
                    message=f"Эффект {effect_type.value} пока не поддержан в MVP.",
                    event_id=event.id,
                )
            ]

        payload = template.effect_payload
        target_id = action.target_agent_id or agent_id
        if target_id not in room.agents:
            return self._private_noop(
                room=room,
                agent_id=agent_id,
                slot_index=slot_index,
                reason="invalid_target",
                message="Некорректная цель для активации предмета.",
            )

        duration_mode = str(payload.get("duration_mode", "next_attack"))
        expires_on_turn: int | None = None
        remaining_attacks: int | None = None
        if duration_mode == "permanent":
            expires_on_turn = None
            remaining_attacks = None
        elif duration_mode == "rounds":
            duration = max(1, int(payload.get("duration_rounds", 1)))
            expires_on_turn = room.current_turn + duration - 1
        else:
            duration_mode = "next_attack"
            remaining_attacks = 1

        effect = AgentEffect(
            effect_type=effect_type,
            actions_penalty=int(payload.get("actions_penalty", 0)),
            stat_mods={
                key: int(payload[key])
                for key in ("strength", "attentiveness", "agency")
                if key in payload
            },
            expires_on_turn=expires_on_turn,
            remaining_attacks=remaining_attacks,
            source=f"item:{item.id}",
        )
        room.agents[target_id].effects.append(effect)

        if bool(payload.get("consumable", True)):
            del room.items[item.id]

        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="activate_item",
            payload={
                "agent_id": agent_id,
                "target_id": target_id,
                "item_id": action.item_id,
                "effect_type": effect_type.value,
                "duration_mode": duration_mode,
                "remaining_attacks": remaining_attacks,
                "expires_on_turn": expires_on_turn,
            },
        )
        log = self._new_log(
            visibility=LogVisibility.PRIVATE,
            recipient_agent_id=agent_id,
            message=f"Вы активировали предмет. Эффект применен к {room.agents[target_id].name}.",
            event_id=event.id,
        )
        return [event], [log]

    def _private_noop(
        self,
        room: RoomState,
        agent_id: str,
        slot_index: int,
        reason: str,
        message: str,
    ) -> tuple[list[GameEvent], list[GameLog]]:
        event = self._new_event(
            turn_number=room.current_turn,
            slot_index=slot_index,
            event_type="action_noop",
            payload={"agent_id": agent_id, "reason": reason},
        )
        return [event], [
            self._new_log(
                visibility=LogVisibility.PRIVATE,
                recipient_agent_id=agent_id,
                message=message,
                event_id=event.id,
            )
        ]

    def _select_target_item(
        self,
        room: RoomState,
        target_id: str,
        requested_item_id: str | None,
    ) -> tuple[RoomItem | None, Literal["ok", "target_empty", "requested_item_not_owned"]]:
        target_items = self._inventory(room, target_id)
        if not target_items:
            return None, "target_empty"

        if requested_item_id is None:
            return self._rng.choice(target_items), "ok"

        item = room.items.get(requested_item_id)
        if item is None or item.owner_agent_id != target_id:
            return None, "requested_item_not_owned"
        return item, "ok"

    def _steal_conditional_logs(
        self,
        room: RoomState,
        thief_id: str,
        target_id: str,
        event_id: str,
        round_mods: dict[str, dict[str, int]],
    ) -> list[GameLog]:
        logs: list[GameLog] = []
        for observer_id in sorted(room.agents):
            if observer_id in (thief_id, target_id):
                continue
            perception_total = self._roll_d10() + self._agent_stat(
                room,
                observer_id,
                "attentiveness",
                round_mods,
            )
            if perception_total > room.perception_threshold:
                logs.append(
                    self._new_log(
                        visibility=LogVisibility.CONDITIONAL,
                        recipient_agent_id=observer_id,
                        message=(
                            "Вы заметили, как один агент что-то украл у другого."
                        ),
                        event_id=event_id,
                    )
                )
        return logs

    def _apply_stun(self, room: RoomState, target_id: str) -> None:
        room.agents[target_id].effects.append(
            AgentEffect(
                effect_type=EffectType.STUNNED,
                actions_penalty=1,
                expires_on_turn=room.current_turn + 1,
            )
        )

    def _agent_stat(
        self,
        room: RoomState,
        agent_id: str,
        stat_name: Literal["strength", "attentiveness", "agency"],
        round_mods: dict[str, dict[str, int]],
    ) -> int:
        agent = room.agents[agent_id]
        base_name = f"base_{stat_name}"
        total = int(getattr(agent, base_name))
        for effect in agent.effects:
            if self._is_effect_active(effect, room.current_turn):
                total += int(effect.stat_mods.get(stat_name, 0))
        total += int(round_mods[agent_id].get(stat_name, 0))
        return total

    def _inventory(self, room: RoomState, agent_id: str) -> list[RoomItem]:
        return sorted(
            [item for item in room.items.values() if item.owner_agent_id == agent_id],
            key=lambda item: item.id,
        )

    def _has_free_slot(self, room: RoomState, agent_id: str) -> bool:
        return len(self._inventory(room, agent_id)) < room.inventory_slots

    def _transfer_item(self, room: RoomState, item: RoomItem, new_owner: str) -> bool:
        if self._has_free_slot(room, new_owner):
            item.owner_agent_id = new_owner
            return False
        item.owner_agent_id = None
        return True

    @staticmethod
    def _resolve_search_open_count(search_total: int) -> int:
        if search_total <= 6:
            return 0
        if search_total <= 9:
            return 1
        return 2

    def _choose_closed_search_slots(self, room: RoomState, count: int):
        if count <= 0:
            return []
        closed = [slot for slot in room.search_slots if not slot.opened]
        if not closed:
            return []
        if len(closed) <= count:
            return sorted(closed, key=lambda slot: slot.index)
        return sorted(self._rng.sample(closed, count), key=lambda slot: slot.index)

    def _consume_on_attack_effects(self, room: RoomState, agent_id: str) -> None:
        for effect in room.agents[agent_id].effects:
            if effect.remaining_attacks is not None and effect.remaining_attacks > 0:
                effect.remaining_attacks -= 1

    def _expire_effects(self, room: RoomState) -> None:
        for agent in room.agents.values():
            agent.effects = [
                effect
                for effect in agent.effects
                if (
                    (effect.expires_on_turn is None or effect.expires_on_turn > room.current_turn)
                    and (effect.remaining_attacks is None or effect.remaining_attacks > 0)
                )
            ]

    @staticmethod
    def _is_effect_active(effect: AgentEffect, current_turn: int) -> bool:
        turn_active = effect.expires_on_turn is None or effect.expires_on_turn >= current_turn
        attack_active = effect.remaining_attacks is None or effect.remaining_attacks > 0
        return turn_active and attack_active

    def _new_event(
        self,
        turn_number: int,
        slot_index: int,
        event_type: str,
        payload: dict,
    ) -> GameEvent:
        self._event_seq += 1
        return GameEvent(
            id=f"evt-{self._event_seq}",
            turn_number=turn_number,
            slot_index=slot_index,
            event_type=event_type,
            payload=payload,
        )

    @staticmethod
    def _new_log(
        visibility: LogVisibility,
        recipient_agent_id: str | None,
        message: str,
        event_id: str | None,
    ) -> GameLog:
        return GameLog(
            visibility=visibility,
            recipient_agent_id=recipient_agent_id,
            message=message,
            event_id=event_id,
        )

    def _roll_d10(self) -> int:
        if self._dice_roller is not None:
            return self._dice_roller()
        return self._rng.randint(1, 10)
