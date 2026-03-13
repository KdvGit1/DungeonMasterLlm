# game/combat_events.py — Dinamik sahne olayları
"""
Combat sırasında rastgele tetiklenen olaylar.
Kod tarafından yönetilir, LLM sadece sonucu anlatır.
"""

import random
from game.monster_data import get_monster, MAX_ENEMIES

# ─── OLAY TABLOSU ─────────────────────────────────────────────────────────────

COMBAT_EVENTS = [
    {
        "id": "reinforcement",
        "effect": "add_enemy",
        "trigger": "turn_3",
        "weight": 15,
        "description_en": "Reinforcements arrive!",
    },
    {
        "id": "enemy_flees",
        "effect": "remove_enemy",
        "trigger": "enemy_hp_low",
        "weight": 20,
        "description_en": "A wounded enemy flees the battle!",
    },
    {
        "id": "env_hazard",
        "effect": "aoe_damage",
        "trigger": "random",
        "weight": 10,
        "aoe_damage": 4,
        "description_en": "An environmental hazard strikes!",
    },
    {
        "id": "ally_arrives",
        "effect": "add_ally",
        "trigger": "player_hp_low",
        "weight": 10,
        "ally_heal": 5,
        "description_en": "A helpful stranger arrives and tends to wounded players!",
    },
]

# Bir encounter'da en fazla 1 event tetiklenir
# (her event sadece 1 kez tetiklenebilir)


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

    for event in COMBAT_EVENTS:
        if event["id"] in already_triggered:
            continue

        if _should_trigger(event, encounter_state, turn_number, players_stats):
            # Ağırlık bazlı şans kontrolü
            roll = random.randint(1, 100)
            if roll <= event["weight"]:
                triggered.append(event)
                already_triggered.add(event["id"])

    return triggered


def _should_trigger(event, encounter_state, turn_number, players_stats):
    """Olayın tetiklenme koşulu sağlanıyor mu?"""
    trigger = event["trigger"]

    if trigger == "turn_3":
        return turn_number >= 3

    elif trigger == "enemy_hp_low":
        # En az bir düşmanın HP'si %25 altında
        for enemy in encounter_state.enemies:
            if enemy["hp"] > 0 and enemy["hp"] <= enemy["max_hp"] * 0.25:
                return True
        return False

    elif trigger == "player_hp_low":
        # En az bir oyuncunun HP'si %25 altında
        if players_stats:
            for ps in players_stats:
                if ps["hp"] > 0 and ps["hp"] <= ps["max_hp"] * 0.25:
                    return True
        return False

    elif trigger == "random":
        return turn_number >= 2  # İlk turda random olay yok

    return False


# ─── OLAY UYGULAMA ────────────────────────────────────────────────────────────

def apply_event(encounter_state, event, players_stats=None):
    """
    Olayı encounter state'e uygular.
    Döner: LLM'e gönderilecek açıklama string'i
    """
    effect = event["effect"]

    if effect == "add_enemy":
        return _apply_reinforcement(encounter_state)

    elif effect == "remove_enemy":
        return _apply_enemy_flees(encounter_state)

    elif effect == "aoe_damage":
        return _apply_aoe_damage(encounter_state, event, players_stats)

    elif effect == "add_ally":
        return _apply_ally_arrives(encounter_state, event, players_stats)

    return None


def _apply_reinforcement(encounter_state):
    """Takviye düşman ekler (max MAX_ENEMIES sınırı korunur)."""
    alive = [e for e in encounter_state.enemies if e["hp"] > 0]
    if len(alive) >= MAX_ENEMIES:
        return None  # Zaten max düşman var

    # Mevcut düşmanlardan rastgele birinin tipini kullan
    if alive:
        template_enemy = random.choice(alive)
        new_type = template_enemy.get("type", "bandit")
        new_name = f"Reinforcement {template_enemy.get('display_name', new_type)}"
    else:
        new_type = "bandit"
        new_name = "Reinforcement"

    from game.monster_data import get_monster
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
    }
    encounter_state.enemies.append(new_enemy)

    return f"Reinforcement arrived! A {new_name} joins the fight."


def _apply_enemy_flees(encounter_state):
    """En düşük HP'li düşman kaçar."""
    alive = [e for e in encounter_state.enemies if e["hp"] > 0]
    if not alive:
        return None

    weakest = min(alive, key=lambda e: e["hp"])
    weakest["hp"] = 0  # Savaştan çıkar (öldü değil, kaçtı)
    weakest["fled"] = True

    return f"{weakest['display_name']} flees the battle!"


def _apply_aoe_damage(encounter_state, event, players_stats):
    """Çevresel hasar: tüm düşmanlara ve oyunculara küçük hasar."""
    aoe_dmg = event.get("aoe_damage", 4)
    affected = []

    # Düşmanlara hasar
    for enemy in encounter_state.enemies:
        if enemy["hp"] > 0:
            enemy["hp"] = max(0, enemy["hp"] - aoe_dmg)
            affected.append(enemy["display_name"])

    desc = f"Environmental hazard deals {aoe_dmg} damage to all enemies!"
    if players_stats:
        desc += f" Players also take {aoe_dmg} damage."

    return desc


def _apply_ally_arrives(encounter_state, event, players_stats):
    """Müttefik gelir, oyunculara heal verir."""
    ally_heal = event.get("ally_heal", 5)
    return f"A helpful stranger arrives and heals all players for {ally_heal} HP!"
