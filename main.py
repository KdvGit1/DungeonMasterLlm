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
    """
    Oyuncu eylemini RAG örnekleri + küçük AI çağrısıyla analiz eder.
    Döner: {"needed": True, "ability": "charisma", "dc": 12}
         veya {"needed": False}
    """
    print("\n" + "─" * 40)
    print(f"🎯 DEBUG needs_roll_check")
    print(f"   Eylem: '{action}'")

    # RAG'dan zar örneklerini çek
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
                "options": {
                    "num_ctx": 4096,
                    "temperature": 0.1,
                    "num_predict": 50
                }
            }
        )
        result = response.json()
        answer = result["message"]["content"].strip()

        print(f"   AI ham cevap: '{answer}'")

        # Markdown temizle
        answer = re.sub(r'```json|```', '', answer).strip()

        # Sadece JSON kısmını al
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
    """
    needs_roll_check'ten gelen roll_info'ya göre zar atar.
    Sonucu ekrana yazar, DB'ye kaydeder, GM'e gidecek string döner.
    """
    ability = roll_info["ability"]
    dc = roll_info["dc"]

    # Kısaltma normalize et (dex→dexterity, str→strength vb.)
    ability_map = {
        "dex": "dexterity", "str": "strength", "con": "constitution",
        "wis": "wisdom", "int": "intelligence", "cha": "charisma"
    }
    ability = ability_map.get(ability, ability)

    print(f"\nDEBUG execute_roll: ability={ability}, dc={dc}")

    # karakterden ability score çek
    char = game_state.characters[0]
    abilities = char.get("abilities", {})
    score = abilities.get(ability, 10)
    modifier = get_modifier(score)

    print(f"DEBUG execute_roll: karakter={char.get('name')}, score={score}, modifier={modifier}")

    # zar at
    roll_result = d20()
    total = roll_result + modifier

    # ekrana yaz
    print("\n" + "─" * 50)
    print(f"🎲 {ability.capitalize()} check vs DC {dc}")
    print(f"   Zar: {roll_result} | Modifier: {modifier:+d} | Toplam: {total} | DC: {dc}")

    if roll_result == 20:
        outcome_label = "CRITICAL SUCCESS"
        print("   ⭐ KRİTİK BAŞARI!")
    elif roll_result == 1:
        outcome_label = "CRITICAL FAILURE"
        print("   💀 KRİTİK BAŞARISIZLIK!")
    elif total >= dc:
        outcome_label = "SUCCESS"
        print("   ✅ BAŞARILI")
    else:
        outcome_label = "FAILURE"
        print("   ❌ BAŞARISIZ")

    # GM'e gidecek özet
    roll_message = (
        f"Player: {player_name}\n"
        f"Action required: {ability} check vs DC {dc}\n"
        f"Roll: {roll_result} + {modifier} (modifier) = {total}\n"
        f"Result: {outcome_label}"
    )

    # DB'ye kaydet
    db_message = (
        f"{player_name} rolled {ability}: "
        f"{roll_result} + {modifier} = {total} vs DC {dc} ({outcome_label})"
    )
    save_message(session_id, user.get("id"), "user", db_message)

    print(f"\nDEBUG execute_roll → GM'e gidecek mesaj:\n{roll_message}")

    return roll_message

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
                print("⚠️  Bir şey girmedin, tekrar dene.")
                continue

            if selected.isdigit():
                idx = int(selected) - 1
                if 0 <= idx < len(files):
                    selected = files[idx]
                else:
                    print("⚠️  Geçersiz numara, tekrar dene.")
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
                print("⚠️  Karakter yüklenemedi, tekrar dene.")
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
        print("⚠️  Geçersiz seçim, tekrar dene.")

    try:
        sm = ScenarioManager(chosen["path"])
        sm.start()
        print(f"✅ Senaryo yüklendi: {chosen['title']}")
        return sm
    except Exception as e:
        print(f"⚠️  Senaryo yüklenirken hata: {e}")
        return None

# ─── ANA OYUN DÖNGÜSÜ ────────────────────────────────────────────────────────

def game_loop(user, session_id, game_state, scenario_manager):
    print("\n🎲 Macera başlıyor...\n")
    print("─" * 50)

    valid_names = [c['name'].lower() for c in game_state.characters]
    names_display = ", ".join([c['name'] for c in game_state.characters])
    player_names_list = [c['name'] for c in game_state.characters]

    # Başlangıç mesajı
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
            "Set the scene in English. Maximum 3 sentences. "
            "Describe where they are and end with an open situation."
        )

    system_prompt = build_system_prompt(
        game_state.characters, "begin adventure exploration",
        game_state, scenario_manager, session_id=session_id
    )

    # ── DEBUG: system prompt tam içerik ──
    print("\n" + "═" * 50)
    print("🔍 DEBUG — SYSTEM PROMPT (ilk 800 karakter)")
    print("═" * 50)
    print(system_prompt[:800])
    print("═" * 50 + "\n")

    # ── DEBUG: NPC durumu (başlangıç) ──
    npcs = get_all_npcs(session_id)
    print(f"🔍 DEBUG — BAŞLANGIÇ NPC'LERİ ({len(npcs)} adet):")
    if npcs:
        for npc in npcs:
            print(f"   • {npc['name']} | {npc['public'].get('role','?')} | SECRET: {str(npc['secret'])[:60]}")
    else:
        print("   (henüz NPC yok)")
    print()

    print("⏳ GM başlangıç sahnesini hazırlıyor...\n")
    gm_intro = ask_gm(
        [{"role": "user", "content": intro_message}],
        system_prompt
    )

    # ── NPC Extraction (intro) ──
    existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
    new_npcs = extract_npcs_from_response(gm_intro, [{"role": "assistant", "content": gm_intro}], existing_npc_names, player_names_list)
    for npc in new_npcs:
        public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
        save_npc(npc["name"], public_data, npc["secret"], session_id)

    npcs_after = get_all_npcs(session_id)
    print(f"\n🔎 NPC Extractor — intro sonrası NPC sayısı: {len(npcs_after)}")
    for npc in npcs_after:
        print(f"   • {npc['name']} | {npc['public'].get('role','?')} | SECRET: {str(npc['secret'])[:50]}")

    game_state.set_scene(gm_intro[:100])
    if scenario_manager and scenario_manager.current_node:
        game_state.current_node = scenario_manager.current_node.get("title", "")

    print("\n" + "─" * 50)

    save_message(session_id, None, "user", intro_message)
    save_message(session_id, None, "assistant", gm_intro)

    while True:

        # ── Karakter adı kontrolü ──
        while True:
            print(f"\nAktif karakterler: {names_display}")
            player_name = input("Karakter adı (veya 'quit'): ").strip()

            if player_name.lower() == "quit":
                return

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

        user_message = f"{player_name}: {action}"
        save_message(session_id, user.get("id"), "user", user_message)

        # ════════════════════════════════════════════════════
        # ADIM 1: TRIGGER CHECK — sahne değişti mi?
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("📍 ADIM 1 — TRIGGER CHECK")
        print("═" * 50)

        if scenario_manager:
            current_id = scenario_manager.current_node.get('id', '?') if scenario_manager.current_node else '?'
            current_title = scenario_manager.current_node.get('title', '?') if scenario_manager.current_node else '?'
            print(f"   Mevcut node: {current_id} — {current_title}")

            recent_for_trigger = get_recent_messages(session_id)
            print(f"   Trigger için son {len(recent_for_trigger)} mesaj kullanılıyor")

            next_node = scenario_manager.check_trigger(recent_for_trigger)
            print(f"   Trigger sonucu: {next_node if next_node else 'YOK — sahne değişmedi'}")

            if next_node:
                print(f"   🚀 Sahne geçişi: {current_id} → {next_node}")
                scenario_manager.load_node(next_node)
                if scenario_manager.current_node:
                    game_state.current_node = scenario_manager.current_node.get("title", "")
                transition_msg = (
                    f"[SCENE TRANSITION: players have arrived at "
                    f"{scenario_manager.current_node.get('title', next_node)}]"
                )
                save_message(session_id, None, "user", transition_msg)
                print(f"   Yeni node yüklendi: {scenario_manager.current_node.get('id','?')} — {scenario_manager.current_node.get('title','?')}")
        else:
            print("   Senaryo yok — trigger atlandı")

        # ════════════════════════════════════════════════════
        # ADIM 2: ROLL CHECK — zar gerekli mi?
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🎲 ADIM 2 — ROLL CHECK")
        print("═" * 50)

        node_actions = None
        if scenario_manager and scenario_manager.current_node:
            node_actions = scenario_manager.current_node.get("available_actions")
            print(f"   Node available_actions: {'mevcut' if node_actions else 'YOK'}")
            if node_actions:
                print(f"   {str(node_actions)[:200]}")
        else:
            print("   Node yok — available_actions kullanılamıyor")

        roll_info = needs_roll_check(action, node_actions)

        roll_result_msg = None
        if roll_info.get("needed"):
            roll_result_msg = execute_roll(roll_info, player_name, game_state, session_id, user)
        else:
            print("   ⏭️  Zar atılmadı")

        # ════════════════════════════════════════════════════
        # ADIM 3: GM CEVABI
        # ════════════════════════════════════════════════════
        print("\n" + "═" * 50)
        print("🧙 ADIM 3 — GM CEVABI")
        print("═" * 50)

        recent_messages = get_recent_messages(session_id)

        print(f"   Mesaj geçmişi ({len(recent_messages)} mesaj):")
        for m in recent_messages:
            icon = "👤" if m['role'] == 'user' else "🧙"
            print(f"     {icon} [{m['role']}]: {m['content'][:70]}")

        # ── DEBUG: NPC'ler ──
        npcs_now = get_all_npcs(session_id)
        print(f"\n   Mevcut NPC'ler ({len(npcs_now)} adet):")
        if npcs_now:
            for npc in npcs_now:
                print(f"     • {npc['name']} | {npc['public'].get('role','?')} | SECRET: {str(npc['secret'])[:50]}")
        else:
            print("     (henüz NPC yok)")

        system_prompt = build_system_prompt(
            game_state.characters, action,
            game_state, scenario_manager,
            roll_info=roll_result_msg, session_id=session_id
        )

        print(f"\n   System prompt uzunluğu: {len(system_prompt)} karakter")
        print(f"   Roll bilgisi GM'e gitti mi: {'EVET' if roll_result_msg else 'HAYIR'}")
        if roll_result_msg:
            print(f"   Roll özeti: {roll_result_msg[:100]}")
        if scenario_manager and scenario_manager.current_node:
            print(f"   Aktif node: {scenario_manager.current_node.get('id','?')} — {scenario_manager.current_node.get('title','?')}")

        print("\n" + "─" * 50)
        print("⏳ GM düşünüyor...\n")
        gm_response = ask_gm(recent_messages, system_prompt)

        # ── NPC Extraction ──
        existing_npc_names = [n['name'] for n in get_all_npcs(session_id)]
        new_npcs = extract_npcs_from_response(gm_response, recent_messages, existing_npc_names, player_names_list)
        for npc in new_npcs:
            public_data = {"role": npc["role"], "appearance": npc["appearance"], "personality": npc["personality"]}
            save_npc(npc["name"], public_data, npc["secret"], session_id)

        npcs_after_turn = get_all_npcs(session_id)
        print(f"\n🔎 NPC Extractor — tur sonrası NPC sayısı: {len(npcs_after_turn)}")
        for npc in npcs_after_turn:
            print(f"   • {npc['name']} | {npc['public'].get('role','?')} | SECRET: {str(npc['secret'])[:50]}")

        game_state.set_scene(gm_response[:100])
        print(f"\nDEBUG game_state.current_scene güncellendi: '{gm_response[:80]}'")

        print("\n" + "─" * 50)
        save_message(session_id, None, "assistant", gm_response)
        print("DEBUG mesaj DB'ye kaydedildi ✅")

# ─── ANA FONKSİYON ───────────────────────────────────────────────────────────

def main():
    initialize_db()
    ingest()

    user = login_screen()
    if user is None:
        print("Giriş başarısız.")
        return

    print(f"\nHoş geldin {user['username']}! Rol: {user['role']}")

    # ── Oturum ──
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

    # ── Oyun durumu ──
    game_state = GameState()
    game_state.session_id = session_id

    # ── Karakter yükle ──
    load_player_characters(game_state)

    if not game_state.characters:
        print("⚠️  Hiç karakter yüklenmedi, çıkılıyor.")
        return

    print(f"\nDEBUG yüklenen karakterler ({len(game_state.characters)} adet):")
    for c in game_state.characters:
        print(f"   • {c.get('name')} | {c.get('class','?')} | abilities: {c.get('abilities',{})}")

    # ── Senaryo seç ──
    scenario_manager = select_scenario()

    if scenario_manager:
        print(f"\nDEBUG senaryo: {scenario_manager.meta.get('title','?')}")
        print(f"DEBUG başlangıç node: {scenario_manager.current_node.get('id','?') if scenario_manager.current_node else 'YOK'}")
    else:
        print("\nDEBUG senaryo: YOK (serbest mod)")

    # ── Oyunu başlat ──
    game_loop(user, session_id, game_state, scenario_manager)

    end_session(session_id)
    print("\nGörüşürüz adventurer! ⚔️")

if __name__ == "__main__":
    main()