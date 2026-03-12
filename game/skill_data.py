# game/skill_data.py — Class-based skill definitions
"""
Her class'a 3 savaş skill'i + 1 heal skill.
Skill level arttıkça base_damage/base_heal +2 artar.
"""

import random
from game.dice import get_modifier

# ─── SKILL TANIMLARI ──────────────────────────────────────────────────────────

CLASS_SKILLS = {
    "Savaşçı": {
        "combat": [
            {
                "id": "power_strike",
                "name": "Güçlü Darbe",
                "name_en": "Power Strike",
                "emoji": "⚔️",
                "ability": "strength",
                "dice": "1d8",
                "base_damage": 0,
                "dc": 10,
                "description": "Ağır bir kılıç darbesi",
            },
            {
                "id": "shield_bash",
                "name": "Kalkan Çarpması",
                "name_en": "Shield Bash",
                "emoji": "🛡️",
                "ability": "strength",
                "dice": "1d4",
                "base_damage": 0,
                "dc": 8,
                "description": "Düşmanı sersemletir, kolay ama düşük hasar",
            },
            {
                "id": "fury_rush",
                "name": "Öfke Hücumu",
                "name_en": "Fury Rush",
                "emoji": "💥",
                "ability": "strength",
                "dice": "2d6",
                "base_damage": 0,
                "dc": 14,
                "description": "Güçlü ama zor saldırı",
            },
        ],
        "heal": {
            "id": "first_aid",
            "name": "İlk Yardım",
            "name_en": "First Aid",
            "emoji": "💚",
            "ability": "wisdom",
            "dice": "1d4",
            "base_heal": 0,
            "mass": False,
            "description": "Tek kişiyi az iyileştirir",
        },
    },
    "Büyücü": {
        "combat": [
            {
                "id": "fireball",
                "name": "Ateş Topu",
                "name_en": "Fireball",
                "emoji": "🔥",
                "ability": "intelligence",
                "dice": "2d6",
                "base_damage": 0,
                "dc": 13,
                "description": "Ateş büyüsü",
            },
            {
                "id": "ice_bolt",
                "name": "Buz Oku",
                "name_en": "Ice Bolt",
                "emoji": "❄️",
                "ability": "intelligence",
                "dice": "1d8",
                "base_damage": 0,
                "dc": 10,
                "description": "Buz mermisi",
            },
            {
                "id": "lightning",
                "name": "Yıldırım",
                "name_en": "Lightning",
                "emoji": "⚡",
                "ability": "intelligence",
                "dice": "3d6",
                "base_damage": 0,
                "dc": 16,
                "description": "Çok güçlü ama çok zor",
            },
        ],
        "heal": {
            "id": "arcane_shield",
            "name": "Koruma Kalkanı",
            "name_en": "Arcane Shield",
            "emoji": "💚",
            "ability": "intelligence",
            "dice": "1d4",
            "base_heal": 0,
            "mass": False,
            "description": "Büyüyle hafif iyileştirme",
        },
    },
    "Hırsız": {
        "combat": [
            {
                "id": "sneak_attack",
                "name": "Sinsi Saldırı",
                "name_en": "Sneak Attack",
                "emoji": "🗡️",
                "ability": "dexterity",
                "dice": "2d6",
                "base_damage": 0,
                "dc": 13,
                "description": "Arkadan saldırı",
            },
            {
                "id": "blade_flurry",
                "name": "Bıçak Yağmuru",
                "name_en": "Blade Flurry",
                "emoji": "🔪",
                "ability": "dexterity",
                "dice": "1d6",
                "base_damage": 0,
                "dc": 10,
                "description": "Hızlı bıçak darbesi",
            },
            {
                "id": "deadly_strike",
                "name": "Ölümcül Darbe",
                "name_en": "Deadly Strike",
                "emoji": "☠️",
                "ability": "dexterity",
                "dice": "3d6",
                "base_damage": 0,
                "dc": 16,
                "description": "Kritik noktalara saldırı",
            },
        ],
        "heal": {
            "id": "bandage",
            "name": "Pansuman",
            "name_en": "Bandage",
            "emoji": "💚",
            "ability": "wisdom",
            "dice": "1d4",
            "base_heal": 0,
            "mass": False,
            "description": "Basit pansuman",
        },
    },
    "Rahip": {
        "combat": [
            {
                "id": "holy_smite",
                "name": "Kutsal Darbe",
                "name_en": "Holy Smite",
                "emoji": "✝️",
                "ability": "wisdom",
                "dice": "1d8",
                "base_damage": 0,
                "dc": 10,
                "description": "Kutsal enerji saldırısı",
            },
            {
                "id": "purify",
                "name": "Arındırma",
                "name_en": "Purify",
                "emoji": "✨",
                "ability": "wisdom",
                "dice": "1d6",
                "base_damage": 0,
                "dc": 8,
                "description": "Işık enerjisi",
            },
            {
                "id": "divine_judgment",
                "name": "İlahi Yargı",
                "name_en": "Divine Judgment",
                "emoji": "⚡",
                "ability": "wisdom",
                "dice": "2d8",
                "base_damage": 0,
                "dc": 14,
                "description": "Güçlü kutsal saldırı",
            },
        ],
        "heal": {
            "id": "mass_heal",
            "name": "Toplu İyileştirme",
            "name_en": "Mass Heal",
            "emoji": "💚",
            "ability": "wisdom",
            "dice": "1d6",
            "base_heal": 0,
            "mass": True,
            "description": "Tüm oyuncuları iyileştirir (Sadece Rahip!)",
        },
    },
    "Avcı": {
        "combat": [
            {
                "id": "precise_shot",
                "name": "Keskin Atış",
                "name_en": "Precise Shot",
                "emoji": "🏹",
                "ability": "dexterity",
                "dice": "1d8",
                "base_damage": 0,
                "dc": 10,
                "description": "Ok atışı",
            },
            {
                "id": "multi_shot",
                "name": "Çoklu Atış",
                "name_en": "Multi Shot",
                "emoji": "🏹",
                "ability": "dexterity",
                "dice": "1d4",
                "base_damage": 0,
                "dc": 12,
                "description": "İki ok atar (x2 vuruş)",
                "hits": 2,
            },
            {
                "id": "death_arrow",
                "name": "Ölüm Oku",
                "name_en": "Death Arrow",
                "emoji": "💀",
                "ability": "dexterity",
                "dice": "2d10",
                "base_damage": 0,
                "dc": 15,
                "description": "Güçlü tek atış",
            },
        ],
        "heal": {
            "id": "natures_touch",
            "name": "Doğa Şifası",
            "name_en": "Nature's Touch",
            "emoji": "💚",
            "ability": "wisdom",
            "dice": "1d4",
            "base_heal": 0,
            "mass": False,
            "description": "Bitki bazlı iyileştirme",
        },
    },
    "Ozan": {
        "combat": [
            {
                "id": "dissonant_chord",
                "name": "Uyumsuz Akor",
                "name_en": "Dissonant Chord",
                "emoji": "🎸",
                "ability": "charisma",
                "dice": "1d8",
                "base_damage": 0,
                "dc": 10,
                "description": "Ses dalgası hasarı",
            },
            {
                "id": "vicious_mockery",
                "name": "Alay Şarkısı",
                "name_en": "Vicious Mockery",
                "emoji": "🎵",
                "ability": "charisma",
                "dice": "1d6",
                "base_damage": 0,
                "dc": 8,
                "description": "Moral bozucu saldırı",
            },
            {
                "id": "sonic_boom",
                "name": "Sonik Patlama",
                "name_en": "Sonic Boom",
                "emoji": "💥",
                "ability": "charisma",
                "dice": "2d8",
                "base_damage": 0,
                "dc": 14,
                "description": "Güçlü ses patlaması",
            },
        ],
        "heal": {
            "id": "healing_melody",
            "name": "İyileştirme Melodisi",
            "name_en": "Healing Melody",
            "emoji": "💚",
            "ability": "charisma",
            "dice": "1d4",
            "base_heal": 0,
            "mass": False,
            "description": "Müzikle iyileştirme",
        },
    },
}


# ─── YARDIMCI FONKSİYONLAR ───────────────────────────────────────────────────

def _roll_dice(dice_str):
    """Parse '2d6' format and roll. Returns total."""
    match = dice_str.lower().strip()
    if "d" not in match:
        return int(match)
    parts = match.split("d")
    count = int(parts[0]) if parts[0] else 1
    sides = int(parts[1])
    return sum(random.randint(1, sides) for _ in range(count))


def get_skills_for_class(class_display_name):
    """Class display adına göre skill listesi döndürür.
    Returns: {"combat": [...], "heal": {...}} or None
    """
    return CLASS_SKILLS.get(class_display_name)


def get_initial_skill_levels(class_display_name):
    """Karakter oluşturulduğunda başlangıç skill seviyeleri.
    Returns: {"skill_id": 1, ...}
    """
    skills = get_skills_for_class(class_display_name)
    if not skills:
        return {}
    levels = {}
    for combat_skill in skills["combat"]:
        levels[combat_skill["id"]] = 1
    levels[skills["heal"]["id"]] = 1
    return levels


def get_skill_by_id(class_display_name, skill_id):
    """Belirli bir skill'i ID'ye göre bul. Returns skill dict or None."""
    skills = get_skills_for_class(class_display_name)
    if not skills:
        return None
    for combat_skill in skills["combat"]:
        if combat_skill["id"] == skill_id:
            return combat_skill
    if skills["heal"]["id"] == skill_id:
        return skills["heal"]
    return None


def calculate_skill_damage(skill, skill_level, ability_score):
    """Skill hasarını hesapla.
    Returns: total damage (int)
    """
    modifier = get_modifier(ability_score)
    dice_total = _roll_dice(skill["dice"])
    level_bonus = (skill_level - 1) * 2  # Her level +2 bonus
    hits = skill.get("hits", 1)

    if hits > 1:
        # Multi-hit: her vuruş ayrı roll
        total = 0
        for _ in range(hits):
            total += _roll_dice(skill["dice"]) + modifier + level_bonus
        return max(1, total)
    else:
        return max(1, dice_total + modifier + level_bonus)


def calculate_skill_heal(skill, skill_level, ability_score):
    """Skill heal miktarını hesapla.
    Returns: total heal (int)
    """
    modifier = get_modifier(ability_score)
    dice_total = _roll_dice(skill["dice"])
    level_bonus = (skill_level - 1) * 2
    return max(1, dice_total + modifier + level_bonus)


def get_all_skill_info(class_display_name, skill_levels):
    """Frontend'e gönderilecek skill bilgileri.
    Returns: [{"id": ..., "name": ..., "type": "combat"/"heal", ...}, ...]
    """
    skills = get_skills_for_class(class_display_name)
    if not skills:
        return []

    result = []
    for cs in skills["combat"]:
        level = skill_levels.get(cs["id"], 1)
        level_bonus = (level - 1) * 2
        result.append({
            "id": cs["id"],
            "name": cs["name"],
            "name_en": cs["name_en"],
            "emoji": cs["emoji"],
            "type": "combat",
            "ability": cs["ability"],
            "dice": cs["dice"],
            "dc": cs["dc"],
            "level": level,
            "level_bonus": level_bonus,
            "description": cs["description"],
        })

    hs = skills["heal"]
    level = skill_levels.get(hs["id"], 1)
    level_bonus = (level - 1) * 2
    result.append({
        "id": hs["id"],
        "name": hs["name"],
        "name_en": hs["name_en"],
        "emoji": hs["emoji"],
        "type": "heal",
        "ability": hs["ability"],
        "dice": hs["dice"],
        "dc": 0,
        "level": level,
        "level_bonus": level_bonus,
        "mass": hs.get("mass", False),
        "description": hs["description"],
    })

    return result
