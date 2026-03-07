# game/character_creator.py

import os
import yaml
import config

# ─── SABİTLER ──────────────────────────────────────────────

# Point Buy maliyet tablosu
POINT_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
TOTAL_POINTS = 27
MIN_SCORE = 8
MAX_SCORE = 15

# Irk bonusları
RACES = {
    "1": {
        "name": "Human",
        "display": "İnsan",
        "bonuses": {
            "strength": 1, "dexterity": 1, "constitution": 1,
            "intelligence": 1, "wisdom": 1, "charisma": 1
        }
    },
    "2": {
        "name": "Elf",
        "display": "Elf",
        "bonuses": {"dexterity": 2, "intelligence": 1}
    },
    "3": {
        "name": "Dwarf",
        "display": "Cüce",
        "bonuses": {"constitution": 2, "wisdom": 1}
    },
    "4": {
        "name": "Halfling",
        "display": "Halfling",
        "bonuses": {"dexterity": 2, "charisma": 1}
    },
    "5": {
        "name": "Half-Orc",
        "display": "Yarı-Ork",
        "bonuses": {"strength": 2, "constitution": 1}
    }
}

# Sınıflar ve önerilen ability'leri
CLASSES = {
    "1": {
        "name": "Fighter",
        "display": "Savaşçı",
        "primary": "strength",
        "hp_dice": 10,
        "tip": "💪 Güç ve Anayasa önemli"
    },
    "2": {
        "name": "Wizard",
        "display": "Büyücü",
        "primary": "intelligence",
        "hp_dice": 6,
        "tip": "🧠 Zeka önemli"
    },
    "3": {
        "name": "Rogue",
        "display": "Hırsız",
        "primary": "dexterity",
        "hp_dice": 8,
        "tip": "🗡️ Çeviklik önemli"
    },
    "4": {
        "name": "Cleric",
        "display": "Rahip",
        "primary": "wisdom",
        "hp_dice": 8,
        "tip": "✨ Bilgelik önemli"
    },
    "5": {
        "name": "Ranger",
        "display": "Avcı",
        "primary": "dexterity",
        "hp_dice": 10,
        "tip": "🏹 Çeviklik ve Bilgelik önemli"
    },
    "6": {
        "name": "Bard",
        "display": "Ozan",
        "primary": "charisma",
        "hp_dice": 8,
        "tip": "🎵 Karizma önemli"
    }
}

ABILITY_DISPLAY = {
    "strength":     "Güç",
    "dexterity":    "Çeviklik",
    "constitution": "Anayasa",
    "intelligence": "Zeka",
    "wisdom":       "Bilgelik",
    "charisma":     "Karizma"
}

# ─── YARDIMCI FONKSİYONLAR ─────────────────────────────────

def calculate_spent_points(abilities):
    return sum(POINT_COST[score] for score in abilities.values())

def print_abilities(abilities, spent):
    remaining = TOTAL_POINTS - spent
    print("\n┌─────────────────────────────────────┐")
    print(f"│  Kalan Puan: {remaining}/27                   │")
    print("├─────────────────────────────────────┤")
    for i, (ability, score) in enumerate(abilities.items(), 1):
        modifier = (score - 10) // 2
        mod_str = f"+{modifier}" if modifier >= 0 else str(modifier)
        cost = POINT_COST[score]
        display = ABILITY_DISPLAY[ability]
        print(f"│  {i}. {display:<12} {score:>2}  ({mod_str})  Maliyet: {cost}  │")
    print("└─────────────────────────────────────┘")

def print_race_bonuses(race):
    bonuses = race["bonuses"]
    bonus_str = ", ".join(
        [f"{ABILITY_DISPLAY[k]} +{v}" for k, v in bonuses.items()]
    )
    print(f"  Irk bonusları: {bonus_str}")

# ─── KARAKTER OLUŞTURMA ─────────────────────────────────────

def create_character():
    print("\n" + "═" * 40)
    print("      ⚔️  KARAKTER OLUŞTUR  ⚔️")
    print("═" * 40)

    # ── İsim ──
    name = input("\nKarakter ismi: ").strip()
    while not name:
        name = input("İsim boş olamaz: ").strip()

    # ── Irk seç ──
    print("\n📖 IRKINIZI SEÇİN:")
    print("─" * 40)
    for key, race in RACES.items():
        print(f"  {key}. {race['display']}")
        print(f"     ", end="")
        print_race_bonuses(race)

    race_choice = input("\nSeçim (1-5): ").strip()
    while race_choice not in RACES:
        race_choice = input("Geçersiz seçim, tekrar (1-5): ").strip()
    selected_race = RACES[race_choice]
    print(f"✅ {selected_race['display']} seçildi!")

    # ── Sınıf seç ──
    print("\n⚔️  SINIFINI SEÇ:")
    print("─" * 40)
    for key, cls in CLASSES.items():
        print(f"  {key}. {cls['display']:<12} {cls['tip']}")

    class_choice = input("\nSeçim (1-6): ").strip()
    while class_choice not in CLASSES:
        class_choice = input("Geçersiz seçim, tekrar (1-6): ").strip()
    selected_class = CLASSES[class_choice]
    print(f"✅ {selected_class['display']} seçildi!")
    print(f"\n💡 İpucu: {selected_class['tip']}")

    # ── Arka plan ──
    print("\n📜 ARKA PLAN (karakterinin geçmişi):")
    background = input("Kısaca anlat (örn: gezgin savaşçı, köy koruyucusu): ").strip()
    if not background:
        background = "Mysterious adventurer"

    # ── Point Buy ──
    print("\n🎯 ABILITY SCORE DAĞITIMI (Point Buy)")
    print("─" * 40)
    print(f"Toplam {TOTAL_POINTS} puan var. Her ability başlangıçta 8.")
    print("Puan maliyeti: 8=0, 9=1, 10=2, 11=3, 12=4, 13=5, 14=7, 15=9")
    print("Min: 8, Max: 15 (ırk bonusları sonra eklenir)\n")

    # hepsi 8'den başlar
    abilities = {
        "strength": 8,
        "dexterity": 8,
        "constitution": 8,
        "intelligence": 8,
        "wisdom": 8,
        "charisma": 8
    }

    ability_keys = list(abilities.keys())

    while True:
        spent = calculate_spent_points(abilities)
        print_abilities(abilities, spent)
        remaining = TOTAL_POINTS - spent

        print("\nNe yapmak istiyorsun?")
        print("  1-6: O ability'yi artır (+1)")
        print("  r:   Sıfırla (hepsini 8'e döndür)")
        print("  t:   Tamamla")

        choice = input("\nSeçim: ").strip().lower()

        if choice == "t":
            if remaining > 0:
                confirm = input(f"⚠️  {remaining} puan harcamadın. Devam? (e/h): ").strip().lower()
                if confirm != "e":
                    continue
            break

        elif choice == "r":
            abilities = {k: 8 for k in ability_keys}
            print("🔄 Sıfırlandı!")

        elif choice in ["1", "2", "3", "4", "5", "6"]:
            idx = int(choice) - 1
            ability = ability_keys[idx]
            current = abilities[ability]

            if current >= MAX_SCORE:
                print(f"⚠️  {ABILITY_DISPLAY[ability]} zaten maksimumda (15)!")
                continue

            new_score = current + 1
            new_cost = POINT_COST[new_score] - POINT_COST[current]

            if remaining < new_cost:
                print(f"⚠️  Yeterli puan yok! Bu artış {new_cost} puan gerektirir.")
                continue

            abilities[ability] = new_score

        else:
            print("Geçersiz seçim!")

    # ── Irk bonuslarını ekle ──
    print("\n🎊 Irk bonusları ekleniyor...")
    final_abilities = abilities.copy()
    for ability, bonus in selected_race["bonuses"].items():
        final_abilities[ability] = final_abilities.get(ability, 8) + bonus
        print(f"  {ABILITY_DISPLAY[ability]}: {abilities[ability]} + {bonus} = {final_abilities[ability]}")

    # ── HP hesapla ──
    # Seviye 1'de: hp_dice'ın max değeri + constitution modifier
    con_modifier = (final_abilities["constitution"] - 10) // 2
    max_hp = selected_class["hp_dice"] + con_modifier
    max_hp = max(max_hp, 1)  # minimum 1 HP

    # ── Karakter dict'i oluştur ──
    character = {
        "name": name,
        "race": selected_race["display"],
        "class": selected_class["display"],
        "level": 1,
        "abilities": final_abilities,
        "hp": max_hp,
        "max_hp": max_hp,
        "armor_class": 10 + (final_abilities["dexterity"] - 10) // 2,
        "skills": [],
        "background": background
    }

    # ── Özeti göster ──
    print("\n" + "═" * 40)
    print("      ✅ KARAKTER OLUŞTURULDU!")
    print("═" * 40)
    print(f"  İsim:    {character['name']}")
    print(f"  Irk:     {character['race']}")
    print(f"  Sınıf:   {character['class']}")
    print(f"  HP:      {character['max_hp']}")
    print(f"  Zırh:    {character['armor_class']}")
    print("\n  Ability Scores (ırk bonusu dahil):")
    for ability, score in final_abilities.items():
        modifier = (score - 10) // 2
        mod_str = f"+{modifier}" if modifier >= 0 else str(modifier)
        print(f"    {ABILITY_DISPLAY[ability]:<12} {score:>2}  ({mod_str})")

    # ── YAML'a kaydet ──
    os.makedirs(config.character_dir, exist_ok=True)
    filename = f"{name.lower().replace(' ', '_')}.yaml"
    filepath = os.path.join(config.character_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(character, f, allow_unicode=True, default_flow_style=False)

    print(f"\n💾 Karakter kaydedildi: {filepath}")
    return character