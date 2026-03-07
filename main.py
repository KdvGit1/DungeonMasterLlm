import os
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
from game.dice import ability_check
from prompts.system_prompt import build_system_prompt
from rag.ingest import ingest
from game.character_creator import create_character
import requests
import config

# ─── OLLAMA'YA İSTEK GÖNDER ────────────────────────────────

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
    full_thinking = ""
    prompt_tokens = 0
    response_tokens = 0
    first_chunk_time = None
    thinking_started = False

    for line in response.iter_lines():
        if not line:
            continue

        chunk = json.loads(line)

        if first_chunk_time is None:
            first_chunk_time = time.time() - start

        message = chunk.get("message", {})
        thinking = message.get("thinking", "")
        content = message.get("content", "")

        # thinking ayrı field'dan geliyor
        if thinking:
            if not thinking_started:
                print("\n💭 Thinking: ", end="", flush=True)
                thinking_started = True
            print(thinking, end="", flush=True)
            full_thinking += thinking

        # asıl cevap
        if content:
            if thinking_started and not full_response:
                # thinking bitti, cevap başlıyor
                print("\n\n🧙 GM: ", end="", flush=True)
            print(content, end="", flush=True)
            full_response += content

        if chunk.get("done"):
            prompt_tokens = chunk.get("prompt_eval_count", "?")
            response_tokens = chunk.get("eval_count", "?")

    elapsed = time.time() - start
    print(f"\n\n⏱️  Toplam : {elapsed:.2f}s  |  İlk token: {first_chunk_time:.2f}s")
    print(f"📊 Prompt : {prompt_tokens} token  |  Cevap: {response_tokens} token")

    return full_response

# ─── GİRİŞ EKRANI ──────────────────────────────────────────

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

# ─── KARAKTER YÜKLE ────────────────────────────────────────

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

# ─── ANA OYUN DÖNGÜSÜ ──────────────────────────────────────

def game_loop(user, session_id, game_state):
    print("\n🎲 Macera başlıyor...\n")
    print("─" * 50)

    valid_names = [c['name'].lower() for c in game_state.characters]
    names_display = ", ".join([c['name'] for c in game_state.characters])

    # intro system prompt'a gömülü, mesaj geçmişine kaydedilmiyor
    intro_message = "Begin the adventure. Set the opening scene."

    system_prompt = build_system_prompt(
        game_state.characters, intro_message, game_state
    )

    print("⏳ GM sahneyi hazırlıyor...\n")
    gm_intro = ask_gm(
        [{"role": "user", "content": intro_message}],
        system_prompt
    )
    print("\n" + "─" * 50)

    # intro'yu kaydet ama kısa tut
    save_message(session_id, None, "user", intro_message)
    save_message(session_id, None, "assistant", gm_intro)

    while True:
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

        action = input(f"{player_name} ne yapıyor? > ").strip()
        if not action:
            print("⚠️  Eylem boş olamaz.")
            continue
        if action.lower() == "quit":
            return

        user_message = f"{player_name}: {action}"
        save_message(session_id, user.get("id"), "user", user_message)

        recent_messages = get_recent_messages(session_id)
        system_prompt = build_system_prompt(
            game_state.characters, action, game_state
        )

        print("\n⏳ GM düşünüyor...\n")
        gm_response = ask_gm(recent_messages, system_prompt)

        if "ROLL" in gm_response.upper():
            print("\n" + "─" * 50)
            print("🎲 Zar atma zamanı!")
            try:
                roll_input = int(input("Zarını at (1-20): ").strip())
                modifier = int(input("Modifier (bilmiyorsan 0): ").strip())
                total = roll_input + modifier
                print(f"Toplam: {roll_input} + {modifier} = {total}")
                roll_message = f"{player_name} rolled: {roll_input} + {modifier} = {total}"
                save_message(session_id, user.get("id"), "user", roll_message)
                recent_messages = get_recent_messages(session_id)
                print("\n⏳ GM sonucu değerlendiriyor...\n")
                gm_response = ask_gm(recent_messages, system_prompt)
            except ValueError:
                print("⚠️  Geçersiz sayı.")

        print("\n" + "─" * 50)
        save_message(session_id, None, "assistant", gm_response)

# ─── ANA FONKSİYON ─────────────────────────────────────────

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

    # ── Oyunu başlat ──
    game_loop(user, session_id, game_state)

    end_session(session_id)
    print("\nGörüşürüz adventurer! ⚔️")

if __name__ == "__main__":
    main()