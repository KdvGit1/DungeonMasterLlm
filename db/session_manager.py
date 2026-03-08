from db.database import get_connection
import config

# ─── OTURUM OLUŞTUR ────────────────────────────────────────

def create_session(session_name):
    conn = get_connection()

    # yeni oturum açmadan önce eski aktif oturumu kapat
    conn.execute("UPDATE sessions SET is_active = 0 WHERE is_active = 1")

    cursor = conn.execute(
        "INSERT INTO sessions (session_name, is_active) VALUES (?, 1)",
        (session_name,)
    )
    session_id = cursor.lastrowid  # yeni oluşturulan satırın ID'si
    conn.commit()
    conn.close()
    print(f"Oturum oluşturuldu: {session_name} (ID: {session_id})")
    return session_id

# ─── AKTİF OTURUMU GETİR ───────────────────────────────────

def get_active_session():
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE is_active = 1"
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)

# ─── OTURUMU KAPAT ─────────────────────────────────────────

def end_session(session_id):
    conn = get_connection()
    conn.execute(
        "UPDATE sessions SET is_active = 0 WHERE id = ?",
        (session_id,)
    )
    conn.commit()
    conn.close()
    print(f"Oturum kapatıldı. (ID: {session_id})")

# ─── MESAJ KAYDET ──────────────────────────────────────────

def save_message(session_id, user_id, role, content):
    conn = get_connection()
    conn.execute(
        "INSERT INTO messages (session_id, user_id, role, content) VALUES (?, ?, ?, ?)",
        (session_id, user_id, role, content)
    )
    conn.commit()
    conn.close()

# ─── TÜM MESAJLARI GETİR ───────────────────────────────────

def load_messages(session_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,)
    ).fetchall()
    conn.close()
    # direkt Ollama'ya gönderilebilecek formata çevir
    return [{"role": row["role"], "content": row["content"]} for row in rows]

# ─── SON N MESAJI GETİR ────────────────────────────────────
def get_recent_messages(session_id):
    conn = get_connection()
    rows = conn.execute('''
        SELECT role, content FROM messages
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
    ''', (session_id, config.message_history_size)).fetchall()
    conn.close()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]