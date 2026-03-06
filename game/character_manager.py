import os
import yaml
import json
import config
from db.database import get_connection
from game.dice import get_modifier

def load_character_from_yaml(filename):
    path = os.path.join(config.character_dir, filename)
    if not os.path.exists(path):
        print(f"{filename} bulunamadı.")
        return None
    with open(path, 'r', encoding='utf-8') as f:
        character = yaml.safe_load(f)
    return character

def save_character_to_db(user_id, character_data):
    character_json = json.dumps(character_data)  # dict → string
    name = character_data.get('name', 'İsimsiz')
    try:
        conn = get_connection()
        conn.execute(
            "INSERT INTO characters (user_id, name, data) VALUES (?, ?, ?)",
            (user_id, name, character_json)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Karakter kaydedilemedi: {e}")
        return None

def get_character_from_db(user_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT data FROM characters WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return json.loads(row[0])  # string → dict

def update_character_hp(user_id, new_hp):
    character = get_character_from_db(user_id)
    if character is None:
        return None
    character['hp'] = new_hp  # hp güncelle
    character_json = json.dumps(character)
    conn = get_connection()
    conn.execute(
        "UPDATE characters SET data = ? WHERE user_id = ?",
        (character_json, user_id)
    )
    conn.commit()
    conn.close()
    return True

def get_character_summary(character_data):
    abilities = character_data.get('abilities', {})

    str_mod = get_modifier(abilities.get('strength', 10))
    dex_mod = get_modifier(abilities.get('dexterity', 10))
    con_mod = get_modifier(abilities.get('constitution', 10))
    int_mod = get_modifier(abilities.get('intelligence', 10))
    wis_mod = get_modifier(abilities.get('wisdom', 10))
    cha_mod = get_modifier(abilities.get('charisma', 10))

    def fmt(mod):
        return f"+{mod}" if mod >= 0 else str(mod)

    skills = ", ".join(character_data.get('skills', []))

    # her satır ayrı string, + ile birleştir, kayma olmaz
    summary = (
        f"{character_data.get('name')} | {character_data.get('race')} {character_data.get('class')} | Seviye {character_data.get('level')}\n"
        f"HP: {character_data.get('hp')}/{character_data.get('max_hp')} | Zırh: {character_data.get('armor_class')}\n"
        f"Güç: {abilities.get('strength')}({fmt(str_mod)}) "
        f"Çeviklik: {abilities.get('dexterity')}({fmt(dex_mod)}) "
        f"Anayasa: {abilities.get('constitution')}({fmt(con_mod)})\n"
        f"Zeka: {abilities.get('intelligence')}({fmt(int_mod)}) "
        f"Bilgelik: {abilities.get('wisdom')}({fmt(wis_mod)}) "
        f"Karizma: {abilities.get('charisma')}({fmt(cha_mod)})\n"
        f"Yetenekler: {skills}\n"
        f"Arka plan: {character_data.get('background')}"
    )

    return summary