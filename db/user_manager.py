import sqlite3
import bcrypt
import config
from db.database import get_connection

# ─── KAYIT ─────────────────────────────────────────────────

def register_user(username, password, role):
    # şifreyi düz metin olarak kaydetmiyoruz
    # bcrypt önce şifreyi karıştırır (hash), DB'ye öyle kaydeder
    password_hash = bcrypt.hashpw(
        password.encode('utf-8'),  # string'i byte'a çevir
        bcrypt.gensalt()           # rastgele tuz ekler, her hash farklı olur
    )

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, ?)
        ''', (username, password_hash, role))
        conn.commit()
        conn.close()
        print(f"'{username}' kaydedildi.")
        return True

    except sqlite3.IntegrityError:
        # UNIQUE constraint'i ihlal edildi
        # yani aynı kullanıcı adı zaten var
        print(f"'{username}' kullanıcı adı zaten alınmış.")
        return None

# ─── GİRİŞ ─────────────────────────────────────────────────

def login_user(username, password):
    conn = get_connection()
    cursor = conn.cursor()

    # kullanıcıyı DB'den çek
    cursor.execute('''
        SELECT * FROM users WHERE username = ?
    ''', (username,))  # virgül önemli! tuple olması lazım

    user = cursor.fetchone()  # tek satır döner, yoksa None
    conn.close()

    if user is None:
        print("Kullanıcı bulunamadı.")
        return None

    # girilen şifreyi DB'deki hash ile karşılaştır
    password_correct = bcrypt.checkpw(
        password.encode('utf-8'),  # girilen şifre
        user['password_hash']      # DB'deki hash
    )

    if password_correct:
        print(f"Hoş geldin, {username}!")
        return dict(user)  # sqlite.Row'u normal dict'e çevir
    else:
        print("Şifre yanlış.")
        return None

# ─── KULLANICI BİLGİSİ ─────────────────────────────────────

def get_user_by_id(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT * FROM users WHERE id = ?
    ''', (user_id,))

    user = cursor.fetchone()
    conn.close()

    if user is None:
        return None

    return dict(user)

# ─── YETKİ KONTROLÜ ────────────────────────────────────────

def is_gm(user):
    # kullanıcının rolü 'gm' ise True, değilse False döner
    return user['role'] == 'gm'