import json
from db.database import get_connection

# Genel seviye XP eşikleri (toplam XP)
LEVEL_THRESHOLDS = [0, 300, 900, 2700, 6500, 14000]

# Ability XP eşikleri (her ability kendi sayacını tutar)
ABILITY_THRESHOLDS = [0, 50, 150, 300, 500, 750]

# ─── DB İŞLEMLERİ ────────────────────────────────────────────────────────────

def get_player_stats(session_id, player_name):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM player_stats WHERE session_id = ? AND player_name = ?",
        (session_id, player_name)
    ).fetchone()
    conn.close()
    if row:
        stats = dict(row)
        stats["ability_xp"] = json.loads(stats.get("ability_xp") or "{}")
        return stats
    return None

def init_player_stats(session_id, player_name, character):
    """İlk girişte player_stats satırı oluştur."""
    existing = get_player_stats(session_id, player_name)
    if existing:
        return existing

    abilities = character.get("abilities", {})
    max_hp = character.get("max_hp", 10)
    hp = character.get("hp", max_hp)
    gold = character.get("gold", 0)

    ability_xp = {a: 0 for a in abilities}

    conn = get_connection()
    conn.execute(
        """INSERT INTO player_stats
           (session_id, player_name, hp, max_hp, gold, xp, level, ability_xp)
           VALUES (?, ?, ?, ?, ?, 0, 1, ?)""",
        (session_id, player_name, hp, max_hp, gold, json.dumps(ability_xp))
    )
    conn.commit()
    conn.close()
    return get_player_stats(session_id, player_name)

def _save_stats(session_id, player_name, stats):
    ability_xp_str = json.dumps(stats.get("ability_xp", {}))
    conn = get_connection()
    conn.execute(
        """UPDATE player_stats SET
           hp=?, max_hp=?, gold=?, xp=?, level=?, ability_xp=?
           WHERE session_id=? AND player_name=?""",
        (stats["hp"], stats["max_hp"], stats["gold"],
         stats["xp"], stats["level"], ability_xp_str,
         session_id, player_name)
    )
    conn.commit()
    conn.close()

# ─── XP VER ──────────────────────────────────────────────────────────────────

def grant_general_xp(session_id, player_name, amount, reason=""):
    """Her aksiyon sonrası genel XP verir. Seviye kontrolü yapar."""
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return []

    stats["xp"] += amount
    events = []

    # Seviye atladı mı?
    for lvl, threshold in enumerate(LEVEL_THRESHOLDS):
        if lvl <= stats["level"]:
            continue
        if stats["xp"] >= threshold:
            stats["level"] = lvl
            stats["max_hp"] += 5
            stats["hp"] = min(stats["hp"] + 5, stats["max_hp"])  # HP de artsın
            events.append(f"🎉 SEVİYE ATLADI: {lvl}! Max HP +5")
            print(f"   🎉 {player_name} seviye {lvl}'e yükseldi! Max HP → {stats['max_hp']}")

    if reason:
        print(f"   📈 Genel XP +{amount} ({reason}) → Toplam: {stats['xp']}")

    _save_stats(session_id, player_name, stats)
    return events

def grant_ability_xp(session_id, player_name, ability, amount=5):
    """
    Başarılı ability check sonrası o ability'e XP verir.
    Eşik dolunca ability score +1 artar.
    """
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return None

    ability_xp = stats.get("ability_xp", {})
    ability_xp[ability] = ability_xp.get(ability, 0) + amount

    leveled_up = False
    # Eşik kontrolü
    current_threshold_idx = 0
    for i, t in enumerate(ABILITY_THRESHOLDS):
        if ability_xp[ability] >= t:
            current_threshold_idx = i

    # Bir önceki XP'den eşik geçildi mi?
    prev_xp = ability_xp[ability] - amount
    prev_threshold_idx = 0
    for i, t in enumerate(ABILITY_THRESHOLDS):
        if prev_xp >= t:
            prev_threshold_idx = i

    if current_threshold_idx > prev_threshold_idx:
        leveled_up = True
        print(f"   ⬆️  {ability.capitalize()} eşiği aşıldı! Ability score +1 artacak.")

    stats["ability_xp"] = ability_xp
    _save_stats(session_id, player_name, stats)

    print(f"   📈 {ability.capitalize()} XP +{amount} → {ability_xp[ability]}")
    return leveled_up

def grant_combat_xp(session_id, player_name, xp_reward):
    """Düşman öldürünce XP ver."""
    return grant_general_xp(session_id, player_name, xp_reward, reason="düşman yenildi")

def grant_quest_rewards(session_id, player_name, quest):
    """Quest tamamlanınca gold + XP ver."""
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return

    stats["gold"] += quest.get("reward_gold", 0)
    _save_stats(session_id, player_name, stats)

    if quest.get("reward_xp", 0) > 0:
        grant_general_xp(session_id, player_name, quest["reward_xp"], reason=f"quest: {quest.get('title','?')}")

    print(f"   💰 Quest ödülü: +{quest.get('reward_gold',0)}gp +{quest.get('reward_xp',0)}xp")

# ─── ALTIN İŞLEMLERİ ─────────────────────────────────────────────────────────

def add_gold(session_id, player_name, amount):
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return
    stats["gold"] += amount
    _save_stats(session_id, player_name, stats)
    print(f"   💰 +{amount} altın → Toplam: {stats['gold']}")

def spend_gold(session_id, player_name, amount):
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return False, "Karakter bulunamadı."
    if stats["gold"] < amount:
        return False, f"Yeterli altın yok. Mevcut: {stats['gold']}gp"
    stats["gold"] -= amount
    _save_stats(session_id, player_name, stats)
    print(f"   💸 -{amount} altın → Kalan: {stats['gold']}")
    return True, f"✅ {amount}gp harcandı."

# ─── CAN SİSTEMİ ─────────────────────────────────────────────────────────────

def apply_damage(session_id, player_name, damage):
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return False, 0
    stats["hp"] = max(0, stats["hp"] - damage)
    _save_stats(session_id, player_name, stats)
    is_down = stats["hp"] <= 0
    print(f"   💔 {player_name} {damage} hasar aldı → HP: {stats['hp']}/{stats['max_hp']}")
    return is_down, stats["hp"]

def heal(session_id, player_name, amount):
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return
    stats["hp"] = min(stats["max_hp"], stats["hp"] + amount)
    _save_stats(session_id, player_name, stats)
    print(f"   💚 {player_name} {amount} HP iyileşti → HP: {stats['hp']}/{stats['max_hp']}")

# ─── DURUM ÖZET ──────────────────────────────────────────────────────────────

def format_player_status(session_id, player_name):
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return ""
    hp_bar = _bar(stats["hp"], stats["max_hp"])
    xp_next = _next_level_xp(stats["level"], stats["xp"])
    return (
        f"❤️  {player_name}  HP: {hp_bar} {stats['hp']}/{stats['max_hp']}"
        f"  |  💰 {stats['gold']}gp"
        f"  |  ⭐ Seviye {stats['level']}  XP: {stats['xp']} ({xp_next})"
    )

def format_stats_for_prompt(session_id, player_name):
    stats = get_player_stats(session_id, player_name)
    if not stats:
        return ""
    return (
        f"[PLAYER STATUS: {player_name}]\n"
        f"HP: {stats['hp']}/{stats['max_hp']}  Gold: {stats['gold']}gp  Level: {stats['level']}"
    )

def _bar(current, maximum, length=8):
    if maximum == 0:
        return "░" * length
    filled = int(length * current / maximum)
    return "█" * filled + "░" * (length - filled)

def _next_level_xp(current_level, current_xp):
    next_idx = current_level + 1
    if next_idx >= len(LEVEL_THRESHOLDS):
        return "MAX"
    needed = LEVEL_THRESHOLDS[next_idx] - current_xp
    return f"{needed} XP sonraki seviyeye"