"""
ui/app.py — Flask web arayüzü (Multiplayer destekli)
Çalıştırma: python -m ui.app   (proje kökünden)
"""

import os
import sys
import json
import time
import re

# Proje kökünü path'e ekle
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, request, jsonify, send_from_directory, Response
import requests as http_requests

from db.database import initialize_db
from db.user_manager import register_user, login_user
from db.session_manager import (
    create_session, get_active_session,
    end_session, save_message, get_recent_messages
)
from game.character_manager import load_character_from_yaml
from game.character_creator import RACES, CLASSES, ABILITY_DISPLAY, POINT_COST, TOTAL_POINTS
from game.game_state import GameState
from game.dice import d20, get_modifier
from game.npc_manager import get_all_npcs, save_npc
from game.npc_extractor import extract_npcs_from_response
from game.scenario_manager import ScenarioManager
from game.combat import check_combat_start, player_attack, enemy_attack, format_encounter_status
from game.inventory_manager import use_item, add_item, get_pickup_dc, get_inventory
from game.skill_data import get_skills_for_class, get_initial_skill_levels, get_all_skill_info, get_skill_by_id, calculate_skill_damage, calculate_skill_heal
from game.xp_manager import init_player_stats, grant_general_xp, grant_ability_xp, grant_combat_xp, apply_damage, add_gold, format_player_status, grant_quest_rewards
from game.quest_manager import init_quests, check_node_quests
from game.event_parser import parse_gm_events
from game.room_manager import create_room, join_room, get_room, get_room_for_user, get_room_code_for_user, leave_room
from prompts.system_prompt import build_system_prompt
from rag.retriever import get_relevant_rules
from rag.ingest import ingest
import config

from ui import translator

# ─── FLASK APP ────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="static")

# ─── GLOBAL STATE ─────────────────────────────────────────────────────────────

_db_initialized = False
_translator_initialized = False


def _init_db():
    """Veritabanı ve RAG'ı bir kez başlat (model-bağımsız)."""
    global _db_initialized
    if not _db_initialized:
        initialize_db()
        ingest()
        _db_initialized = True


def _init_translator():
    """Çeviri modelini arka planda yükle (config kaydedildikten sonra çağrılmalı)."""
    global _translator_initialized
    if not _translator_initialized:
        translator.ensure_model_loaded()
        _translator_initialized = True


# ─── OLLAMA ÇAĞRISI ──────────────────────────────────────────────────────────

def _ask_gm_streaming(messages, system_prompt):
    """GM'den yanıt al, streaming olarak yield et."""
    response = http_requests.post(
        f"{config.base_url}/api/chat",
        json={
            "model": config.model,
            "messages": messages,
            "system": system_prompt,
            "stream": True,
            "think": False,
            "options": {
                "num_ctx": config.context_length,
                "temperature": config.temp,
                "num_predict": config.num_predict,
            },
        },
        stream=True,
    )

    full_response = ""
    for line in response.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        content = chunk.get("message", {}).get("content", "")
        if content:
            full_response += content
            yield content, False

        if chunk.get("done"):
            yield "", True

    return full_response


def _ask_gm_full(messages, system_prompt):
    """GM'den yanıt al, hepsini birden döndür."""
    full = ""
    for content, done in _ask_gm_streaming(messages, system_prompt):
        full += content
    return full


# ─── ZAR KONTROLÜ ────────────────────────────────────────────────────────────

def _needs_roll_check(action, node_available_actions=None):
    """Zar gerekli mi kontrolü."""
    examples = get_relevant_rules(f"dice roll ability check required: {action}")
    if not examples:
        examples = "No examples found."

    node_context = ""
    if node_available_actions:
        node_context = f"\nSCENE SPECIFIC ACTIONS (use these DCs if action matches):\n{node_available_actions}"

    prompt = f"""You are a D&D rules judge. Decide if this player action requires a dice roll.

PLAYER ACTION: "{action}"

DICE ROLL REFERENCE:
{examples}
{node_context}

Rules:
- Uncertain outcomes (persuading, sneaking, investigating, attacking, jumping, lying) → need a roll
- Certain outcomes (talking normally, walking, entering a room, looking around casually) → no roll

Respond with ONLY valid JSON, no explanation, no markdown:
If roll needed: {{"needed": true, "ability": "charisma", "dc": 12}}
If no roll:     {{"needed": false}}"""

    try:
        response = http_requests.post(
            f"{config.base_url}/api/chat",
            json={
                "model": config.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 50},
            },
        )
        result = response.json()
        answer = result["message"]["content"].strip()
        answer = re.sub(r"```json|```", "", answer).strip()
        match = re.search(r"\{.*?\}", answer, re.DOTALL)
        if match:
            answer = match.group(0)
        else:
            return {"needed": False}

        data = json.loads(answer)
        if data.get("needed"):
            return {
                "needed": True,
                "ability": data.get("ability", "strength").lower(),
                "dc": int(data.get("dc", 12)),
            }
        return {"needed": False}
    except Exception:
        return {"needed": False}


def _execute_roll(roll_info, player_name, game_state, session_id, user):
    """Zar at, sonucu döndür."""
    ability = roll_info["ability"]
    dc = roll_info["dc"]

    ability_map = {
        "dex": "dexterity", "str": "strength", "con": "constitution",
        "wis": "wisdom", "int": "intelligence", "cha": "charisma",
    }
    ability = ability_map.get(ability, ability)

    # Find the character for this player
    char = None
    for c in game_state.characters:
        if c["name"].lower() == player_name.lower():
            char = c
            break
    if not char:
        char = game_state.characters[0] if game_state.characters else {"abilities": {}}

    abilities = char.get("abilities", {})
    score = abilities.get(ability, 10)
    modifier = get_modifier(score)

    roll_result = d20()
    total = roll_result + modifier

    if roll_result == 20:
        outcome_label = "CRITICAL SUCCESS"
        success = True
    elif roll_result == 1:
        outcome_label = "CRITICAL FAILURE"
        success = False
    elif total >= dc:
        outcome_label = "SUCCESS"
        success = True
    else:
        outcome_label = "FAILURE"
        success = False

    if success:
        grant_ability_xp(session_id, player_name, ability, amount=5)

    grant_general_xp(session_id, player_name, 2, reason="roll yapıldı")

    roll_message = (
        f"Player: {player_name}\n"
        f"Action required: {ability} check vs DC {dc}\n"
        f"Roll: {roll_result} + {modifier} (modifier) = {total}\n"
        f"Result: {outcome_label}"
    )

    db_message = (
        f"{player_name} rolled {ability}: "
        f"{roll_result} + {modifier} = {total} vs DC {dc} ({outcome_label})"
    )
    save_message(session_id, user.get("id") if user else None, "user", db_message)

    return {
        "roll_message": roll_message,
        "ability": ability,
        "dc": dc,
        "roll": roll_result,
        "modifier": modifier,
        "total": total,
        "outcome": outcome_label,
        "success": success
    }


# ─── EŞYA ALMA & KULLANMA ────────────────────────────────────────────────────

ACQUIRE_PATTERNS = [
    r"steal\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"grab\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"take\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"pick\s+up\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"snatch\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"swipe\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"lift\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"pocket\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"(.+?)\s*(?:çal|çalıyorum|çaldım|al|alıyorum|aldım|kap|kaptım)",
]


def _check_item_acquisition(action):
    action_lower = action.lower().strip()
    action_clean = re.sub(r"^i\s+", "", action_lower)
    for pattern in ACQUIRE_PATTERNS:
        match = re.search(pattern, action_clean, re.IGNORECASE)
        if match:
            item = match.group(1).strip().rstrip('.,!?')
            if len(item.split()) <= 4:
                return item
    return None


def _handle_item_use(action, player_name, session_id):
    match_en = re.search(r'\buse\b\s+(?:my\s+|the\s+)?(.+)', action, re.IGNORECASE)
    match_tr = re.search(r'(.+?)\s*(?:kullan|kullanıyorum|kullandım)', action, re.IGNORECASE)

    item_name = None
    if match_en:
        item_name = match_en.group(1).strip().rstrip('.')
    elif match_tr:
        item_name = match_tr.group(1).strip().lstrip('I').strip()

    if not item_name:
        return False, None

    success, msg = use_item(session_id, item_name, player_name)
    if success:
        grant_general_xp(session_id, player_name, 1, reason="eşya kullanıldı")
        return True, f"{player_name} uses {item_name}."
    else:
        return False, msg


# ═════════════════════════════════════════════════════════════════════════════
# ROUND PROCESSING (multiplayer)
# ═════════════════════════════════════════════════════════════════════════════

def _process_round(room):
    """Process a full multiplayer round: all players' actions → single GM response."""
    room.round_processing = True
    try:
        return _process_round_inner(room)
    finally:
        room.round_processing = False


# ─── HEAL DETECTION KALDIRILDI — Artık skill butonu kullanılıyor ──────────────


def _process_round_inner(room):
    from game.xp_manager import get_player_stats, heal
    import random

    gs = room.game_state
    sm = room.scenario_manager
    session_id = room.session_id
    player_names_list = room.get_player_names()

    actions = room.consume_round_actions()

    # Per-player processing
    all_roll_results = {}  # player_name → roll result dict
    all_combat_logs = {}   # player_name → list of log strings
    combined_roll_msgs = []

    # Track if combat ended this round (prevents enemy respawn)
    combat_ended_this_round = False

    for username, action in actions.items():
        char = room.get_character_for_username(username)
        if not char:
            continue
        player_name = char["name"]

        if action == "__PASS__":
            all_combat_logs[player_name] = [f"{player_name} passes."]
            continue

        all_combat_logs[player_name] = []

        # ── Check if player is unconscious (HP ≤ 0) ──
        player_stats = get_player_stats(session_id, player_name)
        if player_stats and player_stats["hp"] <= 0:
            all_combat_logs[player_name].append(f"💀 {player_name} is unconscious and cannot act!")
            user_message = f"{player_name} (unconscious): {action}"
            save_message(session_id, None, "user", user_message)
            continue

        # Item use check
        item_used, item_gm_msg = _handle_item_use(action, player_name, session_id)
        if item_used and item_gm_msg:
            save_message(session_id, None, "user", item_gm_msg)

        user_message = f"{player_name}: {action}"
        save_message(session_id, None, "user", user_message)
        grant_general_xp(session_id, player_name, 1, reason="aksiyon")

        # Combat check
        roll_result_msg = None

        if gs.is_combat and gs.active_encounter and not combat_ended_this_round:
            attack_msg, damage, enemy_defeated = player_attack(gs, player_name, session_id, {})
            roll_result_msg = attack_msg
            all_combat_logs[player_name].append(attack_msg)

            if enemy_defeated:
                xp = gs.active_encounter.get("xp_reward", 50)
                # Grant combat XP to ALL active players this round
                for uname, act in actions.items():
                    if act != "__PASS__":
                        ch = room.get_character_for_username(uname)
                        if ch:
                            grant_combat_xp(session_id, ch["name"], xp)
                gs.end_encounter()
                combat_ended_this_round = True
                all_combat_logs[player_name].append(f"Enemy defeated! +{xp} XP")
            else:
                enemy_dmg, enemy_msg = enemy_attack(gs, player_name, session_id)
                if enemy_dmg > 0:
                    is_down, _ = apply_damage(session_id, player_name, enemy_dmg)
                    all_combat_logs[player_name].append(enemy_msg)
                    if is_down:
                        all_combat_logs[player_name].append(f"💀 {player_name} has fallen unconscious!")
        elif combat_ended_this_round:
            # Combat just ended this round — skip combat for remaining players
            all_combat_logs[player_name].append(f"⚔️ Combat has ended. {player_name}'s action is narrative only.")
        else:
            combat_result = check_combat_start(action)
            if combat_result.get("combat"):
                gs.start_encounter(combat_result)
                attack_msg, _, enemy_defeated = player_attack(gs, player_name, session_id, {})
                roll_result_msg = f"COMBAT STARTED against {combat_result['enemy_name']}!\n{attack_msg}"
                all_combat_logs[player_name].append(f"⚔️ Combat: {combat_result['enemy_name']}!")

                if enemy_defeated:
                    xp = gs.active_encounter.get("xp_reward", 50)
                    for uname, act in actions.items():
                        if act != "__PASS__":
                            ch = room.get_character_for_username(uname)
                            if ch:
                                grant_combat_xp(session_id, ch["name"], xp)
                    gs.end_encounter()
                    combat_ended_this_round = True
                else:
                    enemy_dmg, enemy_msg = enemy_attack(gs, player_name, session_id)
                    if enemy_dmg > 0:
                        is_down, _ = apply_damage(session_id, player_name, enemy_dmg)
                        if is_down:
                            all_combat_logs[player_name].append(f"💀 {player_name} unconscious!")
            else:
                # Roll check
                node_actions = None
                if sm and sm.current_node:
                    node_actions = sm.current_node.get("available_actions")

                roll_info = _needs_roll_check(action, node_actions)
                if roll_info.get("needed"):
                    roll_result = _execute_roll(roll_info, player_name, gs, session_id, {})
                    roll_result_msg = roll_result["roll_message"]
                    all_roll_results[player_name] = roll_result

                    if roll_result.get("success"):
                        acquired_item = _check_item_acquisition(action)
                        if acquired_item:
                            add_item(session_id, acquired_item, 1, 0, "common", player_name)
                            save_message(session_id, None, "user", f"{player_name} successfully acquires: {acquired_item}")
                            all_combat_logs[player_name].append(f"🎒 {acquired_item} acquired!")
                else:
                    grant_general_xp(session_id, player_name, 1, reason="aksiyon (roll yok)")

        if roll_result_msg:
            combined_roll_msgs.append(roll_result_msg)

    # Trigger check
    transition_info = None
    if sm:
        recent_for_trigger = get_recent_messages(session_id)
        next_node = sm.check_trigger(recent_for_trigger)
        if next_node:
            sm.load_node(next_node)
            if sm.current_node:
                gs.current_node = sm.current_node.get("title", "")

            # Grant quest rewards to first non-passing player
            quest_events = check_node_quests(session_id, next_node)
            for qe in quest_events:
                if qe["event"] == "completed":
                    for uname, act in actions.items():
                        if act != "__PASS__":
                            ch = room.get_character_for_username(uname)
                            if ch:
                                grant_quest_rewards(session_id, ch["name"], qe["quest"])
                                break

            transition_msg = f"[SCENE TRANSITION: players have arrived at {sm.current_node.get('title', next_node)}]"
            save_message(session_id, None, "user", transition_msg)
            transition_info = {
                "new_node": next_node,
                "new_node_title": sm.current_node.get("title", next_node) if sm.current_node else next_node,
            }

    # Build round actions dict for the system prompt (player_name → action)
    round_actions_for_prompt = {}
    for username, action in actions.items():
        char = room.get_character_for_username(username)
        pname = char["name"] if char else username
        round_actions_for_prompt[pname] = action

    # Build combined roll info string
    combined_roll_str = "\n---\n".join(combined_roll_msgs) if combined_roll_msgs else None

    # GM CALL
    recent_messages = get_recent_messages(session_id)
    system_prompt = build_system_prompt(
        gs.characters,
        " | ".join([f"{k}: {v}" for k, v in round_actions_for_prompt.items() if v != "__PASS__"]),
        gs, sm,
        roll_info=combined_roll_str,
        session_id=session_id,
        round_actions=round_actions_for_prompt,
    )

    gm_response = _ask_gm_full(recent_messages, system_prompt)

    # NPC Extraction
    existing_npc_names = [n["name"] for n in get_all_npcs(session_id)]
    new_npcs = extract_npcs_from_response(gm_response, recent_messages, existing_npc_names, player_names_list)
    for npc in new_npcs:
        public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
        save_npc(npc["name"], public_data, npc["secret"], session_id)

    # Event parsing
    events = parse_gm_events(gm_response)
    if events.get("gold_found", 0) > 0:
        # Distribute gold to first non-passing player
        for uname, act in actions.items():
            if act != "__PASS__":
                ch = room.get_character_for_username(uname)
                if ch:
                    add_gold(session_id, ch["name"], events["gold_found"])
                    break

    gs.set_scene(gm_response[:100])
    save_message(session_id, None, "assistant", gm_response)

    # Translation
    gm_response_tr = translator.translate_en_to_tr(gm_response)

    # NPC list
    npcs = get_all_npcs(session_id)
    npcs_clean = [{"name": n["name"], "public": translator.translate_npc_data(n["public"])} for n in npcs]

    # Build per-player inventory, status, XP, and skills
    from game.xp_manager import get_all_xp_data
    all_inventories = {}
    all_statuses = {}
    all_xp = {}
    all_skills = {}
    dead_players = []
    for uname, char in room.players.items():
        pname = char["name"]
        all_inventories[pname] = get_inventory(session_id, pname)
        all_statuses[pname] = format_player_status(session_id, pname)
        all_xp[pname] = get_all_xp_data(session_id, pname)
        all_skills[pname] = get_all_skill_info(char.get("class", ""), char.get("skill_levels", {}))
        # Check if player is dead
        pstats = get_player_stats(session_id, pname)
        if pstats and pstats["hp"] <= 0:
            dead_players.append(pname)

    all_dead = len(dead_players) == len(room.players) and len(room.players) > 0

    # Combat status
    combat_status = None
    if gs.is_combat and gs.active_encounter:
        combat_status = gs.active_encounter

    result = {
        "success": True,
        "gm_response": gm_response,
        "gm_response_tr": gm_response_tr,
        "npcs": npcs_clean,
        "inventories": all_inventories,
        "player_statuses": all_statuses,
        "xp_data": all_xp,
        "skills": all_skills,
        "rolls": all_roll_results,
        "combat_logs": all_combat_logs,
        "events": events,
        "combat_status": combat_status,
        "round_number": room.round_number,
        "player_actions": round_actions_for_prompt,
        "dead_players": dead_players,
        "all_dead": all_dead,
    }
    if transition_info:
        result["transition"] = transition_info

    room.last_round_result = result
    return result


# ═════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═════════════════════════════════════════════════════════════════════════════

# ─── STATIC PAGES ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/assets/<path:filename>")
def serve_asset(filename):
    assets_dir = os.path.join(app.static_folder, "assets")
    return send_from_directory(assets_dir, filename)


# ─── CONFIGURATION ────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify({
        "models": config.AVAILABLE_MODELS,
        "translators": config.AVAILABLE_TRANSLATOR_MODELS,
        "current_model": config.model,
        "current_translator": getattr(config, "translator_model", "none"),
        "target_language": getattr(config, "target_language", "Turkish")
    })


@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.json
    if "model" in data:
        config.model = data["model"]
    if "translator" in data:
        config.translator_model = data["translator"]
    if "target_language" in data:
        config.target_language = data["target_language"]

    config_path = os.path.join(PROJECT_ROOT, "config.py")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r"^model\s*=\s*['\"].*?['\"]", f"model = '{config.model}'", content, flags=re.MULTILINE)
        content = re.sub(r"^translator_model\s*=\s*['\"].*?['\"]", f"translator_model = '{config.translator_model}'", content, flags=re.MULTILINE)
        content = re.sub(r"^target_language\s*=\s*['\"].*?['\"]", f"target_language = '{config.target_language}'", content, flags=re.MULTILINE)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Config save error: {e}")

    return jsonify({"success": True})


@app.route("/api/config/init", methods=["POST"])
def api_config_init():
    """Host config kaydettikten sonra translator'ı başlat."""
    _init_translator()
    return jsonify({"success": True})


# ─── AUTH ─────────────────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def api_login():
    _init_db()
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    action = data.get("action", "login")

    if not username or not password:
        return jsonify({"error": "Kullanıcı adı ve şifre gerekli"}), 400

    if action == "register":
        result = register_user(username, password, "player")
        if not result:
            return jsonify({"error": "Kayıt başarısız, kullanıcı adı alınmış olabilir"}), 400

    user = login_user(username, password)
    if not user:
        return jsonify({"error": "Giriş başarısız"}), 401

    return jsonify({"success": True, "username": user["username"], "role": user["role"]})


# ─── CHARACTERS ───────────────────────────────────────────────────────────────

@app.route("/api/characters", methods=["GET"])
def api_list_characters():
    os.makedirs(config.character_dir, exist_ok=True)
    files = [f for f in os.listdir(config.character_dir) if f.endswith(".yaml")]
    return jsonify({"characters": files})


@app.route("/api/characters/load", methods=["POST"])
def api_load_character():
    data = request.json
    filename = data.get("filename", "")
    if not filename.endswith(".yaml"):
        filename += ".yaml"

    character = load_character_from_yaml(filename)
    if not character:
        return jsonify({"error": "Karakter yüklenemedi"}), 400

    return jsonify({"success": True, "character": character})


@app.route("/api/characters/options", methods=["GET"])
def api_character_options():
    races = {k: {"name": v["name"], "display": v["display"], "bonuses": v["bonuses"]} for k, v in RACES.items()}
    classes = {k: {"name": v["name"], "display": v["display"], "tip": v["tip"], "hp_dice": v["hp_dice"]} for k, v in CLASSES.items()}
    return jsonify({"races": races, "classes": classes, "ability_display": ABILITY_DISPLAY})


@app.route("/api/characters/create", methods=["POST"])
def api_create_character():
    import yaml as _yaml

    data = request.json
    name = data.get("name", "").strip()
    race_key = data.get("race", "1")
    class_key = data.get("class", "1")
    background = data.get("background", "Mysterious adventurer")
    abilities_input = data.get("abilities", {})

    if not name:
        return jsonify({"error": "İsim gerekli"}), 400

    selected_race = RACES.get(race_key)
    selected_class = CLASSES.get(class_key)
    if not selected_race or not selected_class:
        return jsonify({"error": "Geçersiz ırk veya sınıf"}), 400

    abilities = {
        "strength": int(abilities_input.get("strength", 10)),
        "dexterity": int(abilities_input.get("dexterity", 10)),
        "constitution": int(abilities_input.get("constitution", 10)),
        "intelligence": int(abilities_input.get("intelligence", 10)),
        "wisdom": int(abilities_input.get("wisdom", 10)),
        "charisma": int(abilities_input.get("charisma", 10)),
    }

    final_abilities = abilities.copy()
    for ab, bonus in selected_race["bonuses"].items():
        final_abilities[ab] = final_abilities.get(ab, 8) + bonus

    con_modifier = (final_abilities["constitution"] - 10) // 2
    max_hp = selected_class["hp_dice"] + con_modifier
    max_hp = max(max_hp, 1)

    skill_levels = get_initial_skill_levels(selected_class["display"])

    character = {
        "name": name,
        "race": selected_race["display"],
        "class": selected_class["display"],
        "level": 1,
        "abilities": final_abilities,
        "hp": max_hp,
        "max_hp": max_hp,
        "armor_class": 10 + (final_abilities["dexterity"] - 10) // 2,
        "skill_levels": skill_levels,
        "background": background,
    }

    os.makedirs(config.character_dir, exist_ok=True)
    filename = f"{name.lower().replace(' ', '_')}.yaml"
    filepath = os.path.join(config.character_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        _yaml.dump(character, f, allow_unicode=True, default_flow_style=False)

    # Include skill info in response
    skills_info = get_all_skill_info(selected_class["display"], skill_levels)

    return jsonify({"success": True, "character": character, "filename": filename, "skills": skills_info})


# ─── TRANSLATOR ───────────────────────────────────────────────────────────────

@app.route("/api/translate/status", methods=["GET"])
def api_translation_status():
    return jsonify(translator.get_status())


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.json
    text = data.get("text", "")
    direction = data.get("direction", "tr-en")

    if not text:
        return jsonify({"translated": ""})

    if direction == "tr-en":
        translated = translator.translate_tr_to_en(text)
    else:
        translated = translator.translate_en_to_tr(text)

    return jsonify({"translated": translated})


# ─── SCENARIOS ────────────────────────────────────────────────────────────────

@app.route("/api/scenarios", methods=["GET"])
def api_list_scenarios():
    import yaml as _yaml

    scenarios_root = "scenarios"
    if not os.path.exists(scenarios_root):
        return jsonify({"scenarios": []})

    found = []
    for entry in sorted(os.listdir(scenarios_root)):
        entry_path = os.path.join(scenarios_root, entry)
        meta_path = os.path.join(entry_path, "scenario.yaml")
        if os.path.isdir(entry_path) and os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = _yaml.safe_load(f)
                found.append({
                    "path": entry_path,
                    "title": meta.get("title", entry),
                    "description": meta.get("description", ""),
                })
            except Exception:
                found.append({"path": entry_path, "title": entry, "description": ""})

    return jsonify({"scenarios": found})


# ═════════════════════════════════════════════════════════════════════════════
# ROOM / LOBBY SYSTEM
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/room/create", methods=["POST"])
def api_room_create():
    """Host creates a room. Returns room code."""
    data = request.json
    username = data.get("username", "").strip()
    if not username:
        return jsonify({"error": "Username gerekli"}), 400

    room_code = create_room(username)
    room = get_room(room_code)

    # Create a DB session for this room
    session_name = data.get("session_name", f"Room {room_code}")
    session_id = create_session(session_name)
    room.session_id = session_id
    room.game_state.session_id = session_id

    return jsonify({"success": True, "room_code": room_code, "session_id": session_id})


@app.route("/api/room/join", methods=["POST"])
def api_room_join():
    """Player joins an existing room with a character."""
    data = request.json
    room_code = data.get("room_code", "").strip().upper()
    username = data.get("username", "").strip()
    character = data.get("character")

    if not room_code or not username:
        return jsonify({"error": "Room kodu ve kullanıcı adı gerekli"}), 400

    room = join_room(room_code, username)
    if room is None:
        return jsonify({"error": "Oda bulunamadı veya oyun zaten başlamış"}), 404

    if character:
        room.add_player(username, character)

    players_info = {}
    for uname, char in room.players.items():
        players_info[uname] = {"name": char["name"], "race": char.get("race", ""), "class": char.get("class", "")}

    return jsonify({
        "success": True,
        "room_code": room_code,
        "host": room.host_username,
        "players": players_info,
        "game_started": room.game_started,
    })


@app.route("/api/room/status", methods=["GET"])
def api_room_status():
    """Get room status: players, who submitted, game state."""
    room_code = request.args.get("room_code", "").strip().upper()
    room = get_room(room_code)
    if not room:
        return jsonify({"error": "Oda bulunamadı"}), 404

    players_info = {}
    for uname, char in room.players.items():
        players_info[uname] = {"name": char["name"], "race": char.get("race", ""), "class": char.get("class", "")}

    submission = room.get_submission_status()

    result = {
        "room_code": room_code,
        "host": room.host_username,
        "players": players_info,
        "game_started": room.game_started,
        "submission": submission,
        "round_processing": room.round_processing,
    }

    # Only include round_result when NOT processing to avoid stale data.
    # Use the result's own round_number for consistency.
    if room.last_round_result and not room.round_processing:
        result["round_result"] = room.last_round_result
        result["round_number"] = room.last_round_result.get("round_number", 0)
    else:
        result["round_number"] = room.round_number

    return jsonify(result)


@app.route("/api/room/start", methods=["POST"])
def api_room_start():
    """Host starts the game — initializes stats, gets GM intro."""
    data = request.json
    room_code = data.get("room_code", "").strip().upper()
    username = data.get("username", "").strip()
    scenario_path = data.get("scenario_path", "")

    room = get_room(room_code)
    if not room:
        return jsonify({"error": "Oda bulunamadı"}), 404
    if room.host_username != username:
        return jsonify({"error": "Sadece host oyunu başlatabilir"}), 403
    if not room.players:
        return jsonify({"error": "En az bir oyuncu gerekli"}), 400

    gs = room.game_state
    session_id = room.session_id
    player_names_list = room.get_player_names()

    # Load scenario if provided
    if scenario_path:
        try:
            sm = ScenarioManager(scenario_path)
            sm.start()
            room.scenario_manager = sm
            if sm.current_node:
                gs.current_node = sm.current_node.get("title", "")
        except Exception as e:
            return jsonify({"error": f"Senaryo yüklenemedi: {e}"}), 500
    else:
        room.scenario_manager = None

    sm = room.scenario_manager

    # Initialize stats & quests
    for char in gs.characters:
        init_player_stats(session_id, char["name"], char)

    if sm:
        init_quests(session_id, sm.meta)

    # Build intro
    if sm and sm.current_node:
        node = sm.current_node
        intro_message = (
            f"The adventure begins. "
            f"Location: {node.get('title', 'Unknown')}. "
            f"Set the opening scene. Maximum 3 sentences."
        )
    else:
        intro_message = (
            "The players have just begun their adventure. "
            "Set the scene in English. Maximum 3 sentences. "
            "Describe where they are and end with an open situation."
        )

    system_prompt = build_system_prompt(
        gs.characters, "begin adventure exploration",
        gs, sm, session_id=session_id
    )

    gm_intro = _ask_gm_full(
        [{"role": "user", "content": intro_message}],
        system_prompt
    )

    # NPC Extraction
    existing_npc_names = [n["name"] for n in get_all_npcs(session_id)]
    new_npcs = extract_npcs_from_response(
        gm_intro,
        [{"role": "assistant", "content": gm_intro}],
        existing_npc_names,
        player_names_list
    )
    for npc in new_npcs:
        public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
        save_npc(npc["name"], public_data, npc["secret"], session_id)

    gs.set_scene(gm_intro[:100])
    if sm and sm.current_node:
        gs.current_node = sm.current_node.get("title", "")

    save_message(session_id, None, "user", intro_message)
    save_message(session_id, None, "assistant", gm_intro)

    room.game_started = True

    # Translation
    gm_intro_tr = translator.translate_en_to_tr(gm_intro)

    # NPCs
    npcs = get_all_npcs(session_id)
    npcs_clean = [{"name": n["name"], "public": translator.translate_npc_data(n["public"])} for n in npcs]

    # Per-player inventories, statuses, and XP
    from game.xp_manager import get_all_xp_data
    all_inventories = {}
    all_statuses = {}
    all_xp = {}
    for uname, char in room.players.items():
        pname = char["name"]
        all_inventories[pname] = get_inventory(session_id, pname)
        all_statuses[pname] = format_player_status(session_id, pname)
        all_xp[pname] = get_all_xp_data(session_id, pname)

    # Store as last_round_result so non-host players get it via polling
    start_result = {
        "success": True,
        "gm_response": gm_intro,
        "gm_response_tr": gm_intro_tr,
        "npcs": npcs_clean,
        "scenario_title": sm.meta.get("title", "") if sm else "Serbest Macera",
        "node_title": sm.current_node.get("title", "") if sm and sm.current_node else "",
        "inventories": all_inventories,
        "player_statuses": all_statuses,
        "xp_data": all_xp,
        "round_number": room.round_number,
    }
    room.last_round_result = start_result

    return jsonify(start_result)


# ─── GAME ACTIONS ─────────────────────────────────────────────────────────────

@app.route("/api/game/action", methods=["POST"])
def api_game_action():
    """Player submits action. If all players submitted, process the round."""
    try:
        data = request.json
        room_code = data.get("room_code", "").strip().upper()
        username = data.get("username", "").strip()
        action = data.get("action", "").strip()

        room = get_room(room_code)
        if not room:
            return jsonify({"error": "Oda bulunamadı"}), 404
        if not room.game_started:
            return jsonify({"error": "Oyun henüz başlamadı"}), 400
        if username not in room.players:
            return jsonify({"error": "Bu odada değilsiniz"}), 403
        if not action:
            return jsonify({"error": "Eylem boş olamaz"}), 400

        # Dead player check
        char = room.get_character_for_username(username)
        if char:
            from game.xp_manager import get_player_stats
            pstats = get_player_stats(room.session_id, char["name"])
            if pstats and pstats["hp"] <= 0:
                return jsonify({"error": "Karakteriniz öldü! Aksiyon gönderemezsiniz.", "dead": True}), 400

        room.submit_action(username, action)

        if room.all_actions_submitted():
            room.round_processing = True
            result = _process_round(room)
            return jsonify(result)
        else:
            submission = room.get_submission_status()
            return jsonify({
                "success": True,
                "waiting": True,
                "submission": submission,
                "message": f"Bekleniyor: {', '.join(submission['waiting_for'])}"
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Sunucu iç hatası: {str(e)}"}), 500


@app.route("/api/game/pass", methods=["POST"])
def api_game_pass():
    """Player passes their turn."""
    data = request.json
    room_code = data.get("room_code", "").strip().upper()
    username = data.get("username", "").strip()

    room = get_room(room_code)
    if not room:
        return jsonify({"error": "Oda bulunamadı"}), 404
    if username not in room.players:
        return jsonify({"error": "Bu odada değilsiniz"}), 403

    # Dead player check
    char = room.get_character_for_username(username)
    if char:
        from game.xp_manager import get_player_stats
        pstats = get_player_stats(room.session_id, char["name"])
        if pstats and pstats["hp"] <= 0:
            return jsonify({"error": "Karakteriniz öldü! Tur geçemezsiniz.", "dead": True}), 400

    room.pass_turn(username)

    if room.all_actions_submitted():
        room.round_processing = True
        result = _process_round(room)
        return jsonify(result)
    else:
        submission = room.get_submission_status()
        return jsonify({
            "success": True,
            "waiting": True,
            "submission": submission,
            "message": f"Tur geçildi. Bekleniyor: {', '.join(submission['waiting_for'])}"
        })


@app.route("/api/game/poll", methods=["GET"])
def api_game_poll():
    """Players poll for round completion."""
    room_code = request.args.get("room_code", "").strip().upper()
    username = request.args.get("username", "").strip()

    room = get_room(room_code)
    if not room:
        return jsonify({"error": "Oda bulunamadı"}), 404

    submission = room.get_submission_status()

    result = {
        "submission": submission,
        "round_number": room.round_number,
        "game_started": room.game_started,
    }

    # If there's a completed round result available
    if room.last_round_result:
        result["round_result"] = room.last_round_result
        result["round_complete"] = True
    else:
        result["round_complete"] = False

    return jsonify(result)


# ─── SKILL SYSTEM ─────────────────────────────────────────────────────────────

@app.route("/api/game/skill", methods=["POST"])
def api_game_skill():
    """Player uses a combat skill during their turn."""
    try:
        data = request.json
        room_code = data.get("room_code", "").strip().upper()
        username = data.get("username", "").strip()
        skill_id = data.get("skill_id", "").strip()

        room = get_room(room_code)
        if not room:
            return jsonify({"error": "Oda bulunamadı"}), 404
        if not room.game_started:
            return jsonify({"error": "Oyun henüz başlamadı"}), 400

        char = room.get_character_for_username(username)
        if not char:
            return jsonify({"error": "Karakter bulunamadı"}), 404

        gs = room.game_state
        session_id = room.session_id
        player_name = char["name"]

        # Dead check
        from game.xp_manager import get_player_stats
        pstats = get_player_stats(session_id, player_name)
        if pstats and pstats["hp"] <= 0:
            return jsonify({"error": "Karakteriniz öldü!", "dead": True}), 400

        # Must be in combat
        if not gs.is_combat or not gs.active_encounter:
            return jsonify({"error": "Savaş aktif değil!"}), 400

        # Find skill
        class_name = char.get("class", "")
        skill = get_skill_by_id(class_name, skill_id)
        if not skill:
            return jsonify({"error": "Skill bulunamadı"}), 404
        if skill.get("base_heal") is not None and "base_damage" not in skill:
            return jsonify({"error": "Bu bir heal skill'i, saldırı için kullanılamaz"}), 400

        skill_levels = char.get("skill_levels", {})
        skill_level = skill_levels.get(skill_id, 1)
        abilities = char.get("abilities", {})
        ability_score = abilities.get(skill["ability"], 10)

        # Roll d20 + ability modifier vs DC
        from game.dice import d20, get_modifier
        modifier = get_modifier(ability_score)
        roll_result = d20()
        total = roll_result + modifier
        dc = skill["dc"]

        if roll_result == 20:
            success = True
            outcome = "CRITICAL SUCCESS"
        elif roll_result == 1:
            success = False
            outcome = "CRITICAL FAILURE"
        elif total >= dc:
            success = True
            outcome = "SUCCESS"
        else:
            success = False
            outcome = "FAILURE"

        damage = 0
        enemy_defeated = False
        encounter = gs.active_encounter

        if success:
            damage = calculate_skill_damage(skill, skill_level, ability_score)
            if roll_result == 20:
                damage *= 2  # Critical doubles damage
            encounter["hp"] = max(0, encounter["hp"] - damage)
            if encounter["hp"] <= 0:
                enemy_defeated = True
                xp = encounter.get("xp_reward", 50)
                grant_combat_xp(session_id, player_name, xp)
                gs.end_encounter()
            grant_ability_xp(session_id, player_name, skill["ability"], amount=5)

        grant_general_xp(session_id, player_name, 2, reason="skill kullanıldı")

        # Save to DB
        from db.session_manager import save_message
        db_msg = (f"{player_name} uses {skill['name_en']}: "
                  f"roll {roll_result}+{modifier}={total} vs DC {dc} — {outcome}")
        if damage > 0:
            db_msg += f", {damage} damage"
        save_message(session_id, None, "user", db_msg)

        # Also submit this as the player's round action
        action_text = f"[SKILL: {skill['name_en']}] {outcome}"
        if damage > 0:
            action_text += f" — {damage} damage"
        room.submit_action(username, action_text)

        # Enemy counter-attack if still alive and hit
        enemy_counter = None
        if not enemy_defeated and gs.is_combat and gs.active_encounter:
            enemy_dmg, enemy_msg = enemy_attack(gs, player_name, session_id)
            if enemy_dmg > 0:
                is_down, _ = apply_damage(session_id, player_name, enemy_dmg)
                enemy_counter = {
                    "damage": enemy_dmg,
                    "message": enemy_msg,
                    "player_down": is_down,
                }

        # Updated status
        player_status = format_player_status(session_id, player_name)
        combat_status = gs.active_encounter if gs.is_combat and gs.active_encounter else None

        # Check if round should be processed
        round_result = None
        if room.all_actions_submitted():
            room.round_processing = True
            round_result = _process_round(room)

        return jsonify({
            "success": True,
            "skill_name": skill["name"],
            "roll": roll_result,
            "modifier": modifier,
            "total": total,
            "dc": dc,
            "outcome": outcome,
            "damage": damage,
            "enemy_defeated": enemy_defeated,
            "enemy_counter": enemy_counter,
            "player_status": player_status,
            "combat_status": combat_status,
            "round_result": round_result,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Skill hatası: {str(e)}"}), 500


@app.route("/api/game/heal", methods=["POST"])
def api_game_heal():
    """Player uses their heal skill (instant, not turn-based)."""
    try:
        data = request.json
        room_code = data.get("room_code", "").strip().upper()
        username = data.get("username", "").strip()
        target_player = data.get("target_player", "").strip()

        room = get_room(room_code)
        if not room:
            return jsonify({"error": "Oda bulunamadı"}), 404

        char = room.get_character_for_username(username)
        if not char:
            return jsonify({"error": "Karakter bulunamadı"}), 404

        session_id = room.session_id
        player_name = char["name"]

        # Dead check — dead players can't heal
        from game.xp_manager import get_player_stats, heal
        pstats = get_player_stats(session_id, player_name)
        if pstats and pstats["hp"] <= 0:
            return jsonify({"error": "Karakteriniz öldü! İyileştirme yapamazsınız.", "dead": True}), 400

        # Get heal skill
        class_name = char.get("class", "")
        skills_data = get_skills_for_class(class_name)
        if not skills_data:
            return jsonify({"error": "Skill verisi bulunamadı"}), 404
        heal_skill = skills_data["heal"]

        skill_levels = char.get("skill_levels", {})
        skill_level = skill_levels.get(heal_skill["id"], 1)
        abilities = char.get("abilities", {})
        ability_score = abilities.get(heal_skill["ability"], 10)

        heal_amount = calculate_skill_heal(heal_skill, skill_level, ability_score)

        healed_players = []
        revived_players = []

        if heal_skill.get("mass"):
            # Mass heal — heal all players
            for uname, pchar in room.players.items():
                pname = pchar["name"]
                before = get_player_stats(session_id, pname)
                was_dead = before and before["hp"] <= 0
                heal(session_id, pname, heal_amount)
                healed_players.append({"name": pname, "amount": heal_amount})
                if was_dead:
                    after = get_player_stats(session_id, pname)
                    if after and after["hp"] > 0:
                        revived_players.append(pname)
        else:
            # Single target heal
            if not target_player:
                return jsonify({"error": "Hedef oyuncu seçilmedi"}), 400
            target_stats = get_player_stats(session_id, target_player)
            if not target_stats:
                return jsonify({"error": f"Hedef '{target_player}' bulunamadı"}), 404
            was_dead = target_stats["hp"] <= 0
            heal(session_id, target_player, heal_amount)
            healed_players.append({"name": target_player, "amount": heal_amount})
            if was_dead:
                after = get_player_stats(session_id, target_player)
                if after and after["hp"] > 0:
                    revived_players.append(target_player)

        # XP
        grant_general_xp(session_id, player_name, 3, reason="iyileştirme")
        grant_ability_xp(session_id, player_name, heal_skill["ability"], amount=5)

        # Save message
        from db.session_manager import save_message
        if heal_skill.get("mass"):
            save_message(session_id, None, "user",
                         f"{player_name} uses {heal_skill['name_en']} — heals ALL players for {heal_amount} HP!")
        else:
            save_message(session_id, None, "user",
                         f"{player_name} uses {heal_skill['name_en']} on {target_player} for {heal_amount} HP.")

        # Updated statuses
        all_statuses = {}
        for uname, pchar in room.players.items():
            pname = pchar["name"]
            all_statuses[pname] = format_player_status(session_id, pname)

        return jsonify({
            "success": True,
            "heal_skill_name": heal_skill["name"],
            "heal_amount": heal_amount,
            "healed_players": healed_players,
            "revived_players": revived_players,
            "mass": heal_skill.get("mass", False),
            "player_statuses": all_statuses,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Heal hatası: {str(e)}"}), 500


@app.route("/api/game/upgrade-skill", methods=["POST"])
def api_upgrade_skill():
    """Player upgrades a skill on level up."""
    try:
        data = request.json
        room_code = data.get("room_code", "").strip().upper()
        username = data.get("username", "").strip()
        skill_id = data.get("skill_id", "").strip()

        room = get_room(room_code)
        if not room:
            return jsonify({"error": "Oda bulunamadı"}), 404

        char = room.get_character_for_username(username)
        if not char:
            return jsonify({"error": "Karakter bulunamadı"}), 404

        # Verify skill exists
        class_name = char.get("class", "")
        skill = get_skill_by_id(class_name, skill_id)
        if not skill:
            return jsonify({"error": "Skill bulunamadı"}), 404

        # Upgrade skill level (max 5)
        skill_levels = char.get("skill_levels", {})
        current_level = skill_levels.get(skill_id, 1)
        if current_level >= 5:
            return jsonify({"error": "Bu skill zaten maksimum seviyede!"}), 400

        skill_levels[skill_id] = current_level + 1
        char["skill_levels"] = skill_levels

        # Return updated skills info
        skills_info = get_all_skill_info(class_name, skill_levels)

        return jsonify({
            "success": True,
            "skill_id": skill_id,
            "new_level": current_level + 1,
            "skills": skills_info,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Upgrade hatası: {str(e)}"}), 500


@app.route("/api/game/pickup", methods=["POST"])
def api_game_pickup():
    data = request.json
    room_code = data.get("room_code", "").strip().upper()
    username = data.get("username", "").strip()
    accept = data.get("accept", False)

    room = get_room(room_code)
    if not room:
        return jsonify({"error": "Oda bulunamadı"}), 404

    gs = room.game_state
    session_id = room.session_id
    char = room.get_character_for_username(username)
    player_name = char["name"] if char else "Unknown"

    item = gs.pending_item
    if not item:
        return jsonify({"success": False, "msg": "No item to pick up."})

    gs.pending_item = None

    if not accept:
        save_message(session_id, None, "user", f"{player_name} decides to leave the {item['name']} behind.")
        return jsonify({"success": True, "picked_up": False, "msg": f"{item['name']} bırakıldı."})

    dc = get_pickup_dc(item.get("rarity", "common"))
    roll_info = {"ability": "dexterity", "dc": dc}
    roll_result = _execute_roll(roll_info, player_name, gs, session_id, {})

    if roll_result.get("success"):
        add_item(session_id, item["name"], 1, item.get("value", 0), item.get("rarity", "common"), player_name)
        save_message(session_id, None, "user", f"{player_name} successfully picks up the {item['name']}!")
        msg = f"✅ {item['name']} envantere eklendi!"
    else:
        save_message(session_id, None, "user", f"{player_name} fumbles and fails to grab the {item['name']}.")
        msg = f"❌ {item['name']} alınamadı."

    # Get this player's updated inventory
    inventory = get_inventory(session_id, player_name)

    return jsonify({
        "success": True,
        "picked_up": roll_result.get("success"),
        "msg": msg,
        "roll": roll_result,
        "inventory": inventory,
        "player_status": format_player_status(session_id, player_name),
    })


@app.route("/api/game/npcs", methods=["GET"])
def api_get_npcs():
    room_code = request.args.get("room_code", "").strip().upper()
    room = get_room(room_code)
    if not room or not room.session_id:
        return jsonify({"npcs": []})
    npcs = get_all_npcs(room.session_id)
    npcs_clean = [{"name": n["name"], "public": translator.translate_npc_data(n["public"])} for n in npcs]
    return jsonify({"npcs": npcs_clean})


@app.route("/api/game/state", methods=["GET"])
def api_game_state():
    room_code = request.args.get("room_code", "").strip().upper()
    room = get_room(room_code)
    if not room:
        return jsonify({"error": "Oda bulunamadı"}), 400

    gs = room.game_state
    sm = room.scenario_manager

    characters = gs.characters if gs.characters else []
    return jsonify({
        "characters": characters,
        "scenario_title": sm.meta.get("title", "") if sm else "Serbest Macera",
        "node_title": sm.current_node.get("title", "") if sm and sm.current_node else "",
        "current_scene": gs.current_scene,
        "game_started": room.game_started,
    })


# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n⚔️  DungeonMaster UI (Multiplayer) başlatılıyor...")
    print("   http://localhost:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
