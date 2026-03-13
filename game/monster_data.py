# game/monster_data.py — Monster tablosu ve yetenek tanımları
"""
Tüm düşman stat'ları kodda sabit tanımlı.
LLM düşman tipi seçer, stat'lar buradan gelir.
"""

import random

# ─── MONSTER TABLOSU ──────────────────────────────────────────────────────────

MAX_ENEMIES = 4  # Encounter başına maksimum düşman sayısı

MONSTER_TABLE = {
    # Humanos/NPCs
    "guard":         {"hp": 20, "ac": 13, "attack": "+4", "damage": "1d8+2", "xp": 50,  "abilities": []},
    "bandit":        {"hp": 18, "ac": 12, "attack": "+3", "damage": "1d6+2", "xp": 40,  "abilities": []},
    "cultist":       {"hp": 15, "ac": 11, "attack": "+3", "damage": "1d6",   "xp": 35,  "abilities": ["dark_magic"]},
    "assassin":      {"hp": 35, "ac": 15, "attack": "+6", "damage": "1d6+4", "xp": 200, "abilities": ["poison_attack"]},
    "mage":          {"hp": 25, "ac": 12, "attack": "+5", "damage": "1d10",  "xp": 150, "abilities": ["stays_back"]},
    
    # Goblinoids & Orcs
    "goblin":        {"hp": 14, "ac": 12, "attack": "+3", "damage": "1d6+1", "xp": 25,  "abilities": []},
    "goblin_scout":  {"hp": 10, "ac": 13, "attack": "+4", "damage": "1d6+1", "xp": 30,  "abilities": ["poison_attack"]},
    "goblin_shaman": {"hp": 10, "ac": 11, "attack": "+2", "damage": "1d4",   "xp": 40,  "abilities": ["heal_ally"], "behavior": "stays_back"},
    "orc":           {"hp": 30, "ac": 13, "attack": "+5", "damage": "1d12+3","xp": 100, "abilities": ["rage"]},
    "troll":         {"hp": 84, "ac": 15, "attack": "+7", "damage": "2d6+4", "xp": 400, "abilities": ["regeneration"]},

    # Undead
    "skeleton":      {"hp": 13, "ac": 13, "attack": "+4", "damage": "1d6+2", "xp": 50,  "abilities": ["undead"]},
    "zombie":        {"hp": 22, "ac": 8,  "attack": "+3", "damage": "1d6+1", "xp": 50,  "abilities": ["undead"]},
    "ghoul":         {"hp": 22, "ac": 12, "attack": "+4", "damage": "2d4+2", "xp": 100, "abilities": ["undead", "paralytic_touch"]},
    "ghost":         {"hp": 45, "ac": 11, "attack": "+5", "damage": "4d6",   "xp": 300, "abilities": ["undead"]},
    "vampire":       {"hp": 120,"ac": 16, "attack": "+8", "damage": "1d8+4", "xp": 1000,"abilities": ["undead", "life_drain"]},

    # Beasts & Monstrosities
    "wolf":          {"hp": 16, "ac": 11, "attack": "+4", "damage": "2d4+2", "xp": 35,  "abilities": ["knockdown"]},
    "bear":          {"hp": 35, "ac": 11, "attack": "+5", "damage": "2d6+3", "xp": 100, "abilities": ["rage"]},
    "giant_spider":  {"hp": 26, "ac": 14, "attack": "+5", "damage": "1d8+3", "xp": 100, "abilities": ["poison_attack"]},
    "basilisk":      {"hp": 52, "ac": 15, "attack": "+5", "damage": "2d6+3", "xp": 400, "abilities": ["paralytic_touch"]},
    "mimic":         {"hp": 58, "ac": 12, "attack": "+5", "damage": "2d8+3", "xp": 300, "abilities": ["paralytic_touch"]},
    
    # Elementals & Constructs
    "elemental":     {"hp": 90, "ac": 14, "attack": "+6", "damage": "2d6+4", "xp": 500, "abilities": []},
    "golem":         {"hp": 100,"ac": 17, "attack": "+7", "damage": "2d8+5", "xp": 800, "abilities": []},

    # Demons & Dragons
    "demon":         {"hp": 85, "ac": 15, "attack": "+6", "damage": "2d8+4", "xp": 700, "abilities": ["dark_magic"]},
    "dragon":        {"hp": 200,"ac": 18, "attack": "+10","damage": "2d10+6","xp": 3000,"abilities": ["dragon_breath"]},
}

# Fallback: bilinmeyen tip gelirse bu kullanılır
DEFAULT_MONSTER_TYPE = "bandit"

# ─── YETENEK TANIMLARI ────────────────────────────────────────────────────────

ABILITY_EFFECTS = {
    "heal_ally": {
        "cooldown": 3,
        "effect": "heal_lowest_ally",
        "heal": "1d4+2",
        "description": "Heals the lowest HP ally",
    },
    "poison_attack": {
        "cooldown": 2,
        "effect": "dot",
        "dot_damage": 3,
        "dot_turns": 2,
        "description": "Applies poison: 3 damage for 2 turns",
    },
    "dark_magic": {
        "cooldown": 3,
        "effect": "dot",
        "dot_damage": 5,
        "dot_turns": 3,
        "description": "Curses target with dark magic: 5 damage for 3 turns",
    },
    "dragon_breath": {
        "cooldown": 4,
        "effect": "aoe_damage",
        "damage": "4d6",
        "description": "Breathes devastating element on all players",
    },
    "life_drain": {
        "cooldown": 3,
        "effect": "life_drain",
        "damage": "3d6",
        "description": "Drains life target, healing self for damage dealt",
    },
    "stays_back": {
        "passive": True,
        "effect": "ranged_only",
        "description": "Stays at range, avoids melee",
    },
    "knockdown": {
        "trigger": "on_hit",
        "effect": "stun",
        "stun_turns": 1,
        "save_dc": 12,
        "description": "On hit: target must save DC 12 or be stunned 1 turn",
    },
    "paralytic_touch": {
        "trigger": "on_hit",
        "effect": "stun",
        "stun_turns": 1,
        "save_dc": 14,
        "description": "On hit: target must save DC 14 or become paralyzed (stunned)",
    },
    "rage": {
        "trigger": "hp_below_50",
        "effect": "damage_bonus",
        "bonus": 3,
        "description": "When below 50% HP, gains +3 damage",
    },
    "regeneration": {
        "cooldown": 1, # triggers every turn essentially but via active effect parser for simple setup, or we make it passive logic.
        "effect": "heal_self",
        "heal": "1d6",
        "description": "Regenerates HP every few turns",
    },
    "undead": {
        "passive": True,
        "immunities": ["necrotic"],
        "vulnerabilities": ["radiant"],
        "description": "Immune to necrotic, vulnerable to radiant",
    },
}


# ─── YARDIMCI FONKSİYONLAR ───────────────────────────────────────────────────

def parse_attack_bonus(attack_str):
    """"+4" → int 4"""
    try:
        return int(attack_str.replace("+", "").strip())
    except (ValueError, AttributeError):
        return 2  # fallback


def parse_damage(damage_str):
    """
    "1d8+2" formatını parse edip zar atar, toplam hasarı döner.
    "2d4+2", "1d6", "1d12+3" gibi formatları destekler.
    """
    damage_str = damage_str.strip().lower()

    # Bonus kısmını ayır
    bonus = 0
    if "+" in damage_str:
        parts = damage_str.split("+")
        dice_part = parts[0].strip()
        bonus = int(parts[1].strip())
    elif "-" in damage_str and "d" in damage_str:
        parts = damage_str.split("-")
        dice_part = parts[0].strip()
        bonus = -int(parts[1].strip())
    else:
        dice_part = damage_str

    # Zar kısmını parse et
    if "d" in dice_part:
        d_parts = dice_part.split("d")
        count = int(d_parts[0]) if d_parts[0] else 1
        sides = int(d_parts[1])
        total = sum(random.randint(1, sides) for _ in range(count))
    else:
        total = int(dice_part)

    return max(1, total + bonus)


def get_monster(monster_type):
    """
    Monster tablosundan stat kopyası döner.
    Bilinmeyen tip → DEFAULT_MONSTER_TYPE fallback.
    Her çağrıda yeni dict (instance bazlı HP takibi için).
    """
    key = monster_type.lower().strip().replace(" ", "_")

    if key in MONSTER_TABLE:
        template = MONSTER_TABLE[key]
    else:
        print(f"   ⚠️  Bilinmeyen monster tipi: '{monster_type}', fallback: {DEFAULT_MONSTER_TYPE}")
        template = MONSTER_TABLE[DEFAULT_MONSTER_TYPE]

    # Template'i kopyala (her düşman kendi HP'sine sahip olsun)
    stats = {
        "hp": template["hp"],
        "max_hp": template["hp"],
        "ac": template["ac"],
        "attack_bonus": parse_attack_bonus(template["attack"]),
        "damage_str": template["damage"],
        "xp": template["xp"],
        "abilities": list(template.get("abilities", [])),
        "behavior": template.get("behavior", None),
    }
    return stats


def get_monster_type_list():
    """Prompt için mevcut monster tiplerinin listesini döner."""
    return list(MONSTER_TABLE.keys())


def get_ability_effect(ability_name):
    """Yetenek detaylarını döner, yoksa None."""
    return ABILITY_EFFECTS.get(ability_name)
