import re
import json
import requests
import config
from game.dice import d20, get_modifier

# ─── ENCOUNTER YAPISI ────────────────────────────────────────────────────────
# game_state.active_encounter = {
#     "enemy_name": "Goblin",
#     "hp": 7,
#     "max_hp": 7,
#     "ac": 13,
#     "damage_dice": 6,    # d6
#     "xp_reward": 50
# }

# ─── SAVAŞ TESPİTİ ───────────────────────────────────────────────────────────

def check_combat_start(action):
    """
    Oyuncu aksiyonunu analiz eder, savaş başlıyor mu?
    Kesin değilse → False döner (yanlış pozitiften kaçın).
    Döner: {"combat": True, "enemy": "Guard", "hp": 12, "ac": 13, "damage_dice": 6, "xp_reward": 50}
         veya {"combat": False}
    """
    prompt = f"""You are a D&D combat detector. Decide if this action STARTS combat.

PLAYER ACTION: "{action}"

COMBAT TRIGGERS (player must clearly intend to physically attack):
- "I attack", "I strike", "I stab", "I shoot", "I hit", "I slash", "I punch"
- Any direct physical assault on a target

NOT COMBAT:
- Threats, intimidation, shouting
- Drawing a weapon without attacking
- Defensive stances
- Pushing or grabbing (use Strength check instead)
- Any ambiguous or unclear intent

RULE: If you are not 100% certain this is an attack → combat: false

If combat: true, invent a believable enemy for the scene with:
- hp: 5-20 depending on enemy type
- ac: 10-16 depending on armor
- damage_dice: 4, 6, or 8
- xp_reward: 25-150

Respond ONLY with valid JSON, no explanation:
If combat: {{"combat": true, "enemy": "Guard", "hp": 12, "ac": 13, "damage_dice": 6, "xp_reward": 50}}
If not:    {{"combat": false}}"""

    try:
        response = requests.post(
            f"{config.base_url}/api/chat",
            json={
                "model": config.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {"num_ctx": 2048, "temperature": 0.1, "num_predict": 60}
            }
        )
        answer = response.json()["message"]["content"].strip()
        answer = re.sub(r'```json|```', '', answer).strip()
        match = re.search(r'\{.*?\}', answer, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if data.get("combat"):
                return {
                    "combat": True,
                    "enemy_name": data.get("enemy", "Enemy"),
                    "hp": int(data.get("hp", 10)),
                    "max_hp": int(data.get("hp", 10)),
                    "ac": int(data.get("ac", 12)),
                    "damage_dice": int(data.get("damage_dice", 6)),
                    "xp_reward": int(data.get("xp_reward", 50))
                }
        return {"combat": False}
    except Exception as e:
        print(f"   ❌ check_combat_start HATA: {e}")
        return {"combat": False}

# ─── SALDIRI ROLÜ ────────────────────────────────────────────────────────────

def player_attack(game_state, player_name, session_id, user):
    """
    Oyuncunun saldırı zarını atar.
    Döner: (roll_message_for_gm, damage_dealt, enemy_defeated)
    """
    from game.dice import d20, get_modifier
    from db.session_manager import save_message
    from game.xp_manager import grant_ability_xp

    encounter = game_state.active_encounter
    char = next((c for c in game_state.characters if c['name'] == player_name), game_state.characters[0])
    abilities = char.get("abilities", {})

    # Saldırı: STR modifier
    str_mod = get_modifier(abilities.get("strength", 10))
    attack_roll = d20()
    attack_total = attack_roll + str_mod
    ac = encounter["ac"]

    print(f"\n⚔️  SALDIRI")
    print(f"   Saldırı zarı: {attack_roll} + {str_mod:+d} = {attack_total} vs AC {ac}")

    # İsabet kontrolü
    if attack_roll == 20:
        # Kritik: çift hasar
        damage = _roll_damage(encounter["damage_dice"]) * 2
        hit_label = "CRITICAL HIT"
        print(f"   ⭐ KRİTİK İSABET! Hasar: {damage}")
    elif attack_roll == 1 or attack_total < ac:
        damage = 0
        hit_label = "MISS"
        print(f"   💨 ISKALADIK")
    else:
        damage = _roll_damage(encounter["damage_dice"])
        hit_label = "HIT"
        print(f"   ✅ İSABET! Hasar: {damage}")

    # Grant strength XP on successful hits
    if damage > 0:
        grant_ability_xp(session_id, player_name, "strength", amount=5)

    # Düşman HP güncelle
    enemy_defeated = False
    if damage > 0:
        encounter["hp"] = max(0, encounter["hp"] - damage)
        if encounter["hp"] <= 0:
            enemy_defeated = True
            print(f"   💀 {encounter['enemy_name']} yenildi!")

    # GM'e gidecek mesaj
    roll_message = (
        f"Player: {player_name}\n"
        f"Attack roll: {attack_roll} + {str_mod} (STR) = {attack_total} vs AC {ac}\n"
        f"Result: {hit_label}\n"
    )
    if damage > 0:
        roll_message += f"Damage dealt: {damage}\n"
        roll_message += f"Enemy HP: {encounter['hp']}/{encounter['max_hp']}"
    if enemy_defeated:
        roll_message += f"\n{encounter['enemy_name']} has been defeated!"

    # DB'ye kaydet
    db_msg = f"{player_name} attacks {encounter['enemy_name']}: roll {attack_roll}+{str_mod}={attack_total} vs AC {ac} — {hit_label}"
    if damage > 0:
        db_msg += f", {damage} damage"
    save_message(session_id, user.get("id") if user else None, "user", db_msg)

    return roll_message, damage, enemy_defeated

def enemy_attack(game_state, player_name, session_id):
    """
    Düşman saldırır, oyuncuya hasar verir.
    Döner: (hasar_miktarı, gm_mesajı)
    """
    from db.session_manager import save_message

    encounter = game_state.active_encounter
    char = next((c for c in game_state.characters if c['name'] == player_name), game_state.characters[0])
    ac = char.get("armor_class", 12)

    attack_roll = d20()
    enemy_mod = 2  # Basit düşman saldırı bonusu

    print(f"\n👹 DÜŞMAN SALDIRISI")
    print(f"   {encounter['enemy_name']} saldırıyor: {attack_roll}+{enemy_mod} = {attack_roll+enemy_mod} vs AC {ac}")

    damage = 0
    if attack_roll + enemy_mod >= ac:
        damage = _roll_damage(encounter["damage_dice"])
        print(f"   ✅ İsabet! Hasar: {damage}")
    else:
        print(f"   💨 Düşman ıssaladı")

    gm_message = (
        f"{encounter['enemy_name']} attacks {player_name}: "
        f"roll {attack_roll}+{enemy_mod}={attack_roll+enemy_mod} vs AC {ac} — "
        f"{'HIT, ' + str(damage) + ' damage' if damage > 0 else 'MISS'}"
    )
    save_message(session_id, None, "user", gm_message)

    return damage, gm_message

# ─── YARDIMCI ────────────────────────────────────────────────────────────────

def _roll_damage(damage_dice):
    import random
    return random.randint(1, damage_dice)

def format_encounter_status(game_state):
    enc = game_state.active_encounter
    if not enc:
        return ""
    bar_len = 10
    hp_pct = enc["hp"] / enc["max_hp"]
    filled = int(bar_len * hp_pct)
    bar = "█" * filled + "░" * (bar_len - filled)
    return (
        f"\n⚔️  SAVAŞ AKTİF\n"
        f"   Düşman: {enc['enemy_name']}  HP: [{bar}] {enc['hp']}/{enc['max_hp']}  AC: {enc['ac']}"
    )