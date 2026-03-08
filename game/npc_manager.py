import json
import re
from db.database import get_connection

# ─── NPC KAYDET ────────────────────────────────────────────

def save_npc(name, public_data, secret_info):
    conn = get_connection()
    try:
        # aynı isimde NPC var mı kontrol et
        existing = conn.execute(
            "SELECT id FROM characters WHERE name = ? AND type = 'npc'",
            (name,)
        ).fetchone()

        if existing:
            # varsa güncelle
            conn.execute('''
                UPDATE characters
                SET data = ?, secret_info = ?, updated_at = CURRENT_TIMESTAMP
                WHERE name = ? AND type = 'npc'
            ''', (json.dumps(public_data), secret_info, name))
            print(f"📝 NPC güncellendi: {name}")
        else:
            # yoksa ekle
            conn.execute('''
                INSERT INTO characters (user_id, name, data, secret_info, type)
                VALUES (NULL, ?, ?, ?, 'npc')
            ''', (name, json.dumps(public_data), secret_info))
            print(f"📝 Yeni NPC eklendi: {name}")

        conn.commit()
        return True
    except Exception as e:
        print(f"NPC kaydedilemedi: {e}")
        return None
    finally:
        conn.close()

# ─── TÜM NPC'LERİ GETİR ────────────────────────────────────

def get_all_npcs():
    conn = get_connection()
    rows = conn.execute(
        "SELECT name, data, secret_info FROM characters WHERE type = 'npc'"
    ).fetchall()
    conn.close()

    return [
        {
            "name": row["name"],
            "public": json.loads(row["data"]),
            "secret": row["secret_info"]
        }
        for row in rows
    ]

# ─── NPC ÖZETLERİ ──────────────────────────────────────────

def get_npc_summary_secret(npc):
    # sadece system prompt'a gider, oyuncu görmez
    pub = npc["public"]
    return (
        f"NPC: {npc['name']}\n"
        f"  Role: {pub.get('role', '?')}\n"
        f"  Appearance: {pub.get('appearance', '?')}\n"
        f"  Personality: {pub.get('personality', '?')}\n"
        f"  SECRET (never reveal): {npc['secret']}"
    )

# ─── GM CEVABINDAN NPC TAG'İ PARSE ET ──────────────────────

def parse_and_save_npcs(gm_response):
    # GM cevabında [NPC_CREATE: ...] tag'i ara
    # format: [NPC_CREATE: isim | rol | görünüm | kişilik | gizli_bilgi]
    pattern = r'\[NPC_CREATE:\s*(.+?)\]'
    matches = re.findall(pattern, gm_response, re.DOTALL)

    for match in matches:
        try:
            parts = [p.strip() for p in match.split('|')]

            if len(parts) < 5:
                print(f"⚠️  NPC tag eksik bilgi içeriyor, atlanıyor: {match}")
                continue

            name, role, appearance, personality, secret = parts[:5]

            public_data = {
                "role": role,
                "appearance": appearance,
                "personality": personality
            }

            save_npc(name, public_data, secret)

        except Exception as e:
            print(f"NPC parse hatası: {e}")

    # tag'leri GM cevabından temizle, oyuncuya gösterme
    clean_response = re.sub(pattern, '', gm_response, flags=re.DOTALL).strip()
    return clean_response