import os
import re
import time
import json
from db.database import initialize_db
from db.user_manager import register_user, login_user
from db.session_manager import (
    create_session, get_active_session,
    end_session, save_message, get_recent_messages
)
from game.character_manager import load_character_from_yaml
from game.game_state import GameState
from game.dice import d20, get_modifier
from game.npc_manager import get_all_npcs, save_npc
from game.npc_extractor import extract_npcs_from_response
from game.scenario_manager import ScenarioManager
from game.combat import player_attack, enemy_attack, format_encounter_status
from game.encounter_manager import parse_encounter_block, strip_encounter_block, create_encounter, get_alive_enemies, is_encounter_over, get_total_xp, generate_combat_summary
from game.event_parser import parse_encounter_from_response, strip_encounter_from_response
from game.inventory_manager import use_item, add_item, get_pickup_dc, display_inventory
from game.xp_manager import (
    init_player_stats, grant_general_xp, grant_ability_xp,
    grant_combat_xp, grant_quest_rewards, apply_damage, add_gold, format_player_status
)
from game.quest_manager import init_quests, check_node_quests
from game.event_parser import parse_gm_events
from prompts.system_prompt import build_system_prompt
from rag.retriever import get_relevant_rules
from rag.ingest import ingest
from game.character_creator import create_character
import requests
import config

# ─── OLLAMA'YA İSTEK GÖNDER ──────────────────────────────────────────────────

def ask_gm(messages, system_prompt):
    start = time.time()
    response = requests.post(
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
                "num_predict": config.num_predict
            }
        },
        stream=True
    )

    full_response = ""
    prompt_tokens = 0
    response_tokens = 0
    first_chunk_time = None

    print("\n🧙 GM: ", end="", flush=True)

    for line in response.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        if first_chunk_time is None:
            first_chunk_time = time.time() - start
        message = chunk.get("message", {})
        content = message.get("content", "")
        if content:
            print(content, end="", flush=True)
            full_response += content
        if chunk.get("done"):
            prompt_tokens = chunk.get("prompt_eval_count", "?")
            response_tokens = chunk.get("eval_count", "?")

    elapsed = time.time() - start
    print(f"\n\n⏱️  Toplam : {elapsed:.2f}s  |  İlk token: {first_chunk_time:.2f}s")
    print(f"📊 Prompt : {prompt_tokens} token  |  Cevap: {response_tokens} token")
    return full_response

# ─── ZAR GEREKLİ Mİ? ─────────────────────────────────────────────────────────

def needs_roll_check(action, node_available_actions=None):
    print("\n" + "─" * 40)
    print(f"🎯 DEBUG needs_roll_check")
    print(f"   Eylem: '{action}'")

    examples = get_relevant_rules(f"dice roll ability check required: {action}")
    if not examples:
        examples = "No examples found."
    print(f"   RAG sonucu (ilk 200 kr): {str(examples)[:200]}")

    node_context = ""
    if node_available_actions:
        node_context = f"\nSCENE SPECIFIC ACTIONS (use these DCs if action matches):\n{node_available_actions}"
        print(f"   Node actions mevcut: EVET")
    else:
        print(f"   Node actions mevcut: HAYIR")

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
        response = requests.post(
            f"{config.base_url}/api/chat",
            json={
                "model": config.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 50}
            }
        )
        result = response.json()
        answer = result["message"]["content"].strip()
        print(f"   AI ham cevap: '{answer}'")
        answer = re.sub(r'```json|```', '', answer).strip()
        match = re.search(r'\{.*?\}', answer, re.DOTALL)
        if match:
            answer = match.group(0)
            print(f"   JSON parse edildi: '{answer}'")
        else:
            print(f"   ⚠️  JSON bulunamadı, roll yok sayılıyor")
            return {"needed": False}

        data = json.loads(answer)
        if data.get("needed"):
            result_info = {
                "needed": True,
                "ability": data.get("ability", "strength").lower(),
                "dc": int(data.get("dc", 12))
            }
            print(f"   ✅ Roll GEREKLİ → {result_info}")
            return result_info

        print(f"   ⏭️  Roll GEREKMİYOR")
        return {"needed": False}

    except Exception as e:
        print(f"   ❌ needs_roll_check HATA: {e}")
        return {"needed": False}
    finally:
        print("─" * 40)

# ─── ZAR AT ──────────────────────────────────────────────────────────────────

def execute_roll(roll_info, player_name, game_state, session_id, user):
    ability = roll_info["ability"]
    dc = roll_info["dc"]

    ability_map = {
        "dex": "dexterity", "str": "strength", "con": "constitution",
        "wis": "wisdom", "int": "intelligence", "cha": "charisma"
    }
    ability = ability_map.get(ability, ability)

    print(f"\nDEBUG execute_roll: ability={ability}, dc={dc}")

    char = game_state.characters[0]
    abilities = char.get("abilities", {})
    score = abilities.get(ability, 10)
    modifier = get_modifier(score)

    print(f"DEBUG execute_roll: karakter={char.get('name')}, score={score}, modifier={modifier}")

    roll_result = d20()
    total = roll_result + modifier

    print("\n" + "─" * 50)
    print(f"🎲 {ability.capitalize()} check vs DC {dc}")
    print(f"   Zar: {roll_result} | Modifier: {modifier:+d} | Toplam: {total} | DC: {dc}")

    success = False
    if roll_result == 20:
        outcome_label = "CRITICAL SUCCESS"
        success = True
        print("   ⭐ KRİTİK BAŞARI!")
    elif roll_result == 1:
        outcome_label = "CRITICAL FAILURE"
        print("   💀 KRİTİK BAŞARISIZLIK!")
    elif total >= dc:
        outcome_label = "SUCCESS"
        success = True
        print("   ✅ BAŞARILI")
    else:
        outcome_label = "FAILURE"
        print("   ❌ BAŞARISIZ")

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
    if game_state.is_combat:
        game_state.combat_messages.append({"role": "user", "content": db_message})
    else:
        save_message(session_id, user.get("id"), "user", db_message)
    print(f"\nDEBUG execute_roll → GM'e gidecek mesaj:\n{roll_message}")
    return roll_message, success

# ─── EŞYA ALMA ───────────────────────────────────────────────────────────────

def handle_item_pickup(game_state, player_name, session_id, user):
    item = game_state.pending_item
    if not item:
        return None

    dc = get_pickup_dc(item.get("rarity", "common"))
    print(f"\n🎒 EŞYA BULUNDU: {item['name']} (DC {dc} to pick up)")
    choice = input(f"Almak ister misin? (e/h): ").strip().lower()

    if choice != "e":
        game_state.pending_item = None
        return f"{player_name} decides to leave the {item['name']} behind."

    roll_info = {"ability": "dexterity", "dc": dc}
    roll_msg, success = execute_roll(roll_info, player_name, game_state, session_id, user)

    if success:
        add_item(session_id, item["name"], 1, item.get("value", 0), item.get("rarity", "common"))
        result_msg = f"{player_name} successfully picks up the {item['name']}!"
        print(f"   ✅ {item['name']} envantere eklendi!")
    else:
        result_msg = f"{player_name} fumbles and fails to grab the {item['name']}."
        print(f"   ❌ {item['name']} alınamadı.")

    game_state.pending_item = None
    return result_msg

# ─── BAŞARILI ROLL SONRASI EŞYA EDİNME ──────────────────────────────────────

ACQUIRE_PATTERNS = [
    r"steal\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"grab\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"take\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"pick\s+up\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"snatch\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"swipe\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"lift\s+(?:the\s+|a\s+|an\s+)?(.+)",
    r"pocket\s+(?:the\s+|a\s+|an\s+)?(.+)",
    # Türkçe
    r"(.+?)\s*(?:çal|çalıyorum|çaldım|al|alıyorum|aldım|kap|kaptım)",
]

def check_item_acquisition(action):
    """
    Başarılı roll sonrası: aksiyon eşya edinme içeriyor mu?
    Döner: item_name string veya None
    """
    action_lower = action.lower().strip()
    # "I" ile başlayan kalıpları temizle
    action_clean = re.sub(r"^i\s+", "", action_lower)

    for pattern in ACQUIRE_PATTERNS:
        match = re.search(pattern, action_clean, re.IGNORECASE)
        if match:
            item = match.group(1).strip().rstrip('.,!?')
            # Çok uzunsa (cümle değil eşya adı olsun)
            if len(item.split()) <= 4:
                return item
    return None

# ─── EŞYA KULLANMA ───────────────────────────────────────────────────────────

def handle_item_use(action, player_name, session_id, game_state):
    match_en = re.search(r'\buse\b\s+(?:my\s+|the\s+)?(.+)', action, re.IGNORECASE)
    match_tr = re.search(r'(.+?)\s*(?:kullan|kullanıyorum|kullandım)', action, re.IGNORECASE)

    item_name = None
    if match_en:
        item_name = match_en.group(1).strip().rstrip('.')
    elif match_tr:
        item_name = match_tr.group(1).strip().lstrip('I').strip()

    if not item_name:
        return False, None

    success, msg = use_item(session_id, item_name)
    print(f"\n🎒 EŞYA KULLANIMI: '{item_name}' → {msg}")

    if success:
        grant_general_xp(session_id, player_name, 1, reason="eşya kullanıldı")
        return True, f"{player_name} uses {item_name}."
    else:
        print(msg)
        return False, None

# ─── GİRİŞ EKRANI ────────────────────────────────────────────────────────────

def login_screen():
    print("\n⚔️  DUNGEON MASTER AI  ⚔️")
    print("─" * 30)
    print("1. Giriş yap")
    print("2. Kayıt ol")
    choice = input("\nSeçim: ").strip()

    username = input("Kullanıcı adı: ").strip()
    password = input("Şifre: ").strip()

    if choice == "2":
        user = register_user(username, password, "player")
        if not user:
            print("Kayıt başarısız.")
            return None
        return login_user(username, password)
    else:
        return login_user(username, password)

# ─── KARAKTER YÜKLE ──────────────────────────────────────────────────────────

def load_player_characters(game_state):
    os.makedirs(config.character_dir, exist_ok=True)
    files = [f for f in os.listdir(config.character_dir) if f.endswith('.yaml')]

    while True:
        print("\n🧙 KARAKTER YÜKLE")
        print("─" * 30)
        print("1. Yeni karakter oluştur")

        if files:
            print("2. Mevcut karakter yükle")
            choice = input("\nSeçim (1/2): ").strip()
        else:
            print("  (Kayıtlı karakter yok)")
            choice = "1"

        if choice == "1":
            character = create_character()
            if character:
                game_state.add_player({}, character)
                return character

        elif choice == "2":
            print("\nKarakter dosyaları:")
            for i, f in enumerate(files, 1):
                print(f"  {i}. {f}")

            selected = input("Numara veya dosya adı: ").strip()
            if not selected:
                continue

            if selected.isdigit():
                idx = int(selected) - 1
                if 0 <= idx < len(files):
                    selected = files[idx]
                else:
                    print("⚠️  Geçersiz numara.")
                    continue

            if not selected.endswith('.yaml'):
                selected += '.yaml'

            character = load_character_from_yaml(selected)
            if character:
                game_state.add_player({}, character)
                print(f"✅ {character['name']} oyuna katıldı!")
                another = input("Başka karakter eklemek ister misin? (e/h): ").strip().lower()
                if another == "e":
                    files = [f for f in os.listdir(config.character_dir) if f.endswith('.yaml')]
                    continue
                return character
            else:
                print("⚠️  Karakter yüklenemedi.")
                continue
        else:
            print("⚠️  Geçersiz seçim.")
            continue

# ─── SENARYO SEÇ ─────────────────────────────────────────────────────────────

def select_scenario():
    print("\n📖 SENARYO")
    print("─" * 30)
    choice = input("Bir senaryo takip etmek istiyor musun? (e/h): ").strip().lower()

    if choice != "e":
        print("ℹ️  Serbest mod — hayal gücüne bırakıldı.")
        return None

    scenarios_root = "scenarios"
    if not os.path.exists(scenarios_root):
        print("⚠️  'scenarios/' klasörü bulunamadı, serbest mod.")
        return None

    found = []
    for entry in sorted(os.listdir(scenarios_root)):
        entry_path = os.path.join(scenarios_root, entry)
        meta_path = os.path.join(entry_path, "scenario.yaml")
        if os.path.isdir(entry_path) and os.path.exists(meta_path):
            try:
                import yaml
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = yaml.safe_load(f)
                title = meta.get("title", entry)
                description = meta.get("description", "")
            except Exception:
                title = entry
                description = ""
            found.append({"path": entry_path, "title": title, "description": description})

    if not found:
        print("⚠️  Hiç senaryo bulunamadı, serbest mod.")
        return None

    print("\nMevcut senaryolar:")
    for i, s in enumerate(found, 1):
        desc_short = s["description"][:60] + "..." if len(s["description"]) > 60 else s["description"]
        print(f"  {i}. {s['title']}")
        if desc_short:
            print(f"     {desc_short}")

    while True:
        selected = input("\nNumara ile seçin: ").strip()
        if selected.isdigit():
            idx = int(selected) - 1
            if 0 <= idx < len(found):
                chosen = found[idx]
                break
        print("⚠️  Geçersiz seçim.")

    try:
        sm = ScenarioManager(chosen["path"])
        sm.start()
        print(f"✅ Senaryo yüklendi: {chosen['title']}")
        return sm
    except Exception as e:
        print(f"⚠️  Senaryo yüklenirken hata: {e}")
        return None

def generate_llm_combat_summary(session_id, combat_messages, game_state, dead_players=None):
    print(f"🐞 DEBUG [Combat/CLI]: generate_llm_combat_summary called with {len(combat_messages)} messages")
    prompt = (
        "Summarize the following combat encounter in a short, narrative, and engaging paragraph. "
        "The summary should read like a story, describing the flow of battle, who did what, and how it ended. "
        "Focus on the narrative, not mechanical numbers.\n\n"
        "Combat Log:\n"
    )
    for msg in combat_messages:
        role = "Player" if msg["role"] == "user" else "Game Master"
        prompt += f"{role}: {msg['content']}\n"
        
    if dead_players:
        prompt += f"\nNote: The following players died or fell unconscious during the battle: {', '.join(dead_players)}. Incorporate this tragedy into the narrative."
    
    # We call ask_gm manually so we don't mess up main flow
    response = requests.post(
        f"{config.base_url}/api/chat",
        json={
            "model": config.model,
            "messages": [{"role": "user", "content": "Please summarize the combat."}],
            "system": prompt,
            "stream": False,
            "think": False,
            "options": {"num_ctx": config.context_length, "temperature": config.temp}
        }
    ).json()
    summary = response.get("message", {}).get("content", "")
    print(f"🐞 DEBUG [Combat/CLI]: NARRATIVE SUMMARY GENERATED:\n{summary}\n")
    return summary

# ─── ANA OYUN DÖNGÜSÜ ────────────────────────────────────────────────────────

def game_loop(user, session_id, game_state, scenario_manager):
    print("\n🎲 Macera başlıyor...\n")
    print("─" * 50)

    valid_names = [c['name'].lower() for c in game_state.characters]
    names_display = ", ".join([c['name'] for c in game_state.characters])
    player_names_list = [c['name'] for c in game_state.characters]

    for char in game_state.characters:
        init_player_stats(session_id, char["name"], char)

    if scenario_manager:
        init_quests(session_id, scenario_manager.meta)

    if scenario_manager and scenario_manager.current_node:
        node = scenario_manager.current_node
        intro_message = (
            f"The adventure begins. "
            f"Location: {node.get('title', 'Unknown')}. "
            f"Set the opening scene. Maximum 3 sentences."
        )
    else:
        intro_message = (
            "The players have just begun their adventure. "
            "Set the scene. Maximum 3 sentences. "
            "Describe where they are and end with an open situation."
        )

    system_prompt = build_system_prompt(
        game_state.characters, "begin adventure exploration",
        game_state, scenario_manager, session_id=session_id
    )

    print("\n" + "═" * 50)
    print("🔍 DEBUG — SYSTEM PROMPT (ilk 800 karakter)")
    print("═" * 50)
    print(system_prompt[:800])
    print("═" * 50 + "\n")

    npcs = get_all_npcs(session_id)
    print(f"🔍 DEBUG — BAŞLANGIÇ NPC'LERİ ({len(npcs)} adet):")
    if npcs:
        for npc in npcs:
            print(f"   • {npc['name']} | {npc['public'].get('role','?')}")
    else:
        print("   (henüz NPC yok)")
    print()

    print("⏳ GM başlangıç sahnesini hazırlıyor...\n")
    gm_intro = ask_gm(
        [{"role": "user", "content": intro_message}],
        system_prompt
    )

    existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
    new_npcs = extract_npcs_from_response(
        gm_intro, [{"role": "assistant", "content": gm_intro}],
        existing_npc_names, player_names_list
    )
    for npc in new_npcs:
        public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
        save_npc(npc["name"], public_data, npc["secret"], session_id)

    game_state.set_scene(gm_intro[:100])
    if scenario_manager and scenario_manager.current_node:
        game_state.current_node = scenario_manager.current_node.get("title", "")

    print("\n" + "─" * 50)
    save_message(session_id, None, "user", intro_message)
    save_message(session_id, None, "assistant", gm_intro)

    for char in game_state.characters:
        print(format_player_status(session_id, char["name"]))

    while True:

        # ── Karakter adı ──
        while True:
            print(f"\nAktif karakterler: {names_display}")
            player_name = input("Karakter adı (veya 'quit' / 'inventory'): ").strip()

            if player_name.lower() == "quit":
                return

            if player_name.lower() in ("inventory", "envanter", "i"):
                display_inventory(session_id)
                continue

            if not player_name:
                print("⚠️  Karakter adı boş olamaz.")
                continue

            if player_name.lower() in valid_names:
                player_name = next(
                    c['name'] for c in game_state.characters
                    if c['name'].lower() == player_name.lower()
                )
                break
            else:
                print(f"⚠️  '{player_name}' bulunamadı. Geçerli: {names_display}")

        # ── Eylem ──
        action = input(f"{player_name} ne yapıyor? > ").strip()

        if not action:
            print("⚠️  Eylem boş olamaz.")
            continue

        if action.lower() == "quit":
            return

        # ─ Eşya kullanma kontrolü ─
        item_used, item_gm_msg = handle_item_use(action, player_name, session_id, game_state)
        if not item_used and re.search(r'\buse\b|kullan', action, re.IGNORECASE) and item_gm_msg is None:
            # Eşya yok, hata gösterildi, döngü başına dön
            continue

        user_message = f"{player_name}: {action}"
        if game_state.is_combat:
            game_state.combat_messages.append({"role": "user", "content": user_message})
        else:
            save_message(session_id, user.get("id"), "user", user_message)
        
        if item_used and item_gm_msg:
            if game_state.is_combat:
                game_state.combat_messages.append({"role": "user", "content": item_gm_msg})
            else:
                save_message(session_id, None, "user", item_gm_msg)

        grant_general_xp(session_id, player_name, 1, reason="aksiyon")

        # ════════════════════════════════════════════════════
        # ADIM 1: TRIGGER CHECK
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("📍 ADIM 1 — TRIGGER CHECK")
        print("═" * 50)

        if scenario_manager:
            current_id = scenario_manager.current_node.get('id', '?') if scenario_manager.current_node else '?'
            current_title = scenario_manager.current_node.get('title', '?') if scenario_manager.current_node else '?'
            print(f"   Mevcut node: {current_id} — {current_title}")

            recent_for_trigger = get_recent_messages(session_id)
            next_node = scenario_manager.check_trigger(recent_for_trigger)
            print(f"   Trigger sonucu: {next_node if next_node else 'YOK'}")

            if next_node:
                scenario_manager.load_node(next_node)
                if scenario_manager.current_node:
                    game_state.current_node = scenario_manager.current_node.get("title", "")

                quest_events = check_node_quests(session_id, next_node)
                for qe in quest_events:
                    if qe["event"] == "completed":
                        grant_quest_rewards(session_id, player_name, qe["quest"])

                transition_msg = f"[SCENE TRANSITION: players have arrived at {scenario_manager.current_node.get('title', next_node)}]"
                save_message(session_id, None, "user", transition_msg)
        else:
            print("   Senaryo yok — trigger atlandı")

        # ════════════════════════════════════════════════════
        # ADIM 2: COMBAT CHECK
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("⚔️  ADIM 2 — COMBAT CHECK")
        print("═" * 50)

        roll_result_msg = None

        if game_state.is_combat and game_state.active_encounter:
            print(f"   Aktif savaş: {game_state.active_encounter['enemy_name']}")
            print(format_encounter_status(game_state))

            attack_msg, damage, enemy_defeated = player_attack(game_state, player_name, session_id, user)
            roll_result_msg = attack_msg

            if enemy_defeated:
                print(f"🐞 DEBUG [Combat/CLI]: Encounter over. Defeated enemy. Compiling summaries.")
                xp = game_state.active_encounter.get("xp_reward", 50)
                grant_combat_xp(session_id, player_name, xp)
                
                # Savaş bittiğinde mekanik özet ve NARRATIVE özet çıkar
                mechanical_summary = generate_combat_summary(game_state.active_encounter, [])
                narrative_summary = generate_llm_combat_summary(session_id, game_state.combat_messages, game_state)
                final_summary = f"{mechanical_summary}\n\n[NARRATIVE RECAP]\n{narrative_summary}"
                save_message(session_id, None, "assistant", final_summary)
                game_state.combat_messages = []
                
                game_state.end_encounter()
            else:
                enemy_dmg, enemy_msg = enemy_attack(game_state, player_name, session_id)
                if enemy_dmg > 0:
                    is_down, _ = apply_damage(session_id, player_name, enemy_dmg)
                    roll_result_msg += f"\n{enemy_msg}"
                    if is_down:
                        roll_result_msg += f"\n{player_name} has fallen unconscious!"
                        print(f"   💀 {player_name} bilinci kaybetti!")

        else:
            # Combat artık [ENCOUNTER] bloğu ile GM cevabından tetiklenir
            # CLI'da GM cevabı sonrası parse edilir
            print("   ⏭️  Combat şimdi [ENCOUNTER] bloğu ile tetikleniyor")

        # ════════════════════════════════════════════════════
        # ADIM 3: ROLL CHECK
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🎲 ADIM 3 — ROLL CHECK")
        print("═" * 50)

        node_actions = None
        if scenario_manager and scenario_manager.current_node:
            node_actions = scenario_manager.current_node.get("available_actions")
            print(f"   Node available_actions: {'mevcut' if node_actions else 'YOK'}")

        roll_info = needs_roll_check(action, node_actions)

        if roll_info.get("needed"):
            roll_result_msg, roll_success = execute_roll(roll_info, player_name, game_state, session_id, user)
            # Başarılı roll: eşya edinme aksiyonu mu?
            if roll_success:
                acquired_item = check_item_acquisition(action)
                if acquired_item:
                    add_item(session_id, acquired_item, 1, 0, "common")
                    print(f"   🎒 '{acquired_item}' envantere eklendi (başarılı roll)")
                    save_message(session_id, None, "user", f"{player_name} successfully acquires: {acquired_item}")
        else:
            print("   ⏭️  Zar atılmadı")
            grant_general_xp(session_id, player_name, 1, reason="aksiyon (roll yok)")

        # ════════════════════════════════════════════════════
        # ADIM 4: GM CEVABI
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🧙 ADIM 4 — GM CEVABI")
        print("═" * 50)

        recent_messages = get_recent_messages(session_id) + game_state.combat_messages
        system_prompt = build_system_prompt(
            game_state.characters, action,
            game_state, scenario_manager,
            roll_info=roll_result_msg, session_id=session_id
        )

        print(f"🐞 DEBUG [Combat/CLI]: Requesting GM response. (Combat? {game_state.is_combat})")
        print(f"   System prompt uzunluğu: {len(system_prompt)} karakter")
        print("⏳ GM düşünüyor...\n")
        gm_response = ask_gm(recent_messages, system_prompt)

        # ════════════════════════════════════════════════════
        # ADIM 5: EVENT PARSER
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🔍 ADIM 5 — EVENT PARSER")
        print("═" * 50)

        events = parse_gm_events(gm_response)
        print(f"   Parser sonucu: {events}")

        if events.get("gold_found", 0) > 0:
            add_gold(session_id, player_name, events["gold_found"])

        if events.get("item_found"):
            game_state.pending_item = events["item_found"]
            pickup_result = handle_item_pickup(game_state, player_name, session_id, user)
            if pickup_result:
                save_message(session_id, None, "user", pickup_result)

        # ── NPC Extraction ──
        existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
        new_npcs = extract_npcs_from_response(gm_response, recent_messages, existing_npc_names, player_names_list)
        for npc in new_npcs:
            public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
            save_npc(npc["name"], public_data, npc["secret"], session_id)

        npcs_after = get_all_npcs(session_id)
        print(f"\n🔎 NPC Extractor — tur sonrası: {len(npcs_after)} NPC")

        game_state.set_scene(gm_response[:100])
        
        if game_state.is_combat:
            game_state.combat_messages.append({"role": "assistant", "content": gm_response})
        else:
            save_message(session_id, None, "assistant", gm_response)

        # ── Durum göster ──
        print("\n" + "─" * 50)
        for char in game_state.characters:
            print(format_player_status(session_id, char["name"]))
        if game_state.is_combat and game_state.active_encounter:
            print(format_encounter_status(game_state))
        print("─" * 50)

# ─── ANA FONKSİYON ───────────────────────────────────────────────────────────

def main():
    initialize_db()
    ingest()

    user = login_screen()
    if user is None:
        print("Giriş başarısız.")
        return

    print(f"\nHoş geldin {user['username']}! Rol: {user['role']}")

    active = get_active_session()
    if active:
        print(f"\nAktif oturum bulundu: {active['session_name']}")
        choice = input("Devam et? (e/h): ").strip().lower()
        if choice == "e":
            session_id = active["id"]
        else:
            session_name = input("Yeni oturum adı: ").strip()
            session_id = create_session(session_name)
    else:
        session_name = input("Oturum adı: ").strip()
        session_id = create_session(session_name)

    print(f"DEBUG session_id: {session_id}")

    game_state = GameState()
    game_state.session_id = session_id

    load_player_characters(game_state)

    if not game_state.characters:
        print("⚠️  Hiç karakter yüklenmedi, çıkılıyor.")
        return

    print(f"\nDEBUG yüklenen karakterler ({len(game_state.characters)} adet):")
    for c in game_state.characters:
        print(f"   • {c.get('name')} | {c.get('class','?')} | abilities: {c.get('abilities',{})}")

    scenario_manager = select_scenario()

    if scenario_manager:
        print(f"\nDEBUG senaryo: {scenario_manager.meta.get('title','?')}")
        print(f"DEBUG başlangıç node: {scenario_manager.current_node.get('id','?') if scenario_manager.current_node else 'YOK'}")
    else:
        print("\nDEBUG senaryo: YOK (serbest mod)")

    game_loop(user, session_id, game_state, scenario_manager)

    end_session(session_id)
    print("\nGörüşürüz adventurer! ⚔️")

if __name__ == "__main__":
    main()