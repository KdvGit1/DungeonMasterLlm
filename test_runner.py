"""
test_runner.py — AI Destekli Otomatik Oyun Testi

Çalıştırma:
    python test_runner.py

Yapılandırma (aşağıdaki TEST_CONFIG):
    - max_turns      : kaç tur oynanacak
    - scenario_name  : hangi senaryo klasörü (scenarios/ altında)
    - character_file : hangi karakter dosyası (data/characters/ altında)
    - player_name    : karakterin adı
    - player_persona : Player AI'ın nasıl oynaması gerektiği
"""

import sys
import os
import re
import time
import json
import builtins
import datetime
import requests
from io import StringIO

# ─── TEST YAPILANDIRMASI ──────────────────────────────────────────────────────

TEST_CONFIG = {
    "max_turns": 10,
    "scenario_name": "Shadow Over Millhaven",   # scenarios/ altındaki klasör adı
    "character_file": "kdv.yaml",                # data/characters/ altında
    "player_name": "kdv",
    "username": "kdv",                           # gerçek kullanıcı adı
    "password": "2002",                          # gerçek şifre
    "player_persona": (
        "You are an adventurous and curious D&D player. "
        "Your goal is always to PROGRESS the story forward — explore new locations, "
        "talk to NPCs to uncover information, and investigate anything suspicious. "
        "IMPORTANT: Do not stay in the same location more than 2 turns in a row. "
        "If nothing interesting is happening, move to a new place mentioned by the GM. "
        "Occasionally attempt uncertain actions: persuade, deceive, sneak, search, investigate. "
        "Keep your actions short (1-2 sentences). "
        "Do NOT repeat what the GM just said. Just state what you do next."
    )
}

# ─── LOG KURULUMU ─────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_path = f"logs/test_{timestamp}.txt"

class TeeOutput:
    """stdout'u hem terminale hem log dosyasına yazar."""
    def __init__(self, file):
        self.terminal = sys.__stdout__
        self.file = file

    def write(self, message):
        self.terminal.write(message)
        self.file.write(message)
        self.file.flush()

    def flush(self):
        self.terminal.flush()
        self.file.flush()

    def isatty(self):
        return False

log_file = open(log_path, "w", encoding="utf-8")
sys.stdout = TeeOutput(log_file)

print(f"{'='*60}")
print(f"🤖 DnD GM — OTOMATİK TEST")
print(f"   Tarih   : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"   Log     : {log_path}")
print(f"   Tur     : {TEST_CONFIG['max_turns']}")
print(f"   Senaryo : {TEST_CONFIG['scenario_name']}")
print(f"   Karakter: {TEST_CONFIG['player_name']}")
print(f"{'='*60}\n")

# ─── PLAYER AI ────────────────────────────────────────────────────────────────

import config

class PlayerAI:
    """
    GM cevaplarını takip eder, gerçek oyuncu gibi aksiyonlar üretir.
    """
    def __init__(self, persona, player_name):
        self.persona = persona
        self.player_name = player_name
        self.history = []          # GM - Player konuşma geçmişi
        self.turn_count = 0

    def add_gm_response(self, gm_text):
        """GM cevabını geçmişe ekle."""
        self.history.append({"role": "assistant", "content": f"GM: {gm_text}"})

    def decide_action(self):
        """Bir sonraki aksiyonu üret."""
        self.turn_count += 1

        # Son 6 mesajı al (context kısa tutulsun)
        recent = self.history[-6:] if len(self.history) > 6 else self.history

        prompt = (
            f"You are playing a D&D character named {self.player_name}. "
            f"{self.persona}\n\n"
            f"Conversation so far:\n"
        )
        for msg in recent:
            prompt += f"{msg['content']}\n"
        prompt += (
            f"\nWhat does {self.player_name} do next? "
            f"Write ONLY the action, no preamble, no 'I would...', just the action itself. "
            f"Example: 'I search the room for hidden compartments.' "
            f"or 'I try to persuade the guard by showing my medallion.'"
        )

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
                        "temperature": 0.8,
                        "num_predict": 80
                    }
                }
            )
            result = response.json()
            action = result["message"]["content"].strip()

            # Prefix temizle
            action = re.sub(r'^(I would |Action: |Player: )', '', action, flags=re.IGNORECASE)
            action = action.split('\n')[0].strip()  # sadece ilk satır

            self.history.append({"role": "user", "content": f"{self.player_name}: {action}"})
            return action

        except Exception as e:
            print(f"\n⚠️  PlayerAI hata: {e}")
            fallback = "I look around carefully and examine my surroundings."
            self.history.append({"role": "user", "content": f"{self.player_name}: {fallback}"})
            return fallback

# ─── INPUT MOCK ───────────────────────────────────────────────────────────────

player_ai = PlayerAI(TEST_CONFIG["player_persona"], TEST_CONFIG["player_name"])

# Setup aşaması için sabit cevaplar sırası
# Aktif oturum varsa "h" → yeni oturum açar, yoksa direkt oturum adı sorar.
# Her iki durumu da karşılayacak şekilde fazladan cevap eklendi (kullanılmayan atlanır).
# Aktif oturum varsa "Devam et? (e/h)" sorusu gelir → "h" → yeni oturum adı
# Aktif oturum yoksa direkt "Oturum adı" sorusu gelir
# Her iki durumu karşılamak için fazla cevap eklendi, sırayla tükenir
_setup_responses = [
    "1",                                      # login seçimi → giriş yap
    TEST_CONFIG["username"],                   # kullanıcı adı
    TEST_CONFIG["password"],                   # şifre
    "h",                                      # aktif oturum varsa → yeni oturum aç
    f"test_{timestamp}",                      # oturum adı (aktif oturum varsa yeni ad, yoksa ilk soruya cevap)
    f"test_{timestamp}",                      # oturum adı (aktif oturum yoksa bu kullanılır)
    "2",                                      # karakter → mevcut yükle
    "1",                                      # ilk karakter dosyası
    "h",                                      # başka karakter → hayır
    "e",                                      # senaryo → evet
    "1",                                      # ilk senaryo
]
_setup_index = 0
_game_started = False
_last_gm_response = ""
_turn_counter = 0
_original_input = builtins.input

def mock_input(prompt=""):
    global _setup_index, _game_started, _last_gm_response, _turn_counter

    print(f"\n[INPUT MOCK] Prompt: '{prompt}'")

    # ── Setup aşaması ──
    if _setup_index < len(_setup_responses):
        answer = _setup_responses[_setup_index]
        _setup_index += 1
        print(f"[INPUT MOCK] Setup cevabı: '{answer}'")
        return answer

    # ── Oyun aşaması ──
    # Karakter adı sorusu
    if "Karakter adı" in prompt or "karakter" in prompt.lower():
        if "quit" in prompt.lower():
            # Tur limitine ulaşıldıysa çık
            if _turn_counter >= TEST_CONFIG["max_turns"]:
                print(f"\n[INPUT MOCK] Tur limiti ({TEST_CONFIG['max_turns']}) doldu → quit")
                return "quit"
        print(f"[INPUT MOCK] Karakter adı: '{TEST_CONFIG['player_name']}'")
        return TEST_CONFIG["player_name"]

    # Eylem sorusu
    if "ne yapıyor" in prompt or "yapıyor?" in prompt:
        _turn_counter += 1

        if _turn_counter > TEST_CONFIG["max_turns"]:
            print(f"\n[INPUT MOCK] Tur limiti doldu → quit")
            return "quit"

        print(f"\n[INPUT MOCK] Tur {_turn_counter}/{TEST_CONFIG['max_turns']} — PlayerAI karar veriyor...")
        action = player_ai.decide_action()
        print(f"[INPUT MOCK] PlayerAI aksiyonu: '{action}'")
        return action

    # Diğer beklenmedik sorular — boş geç
    print(f"[INPUT MOCK] Tanımsız soru, boş geçiliyor")
    return ""

builtins.input = mock_input

# ─── GM CEVAPLARINI YAKALA ────────────────────────────────────────────────────
# ask_gm'i wrap'le: her GM cevabını PlayerAI'a ilet

_original_ask_gm = None  # main import sonrası set edilecek

# ─── İSTATİSTİK TAKIBI ───────────────────────────────────────────────────────

stats = {
    "turns": 0,
    "rolls_triggered": 0,
    "rolls_success": 0,
    "rolls_failure": 0,
    "rolls_critical": 0,
    "npcs_created": [],
    "nodes_visited": [],
    "scene_transitions": 0,
    "total_gm_tokens": 0,
    "total_time_start": time.time(),
    "roll_details": [],
    "node_history": [],
    "gm_responses": [],
    "player_actions": [],
}

# ─── MAIN'İ PATCH'LE VE ÇALIŞTIR ─────────────────────────────────────────────

# main modülünü import et
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Önce orijinal fonksiyonları kaydet, sonra istatistik toplayan wrapper'lar ekle
import main as game_main
import game.npc_manager as npc_mod
import game.scenario_manager as scenario_mod

# ask_gm wrapper — GM cevabını PlayerAI'a ilet + istatistik topla
_orig_ask_gm = game_main.ask_gm

def wrapped_ask_gm(messages, system_prompt):
    result = _orig_ask_gm(messages, system_prompt)

    # PlayerAI'a ilet
    player_ai.add_gm_response(result)

    # İstatistik
    stats["gm_responses"].append(result[:120])

    return result

game_main.ask_gm = wrapped_ask_gm

# execute_roll wrapper — zar istatistikleri
_orig_execute_roll = game_main.execute_roll

def wrapped_execute_roll(roll_info, player_name, game_state, session_id, user):
    result = _orig_execute_roll(roll_info, player_name, game_state, session_id, user)

    stats["rolls_triggered"] += 1
    if "CRITICAL SUCCESS" in result:
        stats["rolls_critical"] += 1
        stats["rolls_success"] += 1
    elif "CRITICAL FAILURE" in result:
        stats["rolls_critical"] += 1
        stats["rolls_failure"] += 1
    elif "SUCCESS" in result:
        stats["rolls_success"] += 1
    else:
        stats["rolls_failure"] += 1

    stats["roll_details"].append(result.replace('\n', ' | '))
    return result

game_main.execute_roll = wrapped_execute_roll

# load_node wrapper — node geçiş istatistikleri
_orig_load_node = scenario_mod.ScenarioManager.load_node

def wrapped_load_node(self, node_id):
    result = _orig_load_node(self, node_id)
    node_title = self.current_node.get("title", node_id) if self.current_node else node_id
    stats["nodes_visited"].append(node_id)
    stats["node_history"].append(f"{node_id} — {node_title}")
    stats["scene_transitions"] += 1
    return result

scenario_mod.ScenarioManager.load_node = wrapped_load_node

# ─── OYUNU BAŞLAT ─────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("🚀 OYUN BAŞLIYOR")
print("="*60 + "\n")

try:
    game_main.main()
except SystemExit:
    pass
except KeyboardInterrupt:
    print("\n\n⚠️  Test kullanıcı tarafından durduruldu.")
except Exception as e:
    import traceback
    print(f"\n\n❌ BEKLENMEYEN HATA: {e}")
    traceback.print_exc()

# ─── ÖZET RAPOR ───────────────────────────────────────────────────────────────

total_time = time.time() - stats["total_time_start"]

# NPC sayısını DB'den al (son aktif oturumun NPC'leri)
try:
    from game.npc_manager import get_all_npcs
    from db.session_manager import get_active_session
    active = get_active_session()
    sid = active["id"] if active else None
    final_npcs = get_all_npcs(sid) if sid else []
    npc_list = [(n["name"], n["public"].get("role", "?")) for n in final_npcs]
except:
    npc_list = []

print("\n\n" + "═"*60)
print("📊 TEST ÖZET RAPORU")
print("═"*60)
print(f"  Toplam süre        : {total_time:.1f}s ({total_time/60:.1f} dakika)")
print(f"  Oynanan tur        : {_turn_counter}")
print(f"  Sahne geçişi       : {stats['scene_transitions']}")
print(f"  Zar atılan eylem   : {stats['rolls_triggered']}")
print(f"  → Başarı           : {stats['rolls_success']}")
print(f"  → Başarısızlık     : {stats['rolls_failure']}")
print(f"  → Kritik           : {stats['rolls_critical']}")
print(f"  Yaratılan NPC      : {len(npc_list)}")

if npc_list:
    print(f"\n  NPC Listesi:")
    for name, role in npc_list:
        print(f"    • {name} ({role})")

if stats["node_history"]:
    print(f"\n  Ziyaret edilen node'lar ({len(stats['node_history'])} geçiş):")
    for n in stats["node_history"]:
        print(f"    → {n}")

if stats["roll_details"]:
    print(f"\n  Zar detayları:")
    for r in stats["roll_details"]:
        print(f"    🎲 {r}")

print(f"\n  Log dosyası: {log_path}")
print("═"*60)

# Log dosyasını kapat
sys.stdout = sys.__stdout__
log_file.close()

print(f"\n✅ Test tamamlandı. Log: {log_path}")