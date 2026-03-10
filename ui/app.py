"""
ui/app.py — Flask web arayüzü
Mevcut oyun kodlarına dokunmadan, onları import ederek çalışır.
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
from prompts.system_prompt import build_system_prompt
from rag.retriever import get_relevant_rules
from rag.ingest import ingest
import config

from ui import translator

# ─── FLASK APP ────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="static")

# ─── GLOBAL GAME STATE ────────────────────────────────────────────────────────

_state = {
    "user": None,
    "session_id": None,
    "game_state": None,
    "scenario_manager": None,
    "initialized": False,
    "game_started": False,
}


def _init_once():
    """Veritabanı ve RAG'ı bir kez başlat. Çeviri modelini arka planda yükle."""
    if not _state["initialized"]:
        initialize_db()
        ingest()
        translator.ensure_model_loaded()
        _state["initialized"] = True


# ─── OLLAMA ÇAĞRISI (streaming destekli) ──────────────────────────────────────

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
    """Zar gerekli mi kontrolü — main.py'deki ile aynı mantık."""
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

    char = game_state.characters[0]
    abilities = char.get("abilities", {})
    score = abilities.get(ability, 10)
    modifier = get_modifier(score)

    roll_result = d20()
    total = roll_result + modifier

    if roll_result == 20:
        outcome_label = "CRITICAL SUCCESS"
    elif roll_result == 1:
        outcome_label = "CRITICAL FAILURE"
    elif total >= dc:
        outcome_label = "SUCCESS"
    else:
        outcome_label = "FAILURE"

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
    }


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
        
    # config.py dosyasına değişiklikleri kalıcı olarak yaz
    import re
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


# ─── AUTH ─────────────────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def api_login():
    _init_once()
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    action = data.get("action", "login")  # "login" veya "register"

    if not username or not password:
        return jsonify({"error": "Kullanıcı adı ve şifre gerekli"}), 400

    if action == "register":
        result = register_user(username, password, "player")
        if not result:
            return jsonify({"error": "Kayıt başarısız, kullanıcı adı alınmış olabilir"}), 400

    user = login_user(username, password)
    if not user:
        return jsonify({"error": "Giriş başarısız"}), 401

    _state["user"] = user
    return jsonify({"success": True, "username": user["username"], "role": user["role"]})


# ─── SESSIONS ─────────────────────────────────────────────────────────────────

@app.route("/api/sessions", methods=["GET"])
def api_get_sessions():
    active = get_active_session()
    return jsonify({"active_session": dict(active) if active else None})


@app.route("/api/sessions", methods=["POST"])
def api_create_session():
    data = request.json
    name = data.get("name", "Web Session").strip()
    session_id = create_session(name)
    _state["session_id"] = session_id
    _state["game_state"] = GameState()
    _state["game_state"].session_id = session_id
    _state["game_started"] = False
    return jsonify({"success": True, "session_id": session_id})


@app.route("/api/sessions/continue", methods=["POST"])
def api_continue_session():
    active = get_active_session()
    if not active:
        return jsonify({"error": "Aktif oturum yok"}), 404
    _state["session_id"] = active["id"]
    _state["game_state"] = GameState()
    _state["game_state"].session_id = active["id"]
    _state["game_started"] = False
    return jsonify({"success": True, "session_id": active["id"], "session_name": active["session_name"]})


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

    gs = _state["game_state"]
    if gs is None:
        return jsonify({"error": "Önce oturum oluşturun"}), 400

    gs.add_player({}, character)
    return jsonify({"success": True, "character": character})


@app.route("/api/characters/options", methods=["GET"])
def api_character_options():
    """Karakter oluşturma için ırk ve sınıf seçeneklerini döndür."""
    races = {k: {"name": v["name"], "display": v["display"], "bonuses": v["bonuses"]} for k, v in RACES.items()}
    classes = {k: {"name": v["name"], "display": v["display"], "tip": v["tip"], "hp_dice": v["hp_dice"]} for k, v in CLASSES.items()}
    return jsonify({"races": races, "classes": classes, "ability_display": ABILITY_DISPLAY})


@app.route("/api/characters/create", methods=["POST"])
def api_create_character():
    """Web üzerinden basitleştirilmiş karakter oluşturma."""
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

    # Abilities: varsayılan 10
    abilities = {
        "strength": int(abilities_input.get("strength", 10)),
        "dexterity": int(abilities_input.get("dexterity", 10)),
        "constitution": int(abilities_input.get("constitution", 10)),
        "intelligence": int(abilities_input.get("intelligence", 10)),
        "wisdom": int(abilities_input.get("wisdom", 10)),
        "charisma": int(abilities_input.get("charisma", 10)),
    }

    # Irk bonuslarını ekle
    final_abilities = abilities.copy()
    for ab, bonus in selected_race["bonuses"].items():
        final_abilities[ab] = final_abilities.get(ab, 8) + bonus

    con_modifier = (final_abilities["constitution"] - 10) // 2
    max_hp = selected_class["hp_dice"] + con_modifier
    max_hp = max(max_hp, 1)

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
        "background": background,
    }

    # YAML'a kaydet
    os.makedirs(config.character_dir, exist_ok=True)
    filename = f"{name.lower().replace(' ', '_')}.yaml"
    filepath = os.path.join(config.character_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        _yaml.dump(character, f, allow_unicode=True, default_flow_style=False)

    # GameState'e ekle
    gs = _state["game_state"]
    if gs:
        gs.add_player({}, character)

    return jsonify({"success": True, "character": character, "filename": filename})


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


@app.route("/api/scenarios/start", methods=["POST"])
def api_start_scenario():
    data = request.json
    path = data.get("path", "")

    gs = _state["game_state"]
    if gs is None or not gs.characters:
        return jsonify({"error": "Önce karakter yükleyin"}), 400

    if not path:
        # Serbest mod
        _state["scenario_manager"] = None
        return jsonify({"success": True, "mode": "free_play"})

    try:
        sm = ScenarioManager(path)
        sm.start()
        _state["scenario_manager"] = sm
        if sm.current_node:
            gs.current_node = sm.current_node.get("title", "")
        return jsonify({
            "success": True,
            "mode": "scenario",
            "title": sm.meta.get("title", ""),
            "node_title": sm.current_node.get("title", "") if sm.current_node else "",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── GAME ─────────────────────────────────────────────────────────────────────

@app.route("/api/game/start", methods=["POST"])
def api_game_start():
    """Maceraya başla — GM'den giriş sahnesini al."""
    gs = _state["game_state"]
    sm = _state["scenario_manager"]
    session_id = _state["session_id"]
    user = _state["user"]

    if not gs or not gs.characters:
        return jsonify({"error": "Karakter yüklenmedi"}), 400
    if not session_id:
        return jsonify({"error": "Oturum yok"}), 400

    player_names_list = [c["name"] for c in gs.characters]

    # Başlangıç mesajı
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

    # GM'den giriş
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

    _state["game_started"] = True

    # Translation
    gm_intro_tr = translator.translate_en_to_tr(gm_intro)

    # NPC'leri döndür (çevirerek)
    npcs = get_all_npcs(session_id)
    npcs_clean = [{"name": n["name"], "public": translator.translate_npc_data(n["public"])} for n in npcs]

    return jsonify({
        "success": True,
        "gm_response": gm_intro,
        "gm_response_tr": gm_intro_tr,
        "npcs": npcs_clean,
        "scenario_title": sm.meta.get("title", "") if sm else "Serbest Macera",
        "node_title": sm.current_node.get("title", "") if sm and sm.current_node else "",
    })


@app.route("/api/game/action", methods=["POST"])
def api_game_action():
    """Oyuncu eylemi → zar kontrolü → GM cevabı."""
    gs = _state["game_state"]
    sm = _state["scenario_manager"]
    session_id = _state["session_id"]
    user = _state["user"]

    if not gs or not gs.characters:
        return jsonify({"error": "Oyun başlatılmadı"}), 400

    data = request.json
    action = data.get("action", "").strip()
    player_name = data.get("player_name", "").strip()

    if not action:
        return jsonify({"error": "Eylem boş olamaz"}), 400

    # Karakter adı doğrula
    valid_names = [c["name"].lower() for c in gs.characters]
    if not player_name:
        player_name = gs.characters[0]["name"]
    elif player_name.lower() not in valid_names:
        player_name = gs.characters[0]["name"]
    else:
        player_name = next(
            c["name"] for c in gs.characters if c["name"].lower() == player_name.lower()
        )

    player_names_list = [c["name"] for c in gs.characters]
    user_message = f"{player_name}: {action}"
    save_message(session_id, user.get("id") if user else None, "user", user_message)

    # TRIGGER CHECK
    transition_info = None
    if sm:
        recent_for_trigger = get_recent_messages(session_id)
        next_node = sm.check_trigger(recent_for_trigger)
        if next_node:
            sm.load_node(next_node)
            if sm.current_node:
                gs.current_node = sm.current_node.get("title", "")
            transition_msg = (
                f"[SCENE TRANSITION: players have arrived at "
                f"{sm.current_node.get('title', next_node)}]"
            )
            save_message(session_id, None, "user", transition_msg)
            transition_info = {
                "new_node": next_node,
                "new_node_title": sm.current_node.get("title", next_node) if sm.current_node else next_node,
            }

    # ROLL CHECK
    node_actions = None
    if sm and sm.current_node:
        node_actions = sm.current_node.get("available_actions")

    roll_info = _needs_roll_check(action, node_actions)
    roll_result = None
    roll_result_msg = None
    if roll_info.get("needed"):
        roll_result = _execute_roll(roll_info, player_name, gs, session_id, user)
        roll_result_msg = roll_result["roll_message"]

    # GM CEVABI
    recent_messages = get_recent_messages(session_id)
    system_prompt = build_system_prompt(
        gs.characters, action,
        gs, sm,
        roll_info=roll_result_msg, session_id=session_id
    )

    gm_response = _ask_gm_full(recent_messages, system_prompt)

    # NPC Extraction
    existing_npc_names = [n["name"] for n in get_all_npcs(session_id)]
    new_npcs = extract_npcs_from_response(
        gm_response, recent_messages, existing_npc_names, player_names_list
    )
    for npc in new_npcs:
        public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
        save_npc(npc["name"], public_data, npc["secret"], session_id)

    gs.set_scene(gm_response[:100])
    save_message(session_id, None, "assistant", gm_response)

    # Çeviriler
    gm_response_tr = translator.translate_en_to_tr(gm_response)
    
    # NPC listesi (çevrilmiş public data ile)
    npcs = get_all_npcs(session_id)
    npcs_clean = [{"name": n["name"], "public": translator.translate_npc_data(n["public"])} for n in npcs]

    result = {
        "success": True,
        "gm_response": gm_response,
        "gm_response_tr": gm_response_tr,
        "player_name": player_name,
        "action": action,
        "npcs": npcs_clean,
    }
    if roll_result:
        result["roll"] = roll_result
    if transition_info:
        result["transition"] = transition_info

    return jsonify(result)


@app.route("/api/game/npcs", methods=["GET"])
def api_get_npcs():
    session_id = _state["session_id"]
    if not session_id:
        return jsonify({"npcs": []})
    npcs = get_all_npcs(session_id)
    npcs_clean = [{"name": n["name"], "public": translator.translate_npc_data(n["public"])} for n in npcs]
    return jsonify({"npcs": npcs_clean})


@app.route("/api/game/messages", methods=["GET"])
def api_get_messages():
    session_id = _state["session_id"]
    if not session_id:
        return jsonify({"messages": []})
    messages = get_recent_messages(session_id)
    return jsonify({"messages": messages})


@app.route("/api/game/state", methods=["GET"])
def api_game_state():
    gs = _state["game_state"]
    sm = _state["scenario_manager"]
    if not gs:
        return jsonify({"error": "Oyun başlatılmadı"}), 400

    characters = gs.characters if gs.characters else []
    return jsonify({
        "characters": characters,
        "scenario_title": sm.meta.get("title", "") if sm else "Serbest Macera",
        "node_title": sm.current_node.get("title", "") if sm and sm.current_node else "",
        "current_scene": gs.current_scene,
        "game_started": _state["game_started"],
    })


# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n⚔️  DungeonMaster UI başlatılıyor...")
    print("   http://localhost:5000\n")
    app.run(debug=True, port=5000, use_reloader=False)
