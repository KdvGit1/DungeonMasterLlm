# game/combat_events.py — Dinamik sahne olayları
"""
Combat sırasında rastgele tetiklenen olaylar.
Kod tarafından yönetilir, LLM sadece sonucu anlatır.

These events make combat feel dynamic and unpredictable.
They trigger based on combat state (turn count, HP thresholds, randomness).
"""

import random
from game.monster_data import get_monster, MAX_ENEMIES

# ─── OLAY TABLOSU ─────────────────────────────────────────────────────────────

COMBAT_EVENTS = [
    {
        "id": "reinforcement",
        "effect": "add_enemy",
        "trigger": "turn_3",
        "weight": 20,
        "description_en": "Reinforcements arrive!",
        "narrative_templates": [
            "A fresh enemy bursts onto the scene, drawn by the sounds of battle!",
            "Reinforcements arrive — another creature emerges from the shadows!",
            "The commotion has attracted attention. A new threat joins the fray!",
        ],
    },
    {
        "id": "enemy_flees",
        "effect": "remove_enemy",
        "trigger": "enemy_hp_low",
        "weight": 30,
        "description_en": "A wounded enemy flees the battle!",
        "narrative_templates": [
            "Battered and bleeding, {enemy} turns and flees for its life!",
            "{enemy} has had enough — it drops its weapon and runs!",
            "Seeing its allies fall, {enemy} breaks and retreats!",
        ],
    },
    {
        "id": "env_hazard",
        "effect": "aoe_damage",
        "trigger": "random",
        "weight": 15,
        "aoe_damage": 4,
        "description_en": "An environmental hazard strikes!",
        "narrative_templates": [
            "The ground cracks beneath the combatants! Shards of stone fly in all directions!",
            "A support beam gives way — debris crashes down on everyone nearby!",
            "The fire spreads! A wave of heat and smoke washes over the battlefield!",
            "A section of the floor collapses! Everyone struggles to keep their footing!",
        ],
    },
    {
        "id": "ally_arrives",
        "effect": "add_ally",
        "trigger": "player_hp_low",
        "weight": 15,
        "ally_heal": 5,
        "description_en": "A helpful stranger arrives and tends to wounded players!",
        "narrative_templates": [
            "A hooded figure emerges from the shadows, pressing healing hands to the wounded!",
            "A village healer who was hiding behind the barrels rushes forward to help!",
            "An old warrior, drawn by the clash of steel, charges in to even the odds!",
        ],
    },
    {
        "id": "enemy_desperation",
        "effect": "enemy_berserk",
        "trigger": "enemy_hp_low",
        "weight": 25,
        "description_en": "A wounded enemy goes into a desperate frenzy!",
        "narrative_templates": [
            "{enemy}, cornered and bleeding, lets out a guttural roar and attacks with reckless abandon!",
            "Wounded and desperate, {enemy} lashes out wildly — unpredictable and dangerous!",
            "{enemy} fights with the fury of a cornered animal, ignoring its own safety!",
        ],
    },
    {
        "id": "tactical_shift",
        "effect": "terrain_change",
        "trigger": "turn_5",
        "weight": 20,
        "description_en": "The battlefield shifts — new tactical opportunities emerge!",
        "narrative_templates": [
            "A crumbling pillar creates new cover. The battlefield has changed!",
            "Thick smoke from the fire now obscures parts of the battlefield!",
            "The fighting has moved to uneven ground — balance is now a factor!",
            "A previously locked door has burst open, revealing a new escape route or danger!",
        ],
    },
    {
        "id": "enemy_surrender",
        "effect": "enemy_surrender",
        "trigger": "outnumbered",
        "weight": 15,
        "description_en": "An enemy surrenders!",
        "narrative_templates": [
            "{enemy} throws down its weapon and raises its hands in surrender!",
            "Seeing the tide turn, {enemy} drops to its knees and begs for mercy!",
            "{enemy} backs away, weapon lowered, eyes wide with fear!",
        ],
    },
]

# Bir encounter'da en fazla 2 event tetiklenir
MAX_EVENTS_PER_ENCOUNTER = 2


# ─── OLAY KONTROL ─────────────────────────────────────────────────────────────

def check_combat_events(encounter_state, turn_number, players_stats=None):
    """
    Her tur sonunda tetiklenecek olayları kontrol eder.
    Döner: tetiklenen event listesi (genellikle 0 veya 1 olay)

    Args:
        encounter_state: EncounterState nesnesi
        turn_number: mevcut tur numarası
        players_stats: oyuncu stat'ları listesi [{name, hp, max_hp}, ...]
    """
    triggered = []
    already_triggered = encounter_state.triggered_events

    # Don't trigger too many events
    if len(already_triggered) >= MAX_EVENTS_PER_ENCOUNTER:
        return triggered

    for event in COMBAT_EVENTS:
        if event["id"] in already_triggered:
            continue

        if _should_trigger(event, encounter_state, turn_number, players_stats):
            roll = random.randint(1, 100)
            if roll <= event["weight"]:
                triggered.append(event)
                already_triggered.add(event["id"])
                # Only trigger one event per turn max
                break

    return triggered


def _should_trigger(event, encounter_state, turn_number, players_stats):
    """Olayın tetiklenme koşulu sağlanıyor mu?"""
    trigger = event["trigger"]

    alive_enemies = [e for e in encounter_state.enemies if e["hp"] > 0 and not e.get("fled")]
    alive_players = [p for p in (players_stats or []) if p["hp"] > 0]

    if trigger == "turn_3":
        return turn_number >= 3

    elif trigger == "turn_5":
        return turn_number >= 5

    elif trigger == "enemy_hp_low":
        for enemy in alive_enemies:
            if enemy["hp"] <= enemy["max_hp"] * 0.25:
                return True
        return False

    elif trigger == "player_hp_low":
        if players_stats:
            for ps in players_stats:
                if ps["hp"] > 0 and ps["hp"] <= ps["max_hp"] * 0.25:
                    return True
        return False

    elif trigger == "random":
        return turn_number >= 2

    elif trigger == "outnumbered":
        # Trigger if enemies are outnumbered 2:1
        return len(alive_enemies) > 0 and len(alive_players) > len(alive_enemies) * 2

    return False


# ─── OLAY UYGULAMA ────────────────────────────────────────────────────────────

def apply_event(encounter_state, event, players_stats=None):
    """
    Olayı encounter state'e uygular.
    Döner: LLM'e gösterilecek açıklama string'i
    """
    effect = event["effect"]

    if effect == "add_enemy":
        return _apply_reinforcement(encounter_state, event)
    elif effect == "remove_enemy":
        return _apply_enemy_flees(encounter_state, event)
    elif effect == "aoe_damage":
        return _apply_aoe_damage(encounter_state, event, players_stats)
    elif effect == "add_ally":
        return _apply_ally_arrives(encounter_state, event, players_stats)
    elif effect == "enemy_berserk":
        return _apply_enemy_berserk(encounter_state, event)
    elif effect == "terrain_change":
        return _apply_terrain_change(encounter_state, event)
    elif effect == "enemy_surrender":
        return _apply_enemy_surrender(encounter_state, event)

    return None


def _get_narrative(event, enemy_name=None):
    """Pick a random narrative template and format it."""
    templates = event.get("narrative_templates", [event.get("description_en", "Something happens!")])
    template = random.choice(templates)
    if enemy_name:
        template = template.replace("{enemy}", enemy_name)
    return template


def _apply_reinforcement(encounter_state, event):
    alive = [e for e in encounter_state.enemies if e["hp"] > 0]
    if len(alive) >= MAX_ENEMIES:
        return None

    if alive:
        template_enemy = random.choice(alive)
        new_type = template_enemy.get("type", "bandit")
        new_name = f"Reinforcement {template_enemy.get('display_name', new_type)}"
    else:
        new_type = "bandit"
        new_name = "Reinforcement"

    stats = get_monster(new_type)
    new_enemy = {
        "id": len(encounter_state.enemies),
        "type": new_type,
        "display_name": new_name,
        "hp": stats["hp"],
        "max_hp": stats["max_hp"],
        "ac": stats["ac"],
        "attack_bonus": stats["attack_bonus"],
        "damage_str": stats["damage_str"],
        "xp": stats["xp"],
        "abilities": stats["abilities"],
        "behavior": stats["behavior"],
        "status_effects": [],
        "ability_cooldowns": {},
        "fled": False,
    }
    encounter_state.enemies.append(new_enemy)
    return _get_narrative(event)


def _apply_enemy_flees(encounter_state, event):
    alive = [e for e in encounter_state.enemies if e["hp"] > 0]
    if not alive:
        return None

    # Pick the weakest enemy to flee
    weakest = min(alive, key=lambda e: e["hp"])
    weakest["hp"] = 0
    weakest["fled"] = True
    return _get_narrative(event, weakest["display_name"])


def _apply_aoe_damage(encounter_state, event, players_stats):
    aoe_dmg = event.get("aoe_damage", 4)
    affected = []

    for enemy in encounter_state.enemies:
        if enemy["hp"] > 0:
            enemy["hp"] = max(0, enemy["hp"] - aoe_dmg)
            affected.append(enemy["display_name"])

    desc = _get_narrative(event)
    if players_stats:
        desc += f" Players also take {aoe_dmg} damage."
    return desc


def _apply_ally_arrives(encounter_state, event, players_stats):
    return _get_narrative(event)


def _apply_enemy_berserk(encounter_state, event):
    alive = [e for e in encounter_state.enemies if e["hp"] > 0]
    if not alive:
        return None

    # Pick the most damaged alive enemy
    target = min(alive, key=lambda e: e["hp"])
    # Boost their attack bonus temporarily
    target["attack_bonus"] = target.get("attack_bonus", 2) + 2
    return _get_narrative(event, target["display_name"])


def _apply_terrain_change(encounter_state, event):
    encounter_state.terrain_advantage = random.choice(["players", "enemies", None])
    return _get_narrative(event)


def _apply_enemy_surrender(encounter_state, event):
    alive = [e for e in encounter_state.enemies if e["hp"] > 0]
    if not alive:
        return None

    # Pick the weakest to surrender
    weakest = min(alive, key=lambda e: e["hp"])
    weakest["hp"] = 0
    weakest["fled"] = True  # Surrendered enemies are removed from combat
    return _get_narrative(event, weakest["display_name"])
