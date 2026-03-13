# game/combat.py — Combat logic (multi-enemy, code-driven)
"""
Tüm combat kararları ve state yönetimi kod tarafında.
LLM sadece narrative üretir.

check_combat_start() KALDIRILDI — artık LLM [ENCOUNTER] bloğu ekler,
encounter_manager parse eder.
"""

from game.dice import d20, get_modifier
from game.monster_data import parse_damage
from game.encounter_manager import get_alive_enemies, is_encounter_over


# ─── OYUNCU SALDIRISI (çoklu düşman, hedef seçimli) ──────────────────────────

def player_attack_target(game_state, player_name, target_index, session_id, user):
    """
    Oyuncu belirli bir düşmana saldırır.

    Args:
        game_state: GameState
        player_name: saldıran oyuncunun adı
        target_index: düşmanın encounter_state.enemies içindeki ID'si
        session_id: oturum ID (DB kaydı için — combat sırasında KAYDETME)
        user: kullanıcı dict

    Returns:
        (roll_message, damage, enemy_defeated, encounter_over)
    """
    from game.xp_manager import grant_ability_xp

    encounter = game_state.active_encounter
    if not encounter or not encounter.is_active:
        return "No active encounter!", 0, False, False

    # Hedef düşmanı bul
    target_enemy = None
    for enemy in encounter.enemies:
        if enemy["id"] == target_index:
            target_enemy = enemy
            break

    if not target_enemy or target_enemy["hp"] <= 0:
        # Geçersiz hedef, hayattaki ilk düşmanı seç
        alive = get_alive_enemies(encounter)
        if not alive:
            return "No enemies left!", 0, False, True
        target_enemy = alive[0]

    # Karakter bilgileri
    char = next((c for c in game_state.characters if c['name'] == player_name), None)
    if not char:
        char = game_state.characters[0] if game_state.characters else {"abilities": {}}

    abilities = char.get("abilities", {})
    str_mod = get_modifier(abilities.get("strength", 10))

    # Saldırı zarı
    attack_roll = d20()
    attack_total = attack_roll + str_mod
    ac = target_enemy["ac"]
    
    print(f"🐞 DEBUG [Combat]: Player '{player_name}' attacking '{target_enemy['display_name']}'. AC: {ac}, Base Roll: {attack_roll}, Mod: {str_mod}, Total: {attack_total}")

    # İsabet kontrolü
    if attack_roll == 20:
        damage = parse_damage(target_enemy["damage_str"]) * 2
        hit_label = "CRITICAL HIT"
    elif attack_roll == 1 or attack_total < ac:
        damage = 0
        hit_label = "MISS"
    else:
        # Oyuncunun kendi hasar zarı (basit: 1d8 + str_mod)
        import random
        damage = random.randint(1, 8) + max(0, str_mod)
        hit_label = "HIT"

    # XP ver (combat sırasında ability xp — DB'ye kaydedilir ama mesaj DEĞİL)
    if damage > 0:
        grant_ability_xp(session_id, player_name, "strength", amount=5)

    # Düşman HP güncelle
    enemy_defeated = False
    if damage > 0:
        target_enemy["hp"] = max(0, target_enemy["hp"] - damage)
        if target_enemy["hp"] <= 0:
            enemy_defeated = True

    # Encounter bitti mi?
    encounter_over = is_encounter_over(encounter)

    # Mesaj (bu sadece frontend'e gider, DB'ye kaydedilmez)
    roll_message = (
        f"Player: {player_name}\n"
        f"Target: {target_enemy['display_name']}\n"
        f"Attack roll: {attack_roll} + {str_mod} (STR) = {attack_total} vs AC {ac}\n"
        f"Result: {hit_label}\n"
    )
    if damage > 0:
        roll_message += f"Damage dealt: {damage}\n"
        roll_message += f"Enemy HP: {target_enemy['hp']}/{target_enemy['max_hp']}"
    if enemy_defeated:
        roll_message += f"\n{target_enemy['display_name']} has been defeated!"
    if encounter_over:
        roll_message += "\nAll enemies have been defeated!"

    # Combat log'a ekle (özet için)
    encounter.combat_log.append({
        "type": "player_attack",
        "player": player_name,
        "target": target_enemy["display_name"],
        "roll": attack_roll,
        "total": attack_total,
        "damage": damage,
        "hit": hit_label,
    })

    print(f"🐞 DEBUG [Combat]: Player attack result -> Hit: {hit_label}, Damage: {damage}, Enemy Defeated: {enemy_defeated}, Encounter Over: {encounter_over}")
    return roll_message, damage, enemy_defeated, encounter_over


# ─── ESKİ TEK DÜŞMAN UYUMLULUĞU (player_attack wrapper) ─────────────────────

def player_attack(game_state, player_name, session_id, user, target_index=None):
    """
    Eski API uyumluluğu: target_index verilmezse ilk hayattaki düşmana saldırır.
    Döner: (roll_message, damage, enemy_defeated)
    """
    encounter = game_state.active_encounter
    if not encounter:
        return "No active encounter!", 0, False

    if target_index is None:
        alive = get_alive_enemies(encounter)
        target_index = alive[0]["id"] if alive else 0

    msg, dmg, defeated, enc_over = player_attack_target(
        game_state, player_name, target_index, session_id, user
    )
    return msg, dmg, defeated


# ─── DÜŞMAN SALDIRISI (encounter_manager kullanır) ───────────────────────────

def enemy_turn_all(game_state, player_targets, session_id):
    """
    Tüm düşmanların saldırılarını işler.

    Args:
        game_state: GameState
        player_targets: [{name, ac, hp, max_hp}, ...]
        session_id: oturum ID

    Returns:
        list of attack results (encounter_manager.enemy_turn çıktısı)
    """
    from game.encounter_manager import enemy_turn

    encounter = game_state.active_encounter
    if not encounter or not encounter.is_active:
        print(f"🐞 DEBUG [Combat]: enemy_turn_all aborted. No active encounter.")
        return []

    print(f"🐞 DEBUG [Combat]: Triggering enemy_turn_all for session {session_id}.")
    results = enemy_turn(encounter, player_targets)

    # Combat log'a ekle
    for r in results:
        encounter.combat_log.append({
            "type": "enemy_attack",
            "enemy": r["enemy_name"],
            "target": r.get("target_player"),
            "damage": r["damage"],
            "hit": r["hit"],
            "ability": r.get("ability_used"),
        })

    return results


# ─── ESKİ API UYUMLULUĞU: enemy_attack ──────────────────────────────────────

def enemy_attack(game_state, player_name, session_id):
    """
    Eski API uyumluluğu: tek düşman, tek oyuncu.
    Döner: (hasar_miktarı, gm_mesajı)
    """
    encounter = game_state.active_encounter
    if not encounter or not encounter.is_active:
        return 0, "No active encounter"

    char = next((c for c in game_state.characters if c['name'] == player_name), None)
    if not char:
        char = game_state.characters[0] if game_state.characters else {"armor_class": 12}

    player_targets = [{
        "name": player_name,
        "ac": char.get("armor_class", 12),
        "hp": char.get("hp", 10),
        "max_hp": char.get("max_hp", 10),
    }]

    results = enemy_turn_all(game_state, player_targets, session_id)

    total_damage = 0
    messages = []
    for r in results:
        if r["target_player"] == player_name and r["damage"] > 0:
            total_damage += r["damage"]
        messages.append(r["message"])

    return total_damage, "\n".join(messages)


# ─── ENCOUNTER STATUS DISPLAY ────────────────────────────────────────────────

def format_encounter_status(game_state):
    """Oyuncuya gösterilecek encounter durumu."""
    from game.encounter_manager import format_encounter_display

    enc = game_state.active_encounter
    if not enc:
        return ""
    return format_encounter_display(enc)