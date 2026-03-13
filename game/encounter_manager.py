# game/encounter_manager.py — Encounter state yönetimi
"""
[ENCOUNTER] blok parse + çoklu düşman encounter state yönetimi.
LLM cevabından encounter bloğu çıkarır, monster tablosundan stat çeker,
tur-bazlı combat mantığını yönetir.
"""

import re
import json
import random
from game.monster_data import get_monster, MAX_ENEMIES, parse_damage, parse_attack_bonus, get_ability_effect
from game.dice import d20


# ─── ENCOUNTER STATE ──────────────────────────────────────────────────────────

class EncounterState:
    """Aktif bir encounter'ın tüm durumunu tutar."""

    def __init__(self):
        self.enemies = []           # [{id, type, display_name, hp, max_hp, ac, attack_bonus, damage_str, xp, abilities, behavior, status_effects, ability_cooldowns}, ...]
        self.turn_number = 0
        self.is_active = True
        self.combat_log = []        # Her tur logları (frontend'e gönderilir, DB'ye kaydedilmez)
        self.triggered_events = set()  # Tetiklenmiş olay ID'leri
        self.context = ""           # Encounter bağlamı

    def to_dict(self):
        """Frontend'e göndermek için dict'e çevir."""
        return {
            "enemies": [
                {
                    "id": e["id"],
                    "type": e["type"],
                    "display_name": e["display_name"],
                    "hp": e["hp"],
                    "max_hp": e["max_hp"],
                    "ac": e["ac"],
                    "abilities": e["abilities"],
                    "status_effects": e.get("status_effects", []),
                    "fled": e.get("fled", False),
                }
                for e in self.enemies
            ],
            "turn_number": self.turn_number,
            "is_active": self.is_active,
            "context": self.context,
        }


# ─── ENCOUNTER PARSE ──────────────────────────────────────────────────────────

def parse_encounter_block(gm_response):
    """
    GM cevabından [ENCOUNTER]...[/ENCOUNTER] bloğunu parse eder.

    Döner:
        {"enemies": [{"name": "Tavern Bouncer", "type": "guard"}, ...], "context": "..."}
        veya None (blok yoksa)
    """
    pattern = r'\[ENCOUNTER\](.*?)\[/ENCOUNTER\]'
    match = re.search(pattern, gm_response, re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group(1).strip())

        # enemies listesi kontrolü
        enemies = data.get("enemies", [])
        if not enemies:
            return None

        # Eski format desteği: string list → name=type olan dict list
        normalized = []
        for e in enemies:
            if isinstance(e, str):
                normalized.append({"name": e, "type": e})
            elif isinstance(e, dict):
                normalized.append({
                    "name": e.get("name", e.get("type", "Unknown")),
                    "type": e.get("type", "bandit"),
                })
            else:
                continue

        # Max enemy sınırı
        if len(normalized) > MAX_ENEMIES:
            normalized = normalized[:MAX_ENEMIES]

        data["enemies"] = normalized
        return data

    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"   ⚠️  [ENCOUNTER] parse hatası: {exc}")
        return None


def strip_encounter_block(gm_response):
    """GM cevabından [ENCOUNTER] bloğunu çıkarır, temiz narrative döner."""
    return re.sub(r'\[ENCOUNTER\].*?\[/ENCOUNTER\]', '', gm_response, flags=re.DOTALL).strip()


# ─── ENCOUNTER OLUŞTUR ────────────────────────────────────────────────────────

def create_encounter(encounter_data):
    """
    Parse edilmiş encounter verisinden EncounterState oluşturur.
    Monster tablosundan stat çeker.

    Args:
        encounter_data: {"enemies": [{"name": "...", "type": "..."}, ...], "context": "..."}

    Returns:
        EncounterState
    """
    state = EncounterState()
    state.context = encounter_data.get("context", "")

    for idx, enemy_info in enumerate(encounter_data["enemies"]):
        monster_type = enemy_info.get("type", "bandit")
        display_name = enemy_info.get("name", monster_type)

        stats = get_monster(monster_type)

        enemy = {
            "id": idx,
            "type": monster_type,
            "display_name": display_name,
            "hp": stats["hp"],
            "max_hp": stats["max_hp"],
            "ac": stats["ac"],
            "attack_bonus": stats["attack_bonus"],
            "damage_str": stats["damage_str"],
            "xp": stats["xp"],
            "abilities": stats["abilities"],
            "behavior": stats["behavior"],
            "status_effects": [],       # aktif efektler: [{type, turns_left, ...}]
            "ability_cooldowns": {},     # ability_name → kalan cooldown turu
            "fled": False,
        }
        state.enemies.append(enemy)

    return state


# ─── DÜŞMAN TURU ──────────────────────────────────────────────────────────────

def enemy_turn(encounter_state, player_targets):
    """
    Tüm hayattaki düşmanların saldırılarını işler.

    Args:
        encounter_state: EncounterState
        player_targets: [{name, ac, hp, max_hp}, ...] — saldırılabilecek oyuncular

    Returns:
        list of dicts: [
            {
                "enemy_name": str,
                "target_player": str,
                "attack_roll": int,
                "hit": bool,
                "damage": int,
                "ability_used": str or None,
                "ability_effect": dict or None,
                "message": str,
            },
            ...
        ]
    """
    results = []
    alive_enemies = get_alive_enemies(encounter_state)
    alive_players = [p for p in player_targets if p["hp"] > 0]

    if not alive_players:
        return results

    for enemy in alive_enemies:
        # Cooldown'ları tick et
        _tick_enemy_cooldowns(enemy)

        # Stun kontrolü
        if _is_stunned(enemy):
            results.append({
                "enemy_name": enemy["display_name"],
                "target_player": None,
                "attack_roll": 0,
                "hit": False,
                "damage": 0,
                "ability_used": None,
                "ability_effect": None,
                "message": f"{enemy['display_name']} is stunned and cannot act!",
            })
            _tick_status_effects(enemy)
            continue

        # Yetenek kontrolü — önce passive olmayan yetenekleri dene
        ability_result = _try_use_ability(enemy, encounter_state, alive_players)
        if ability_result:
            results.append(ability_result)
            _tick_status_effects(enemy)
            continue

        # Normal saldırı
        target = random.choice(alive_players)
        attack_roll = d20()

        # Rage kontrolü
        rage_bonus = _get_rage_bonus(enemy)
        attack_total = attack_roll + enemy["attack_bonus"]

        hit = attack_roll == 20 or (attack_roll != 1 and attack_total >= target["ac"])
        damage = 0

        if hit:
            damage = parse_damage(enemy["damage_str"])
            damage += rage_bonus
            if attack_roll == 20:
                damage *= 2  # Critical

        # Knockdown kontrolü (on_hit ability)
        ability_triggered = None
        if hit and "knockdown" in enemy["abilities"]:
            kd_effect = get_ability_effect("knockdown")
            if kd_effect:
                ability_triggered = "knockdown"

        hit_label = "CRITICAL HIT" if attack_roll == 20 else ("HIT" if hit else "MISS")
        msg = (
            f"{enemy['display_name']} attacks {target['name']}: "
            f"roll {attack_roll}+{enemy['attack_bonus']}={attack_total} vs AC {target['ac']} — {hit_label}"
        )
        if damage > 0:
            msg += f", {damage} damage"

        results.append({
            "enemy_name": enemy["display_name"],
            "target_player": target["name"],
            "attack_roll": attack_roll,
            "hit": hit,
            "damage": damage,
            "ability_used": ability_triggered,
            "ability_effect": get_ability_effect(ability_triggered) if ability_triggered else None,
            "message": msg,
        })

        _tick_status_effects(enemy)

    return results


# ─── YETENEK SİSTEMİ ──────────────────────────────────────────────────────────

def _try_use_ability(enemy, encounter_state, alive_players):
    """Düşman yeteneği kullanmayı dener. Döner: result dict veya None."""
    for ability_name in enemy["abilities"]:
        effect = get_ability_effect(ability_name)
        if not effect:
            continue
        if effect.get("passive"):
            continue  # Passive yetenekler otomatik, aksiyon harcanmaz

        # Cooldown kontrolü
        cd_remaining = enemy["ability_cooldowns"].get(ability_name, 0)
        if cd_remaining > 0:
            continue

        # Tetikleme koşulu
        trigger = effect.get("trigger")
        if trigger == "hp_below_50":
            if enemy["hp"] > enemy["max_hp"] * 0.5:
                continue  # HP yeterince düşmemiş
        elif trigger == "on_hit":
            continue  # on_hit pasif tetiklenir, burada kullanılmaz

        # Yeteneği kullan
        if effect["effect"] == "heal_lowest_ally":
            return _use_heal_ally(enemy, encounter_state, effect, ability_name)
        elif effect["effect"] == "dot":
            target = random.choice(alive_players)
            return _use_poison_dart(enemy, target, effect, ability_name)
        elif effect["effect"] == "aoe_damage":
            return _use_aoe_damage(enemy, alive_players, effect, ability_name)
        elif effect["effect"] == "life_drain":
            target = random.choice(alive_players)
            return _use_life_drain(enemy, target, effect, ability_name)
        elif effect["effect"] == "heal_self":
            return _use_heal_self(enemy, effect, ability_name)

    return None


def _use_heal_ally(enemy, encounter_state, effect, ability_name):
    """heal_ally yeteneği: en düşük HP'li müttefiki iyileştirir."""
    alive = [e for e in encounter_state.enemies if e["hp"] > 0 and e["id"] != enemy["id"]]
    if not alive:
        return None

    target = min(alive, key=lambda e: e["hp"])

    # Heal miktarı hesapla
    heal_amount = parse_damage(effect["heal"])
    target["hp"] = min(target["max_hp"], target["hp"] + heal_amount)

    # Cooldown uygula
    enemy["ability_cooldowns"][ability_name] = effect.get("cooldown", 3)

    msg = f"{enemy['display_name']} heals {target['display_name']} for {heal_amount} HP!"
    return {
        "enemy_name": enemy["display_name"],
        "target_player": None,
        "attack_roll": 0,
        "hit": False,
        "damage": 0,
        "ability_used": ability_name,
        "ability_effect": {"healed": target["display_name"], "amount": heal_amount},
        "message": msg,
    }


def _use_poison_dart(enemy, target, effect, ability_name):
    """poison_dart: hedefe DoT uygular."""
    dot_dmg = effect.get("dot_damage", 3)
    dot_turns = effect.get("dot_turns", 2)

    # Cooldown uygula
    enemy["ability_cooldowns"][ability_name] = effect.get("cooldown", 0)

    msg = f"{enemy['display_name']} fires a poison dart at {target['name']}! ({dot_dmg} damage for {dot_turns} turns)"
    return {
        "enemy_name": enemy["display_name"],
        "target_player": target["name"],
        "attack_roll": 0,
        "hit": True,
        "damage": 0,  # İlk tur hasar yok, DoT sonra uygulanır
        "ability_used": ability_name,
        "ability_effect": {"dot_damage": dot_dmg, "dot_turns": dot_turns, "target": target["name"]},
        "message": msg,
    }


def _use_aoe_damage(enemy, alive_players, effect, ability_name):
    """aoe_damage: tüm oyunculara hasar vurur."""
    damage = parse_damage(effect.get("damage", "2d6"))
    enemy["ability_cooldowns"][ability_name] = effect.get("cooldown", 3)
    
    msg = f"{enemy['display_name']} unleashes an area attack! ({damage} damage to everyone)"
    
    return {
        "enemy_name": enemy["display_name"],
        "target_player": None, # Indicates AOE
        "attack_roll": 0,
        "hit": True,
        "damage": damage,
        "ability_used": ability_name,
        "ability_effect": {"aoe_damage": damage},
        "message": msg,
    }


def _use_life_drain(enemy, target, effect, ability_name):
    """life_drain: hedefe hasar verir, hasar kadar kendini iyileştirir."""
    damage = parse_damage(effect.get("damage", "2d6"))
    enemy["ability_cooldowns"][ability_name] = effect.get("cooldown", 3)
    
    heal_amount = damage
    enemy["hp"] = min(enemy["max_hp"], enemy["hp"] + heal_amount)
    
    msg = f"{enemy['display_name']} drains life from {target['name']}! ({damage} damage treated as self-heal)"
    
    return {
        "enemy_name": enemy["display_name"],
        "target_player": target["name"],
        "attack_roll": 0,
        "hit": True,
        "damage": damage,
        "ability_used": ability_name,
        "ability_effect": {"life_drain_heal": heal_amount},
        "message": msg,
    }


def _use_heal_self(enemy, effect, ability_name):
    """heal_self: kendini iyileştirir."""
    heal_amount = parse_damage(effect.get("heal", "1d6"))
    enemy["ability_cooldowns"][ability_name] = effect.get("cooldown", 2)
    
    enemy["hp"] = min(enemy["max_hp"], enemy["hp"] + heal_amount)
    msg = f"{enemy['display_name']} regenerates {heal_amount} HP!"
    
    return {
        "enemy_name": enemy["display_name"],
        "target_player": None,
        "attack_roll": 0,
        "hit": False,
        "damage": 0,
        "ability_used": ability_name,
        "ability_effect": {"healed": enemy["display_name"], "amount": heal_amount},
        "message": msg,
    }


# ─── STATUS EFFECT YÖNETİMİ ──────────────────────────────────────────────────

def _is_stunned(enemy):
    """Düşman stunned mı?"""
    for se in enemy.get("status_effects", []):
        if se["type"] == "stun" and se.get("turns_left", 0) > 0:
            return True
    return False


def _tick_status_effects(enemy):
    """Tur sonu: status effect sürelerini azalt, süresi bitenleri kaldır."""
    remaining = []
    for se in enemy.get("status_effects", []):
        se["turns_left"] = se.get("turns_left", 0) - 1
        if se["turns_left"] > 0:
            remaining.append(se)
    enemy["status_effects"] = remaining


def _tick_enemy_cooldowns(enemy):
    """Tur başı: yetenek cooldown'larını azalt."""
    to_remove = []
    for ability_name, cd in enemy.get("ability_cooldowns", {}).items():
        if cd > 0:
            enemy["ability_cooldowns"][ability_name] = cd - 1
        if enemy["ability_cooldowns"][ability_name] <= 0:
            to_remove.append(ability_name)
    for key in to_remove:
        del enemy["ability_cooldowns"][key]


def _get_rage_bonus(enemy):
    """Rage yeteneği aktifse bonus hasar döner."""
    if "rage" not in enemy.get("abilities", []):
        return 0
    if enemy["hp"] <= enemy["max_hp"] * 0.5:
        effect = get_ability_effect("rage")
        return effect.get("bonus", 3) if effect else 0
    return 0


# ─── YARDIMCI FONKSİYONLAR ───────────────────────────────────────────────────

def get_alive_enemies(encounter_state):
    """Hayatta kalan düşmanları döner."""
    return [e for e in encounter_state.enemies if e["hp"] > 0 and not e.get("fled", False)]


def get_total_xp(encounter_state):
    """Encounter'daki toplam XP ödülünü hesaplar."""
    return sum(e["xp"] for e in encounter_state.enemies if not e.get("fled", False))


def is_encounter_over(encounter_state):
    """Tüm düşmanlar öldü mü / kaçtı mı?"""
    return len(get_alive_enemies(encounter_state)) == 0


# ─── PROMPT İÇİN ENCOUNTER DURUMU ────────────────────────────────────────────

def get_encounter_status_for_prompt(encounter_state):
    """LLM'e gönderilecek aktif encounter durumu."""
    if not encounter_state or not encounter_state.is_active:
        return ""

    lines = ["[ACTIVE ENCOUNTER]"]
    for enemy in encounter_state.enemies:
        status = "ALIVE" if enemy["hp"] > 0 else ("FLED" if enemy.get("fled") else "DEAD")
        lines.append(
            f"- {enemy['display_name']} ({enemy['type']}): "
            f"HP {enemy['hp']}/{enemy['max_hp']} — {status}"
        )
    lines.append(f"Turn: {encounter_state.turn_number}")
    return "\n".join(lines) + "\n"


def format_encounter_display(encounter_state):
    """Oyuncuya gösterilecek formatlanmış encounter durumu (konsol)."""
    if not encounter_state or not encounter_state.is_active:
        return ""

    lines = ["\n⚔️  SAVAŞ AKTİF"]
    for enemy in encounter_state.enemies:
        if enemy.get("fled"):
            lines.append(f"   💨 {enemy['display_name']} — KAÇTI")
            continue

        if enemy["hp"] <= 0:
            lines.append(f"   💀 {enemy['display_name']} — YENİLDİ")
            continue

        bar_len = 10
        hp_pct = enemy["hp"] / enemy["max_hp"]
        filled = int(bar_len * hp_pct)
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(
            f"   [{enemy['id']}] {enemy['display_name']}  "
            f"HP: [{bar}] {enemy['hp']}/{enemy['max_hp']}  AC: {enemy['ac']}"
        )

    lines.append(f"   Tur: {encounter_state.turn_number}")
    return "\n".join(lines)


# ─── COMBAT SUMMARY ──────────────────────────────────────────────────────────

def generate_combat_summary(encounter_state, dead_players=None):
    """
    Savaş bitince tek bir özet mesaj üretir.
    Bu mesaj DB'ye kaydedilir ve LLM'in hafızasına girer.

    Ölü oyuncuları açıkça belirtir.
    """
    dead_players = dead_players or []

    # Düşman sonuçları
    defeated = [e for e in encounter_state.enemies if e["hp"] <= 0 and not e.get("fled")]
    fled = [e for e in encounter_state.enemies if e.get("fled")]

    parts = ["[COMBAT SUMMARY]"]

    if defeated:
        names = ", ".join(e["display_name"] for e in defeated)
        parts.append(f"Enemies defeated: {names}.")

    if fled:
        names = ", ".join(e["display_name"] for e in fled)
        parts.append(f"Enemies fled: {names}.")

    parts.append(f"Combat lasted {encounter_state.turn_number} turns.")

    total_xp = get_total_xp(encounter_state)
    parts.append(f"Total XP earned: {total_xp}.")

    # Ölü oyuncular — KRİTİK
    if dead_players:
        for dp in dead_players:
            parts.append(
                f"⚠️ {dp} has fallen and is DEAD — "
                f"this character cannot move, speak, or take any actions. "
                f"Do NOT include {dp} in any future narrative."
            )

    return " ".join(parts)
