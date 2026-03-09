import json
from db.database import get_connection

# ─── NPC KAYDET ────────────────────────────────────────────

def save_npc(name, public_data, secret_info, session_id):
    conn = get_connection()
    try:
        # aynı isimde ve aynı oturumdaki NPC var mı kontrol et
        existing = conn.execute(
            "SELECT id FROM characters WHERE name = ? AND type = 'npc' AND session_id = ?",
            (name, session_id)
        ).fetchone()

        if existing:
            # varsa güncelle
            conn.execute('''
                UPDATE characters
                SET data = ?, secret_info = ?, updated_at = CURRENT_TIMESTAMP
                WHERE name = ? AND type = 'npc' AND session_id = ?
            ''', (json.dumps(public_data), secret_info, name, session_id))
            print(f"📝 NPC güncellendi: {name} (session: {session_id})")
        else:
            # yoksa ekle
            conn.execute('''
                INSERT INTO characters (user_id, name, data, secret_info, type, session_id)
                VALUES (NULL, ?, ?, ?, 'npc', ?)
            ''', (name, json.dumps(public_data), secret_info, session_id))
            print(f"📝 Yeni NPC eklendi: {name} (session: {session_id})")

        conn.commit()
        return True
    except Exception as e:
        print(f"NPC kaydedilemedi: {e}")
        return None
    finally:
        conn.close()

# ─── TÜM NPC'LERİ GETİR ────────────────────────────────────

def get_all_npcs(session_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT name, data, secret_info FROM characters WHERE type = 'npc' AND session_id = ?",
        (session_id,)
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
