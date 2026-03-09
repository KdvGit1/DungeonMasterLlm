"""
npc_extractor.py — AI-Based NPC Extraction Layer

Her GM cevabından sonra çalışır:
1. Cevaptaki yeni isimli NPC'leri tespit eder
2. Her NPC için tam bilgi üretir (isim, rol, görünüm, kişilik, sır)
3. Bilgileri döner, main.py bunları DB'ye kaydeder
"""

import json
import re
import requests
import config


def extract_npcs_from_response(gm_response, recent_messages, existing_npc_names, player_names):
    """
    GM cevabını analiz edip yeni NPC'leri çıkarır.

    Args:
        gm_response: GM'in son cevabı
        recent_messages: Son birkaç mesaj (konuşma bağlamı)
        existing_npc_names: DB'deki mevcut NPC isimleri (tekrar eklenmesin diye)
        player_names: Oyuncu karakter isimleri (NPC olarak algılanmasın diye)

    Returns:
        List of dicts: [{"name": ..., "role": ..., "appearance": ..., "personality": ..., "secret": ...}]
    """

    # Bağlam için son mesajları string'e çevir
    context_lines = []
    for msg in recent_messages[-6:]:
        context_lines.append(f"{msg['role'].upper()}: {msg['content']}")
    conversation_context = "\n".join(context_lines)

    # Zaten bilinen isimleri filtre listesi yap
    known_names = list(set(
        [n.lower() for n in existing_npc_names] +
        [n.lower() for n in player_names]
    ))
    known_names_str = ", ".join(known_names) if known_names else "none"

    prompt = f"""You are analyzing a D&D Game Master's response to identify NEW named NPCs.

GM'S LATEST RESPONSE:
\"\"\"{gm_response}\"\"\"

RECENT CONVERSATION FOR CONTEXT:
{conversation_context}

ALREADY KNOWN NAMES (do NOT include these): {known_names_str}

TASK:
1. Find any NEW named NPCs in the GM's latest response (characters with proper names like "Garret", "Old Silas", "Borin")
2. Do NOT include unnamed references like "a merchant", "the guards", "creatures", "the bartender"
3. Do NOT include player characters or already known names listed above
4. For each new NPC, generate ALL of these fields based on what the GM described and the conversation context:
   - name: their proper name
   - role: their function (e.g. "Gate Guard", "Innkeeper", "Traveling Merchant")
   - appearance: physical description (invent realistic details if GM didn't describe them fully)
   - personality: behavioral traits (invent realistic traits if GM didn't describe them fully)
   - secret: something this NPC is actively hiding from the players (MANDATORY — every NPC must have a secret relevant to the story context)

Respond with ONLY valid JSON. No explanation, no markdown.
If there are new NPCs: [{{"name":"...","role":"...","appearance":"...","personality":"...","secret":"..."}}]
If there are NO new NPCs: []"""

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
                    "temperature": 0.2,
                    "num_predict": 400
                }
            }
        )
        result = response.json()
        answer = result["message"]["content"].strip()

        print(f"\n🔎 NPC Extractor — AI ham cevap: {answer[:200]}")

        # Markdown temizle
        answer = re.sub(r'```json|```', '', answer).strip()

        # JSON array'i bul
        match = re.search(r'\[.*\]', answer, re.DOTALL)
        if not match:
            print("🔎 NPC Extractor — JSON array bulunamadı, NPC yok")
            return []

        data = json.loads(match.group(0))

        if not isinstance(data, list):
            print("🔎 NPC Extractor — Geçersiz format, liste değil")
            return []

        # Sonuçları doğrula — her NPC'nin tüm alanları olmalı
        valid_npcs = []
        required_fields = ["name", "role", "appearance", "personality", "secret"]

        for npc in data:
            if not isinstance(npc, dict):
                continue

            # Tüm gerekli alanlar var mı?
            missing = [f for f in required_fields if not npc.get(f)]
            if missing:
                print(f"🔎 NPC Extractor — ⚠️  '{npc.get('name', '?')}' eksik alan: {missing}, atlanıyor")
                continue

            # Zaten bilinen bir isim mi?
            if npc["name"].lower() in known_names:
                print(f"🔎 NPC Extractor — ⏭️  '{npc['name']}' zaten biliniyor, atlanıyor")
                continue

            valid_npcs.append(npc)
            print(f"🔎 NPC Extractor — ✅ Yeni NPC bulundu: {npc['name']} ({npc['role']})")

        return valid_npcs

    except json.JSONDecodeError as e:
        print(f"🔎 NPC Extractor — JSON parse hatası: {e}")
        return []
    except Exception as e:
        print(f"🔎 NPC Extractor — Hata: {e}")
        return []
