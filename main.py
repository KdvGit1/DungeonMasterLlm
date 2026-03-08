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
from game.npc_manager import parse_and_save_npcs
from game.scenario_manager import ScenarioManager
from prompts.system_prompt import build_system_prompt
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

# ─── ZAR AT ──────────────────────────────────────────────────────────────────

def handle_roll(gm_response, player_name, game_state, session_id, user):
    """
    GM cevabından 'ROLL d20 + [ability] vs DC [number]' parse eder,
    dice.py ile otomatik atar, sonucu DB'ye kaydeder.
    """
    pattern = r'ROLL\s+d20\s*\+\s*(\w+)\s+vs\s+DC\s+(\d+)'
    match = re.search(pattern, gm_response, re.IGNORECASE)

    if not match:
        print("DEBUG handle_roll: ROLL bulundu ama format eşleşmedi.")
        print(f"DEBUG gm_response snippet: {gm_response[:200]}")
        return None

    ability = match.group(1).lower()
    dc = int(match.group(2))

    print(f"DEBUG handle_roll: ability={ability}, dc={dc}")

    # karakterden ability score çek
    char = game_state.characters[0]
    abilities = char.get("abilities", {})
    score = abilities.get(ability, 10)
    modifier = get_modifier(score)

    print(f"DEBUG handle_roll: score={score}, modifier={modifier}")

    # zar at
    roll_result = d20()
    total = roll_result + modifier

    # sonucu ekrana yaz
    print("\n" + "─" * 50)
    print(f"🎲 {ability.capitalize()} check vs DC {dc}")
    print(f"   Zar: {roll_result} | Modifier: {modifier:+d} | Toplam: {total} | DC: {dc}")

    if roll_result == 20:
        print("   ⭐ KRİTİK BAŞARI!")
    elif roll_result == 1:
        print("   💀 KRİTİK BAŞARISIZLIK!")
    elif total >= dc:
        print("   ✅ BAŞARILI")
    else:
        print("   ❌ BAŞARISIZ")

    outcome = "SUCCESS" if total >= dc else "FAIL"
    roll_message = (
        f"{player_name} rolled {ability}: "
        f"{roll_result} + {modifier} = {total} vs DC {dc} ({outcome})"
    )
    save_message(session_id, user.get("id"), "user", roll_message)
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
    """
    Kullanıcıya senaryo takip etmek isteyip istemediğini sorar.
    Evet → scenarios/ klasöründeki senaryoları tarar, seçtirip ScenarioManager döner.
    Hayır → None döner (serbest mod).
    """
    print("\n📖 SENARYO")
    print("─" * 30)
    choice = input("Bir senaryo takip etmek istiyor musun? (e/h): ").strip().lower()

    if choice != "e":
        print("ℹ️  Serbest mod — hayal gücüne bırakıldı.")
        return None

    # scenarios/ klasörünü tara
    scenarios_root = "scenarios"
    if not os.path.exists(scenarios_root):
        print("⚠️  'scenarios/' klasörü bulunamadı, serbest mod.")
        return None

    # Her alt klasörde scenario.yaml arayalım
    found = []
    for entry in sorted(os.listdir(scenarios_root)):
        entry_path = os.path.join(scenarios_root, entry)
        meta_path = os.path.join(entry_path, "scenario.yaml")
        if os.path.isdir(entry_path) and os.path.exists(meta_path):
            # Başlığı meta'dan çek
            try:
                import yaml
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = yaml.safe_load(f)
                title = meta.get("title", entry)
                description = meta.get("description", "")
            except Exception:
                title = entry
                description = ""
            found.append({
                "path": entry_path,
                "title": title,
                "description": description
            })

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

    # Senaryo başlangıç mesajı
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
        game_state, scenario_manager
    )

    # ── DEBUG: system prompt önizleme ──
    print("\n" + "═" * 50)
    print("🔍 DEBUG — SYSTEM PROMPT (ilk 600 karakter)")
    print("═" * 50)
    print(system_prompt[:600])
    print("═" * 50 + "\n")

    print("⏳ GM başlangıç sahnesini hazırlıyor...\n")
    gm_intro = ask_gm(
        [{"role": "user", "content": intro_message}],
        system_prompt
    )
    gm_intro = parse_and_save_npcs(gm_intro)
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

        recent_messages = get_recent_messages(session_id)

        # ── DEBUG: mesaj geçmişi ──
        print(f"\nDEBUG mesaj geçmişi ({len(recent_messages)} mesaj):")
        for m in recent_messages:
            icon = "👤" if m['role'] == 'user' else "🧙"
            print(f"  {icon} [{m['role']}]: {m['content'][:70]}")

        system_prompt = build_system_prompt(
            game_state.characters, action,
            game_state, scenario_manager
        )

        # ── DEBUG: kaç token gönderileceğini tahmin et ──
        print(f"\nDEBUG system_prompt uzunluğu: {len(system_prompt)} karakter")
        if scenario_manager and scenario_manager.current_node:
            print(f"DEBUG aktif node: {scenario_manager.current_node.get('id', '?')} — {scenario_manager.current_node.get('title', '?')}")

        print("\n⏳ GM düşünüyor...\n")
        gm_response = ask_gm(recent_messages, system_prompt)
        gm_response = parse_and_save_npcs(gm_response)
        game_state.set_scene(gm_response[:100])

        # ── Zar gerekli mi? ──
        if "ROLL" in gm_response.upper():
            roll_result = handle_roll(
                gm_response, player_name, game_state, session_id, user
            )
            if roll_result:
                recent_messages = get_recent_messages(session_id)
                print("\n⏳ GM sonucu değerlendiriyor...\n")
                gm_response = ask_gm(recent_messages, system_prompt)
                gm_response = parse_and_save_npcs(gm_response)
                game_state.set_scene(gm_response[:100])

        print("\n" + "─" * 50)
        save_message(session_id, None, "assistant", gm_response)

        # ── Senaryo trigger kontrolü ──
        if scenario_manager:
            recent_messages = get_recent_messages(session_id)
            print(f"\nDEBUG trigger kontrolü başlıyor... (node: {scenario_manager.current_node.get('id', '?')})")
            next_node = scenario_manager.check_trigger(recent_messages)
            print(f"DEBUG trigger sonucu: {next_node}")
            if next_node:
                scenario_manager.load_node(next_node)
                if scenario_manager.current_node:
                    game_state.current_node = scenario_manager.current_node.get("title", "")
                transition_msg = (
                    f"[SCENE TRANSITION: players have arrived at "
                    f"{scenario_manager.current_node.get('title', next_node)}]"
                )
                save_message(session_id, None, "user", transition_msg)

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

    # ── Oyun durumu ──
    game_state = GameState()
    game_state.session_id = session_id

    # ── Karakter yükle ──
    load_player_characters(game_state)

    if not game_state.characters:
        print("⚠️  Hiç karakter yüklenmedi, çıkılıyor.")
        return

    # ── Senaryo seç ──
    scenario_manager = select_scenario()

    # ── Oyunu başlat ──
    game_loop(user, session_id, game_state, scenario_manager)

    end_session(session_id)
    print("\nGörüşürüz adventurer! ⚔️")

if __name__ == "__main__":
    main()