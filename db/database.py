import sqlite3
import os
import config

def get_connection():
    conn = sqlite3.connect(config.sq_lite_path)
    conn.row_factory = sqlite3.Row
    return conn

# ─── TABLO OLUŞTURMA ───────────────────────────────────────

def create_users_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT CHECK(role IN ('gm', 'player')) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

def create_characters_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            data TEXT NOT NULL,
            secret_info TEXT,
            type TEXT CHECK(type IN ('player', 'npc')) DEFAULT 'player',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

def create_sessions_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    ''')

def create_messages_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            user_id INTEGER,
            role TEXT CHECK(role IN ('user', 'assistant', 'system')) NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

# ─── MİGRATION ─────────────────────────────────────────────

def migrate(conn):
    cursor = conn.cursor()

    # mevcut characters tablosunun sütunlarını kontrol et
    cursor.execute("PRAGMA table_info(characters)")
    columns = [row["name"] for row in cursor.fetchall()]

    # secret_info yoksa ekle
    if "secret_info" not in columns:
        cursor.execute("ALTER TABLE characters ADD COLUMN secret_info TEXT")
        print("Migration: secret_info sütunu eklendi.")

    # type yoksa ekle
    if "type" not in columns:
        cursor.execute(
            "ALTER TABLE characters ADD COLUMN type TEXT DEFAULT 'player'"
        )
        print("Migration: type sütunu eklendi.")

    conn.commit()

# ─── INITIALIZE ────────────────────────────────────────────

def initialize_db():
    os.makedirs(os.path.dirname(config.sq_lite_path), exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    create_users_table(cursor)
    create_characters_table(cursor)
    create_sessions_table(cursor)
    create_messages_table(cursor)

    conn.commit()

    # migration: mevcut tablolara yeni sütunlar ekle
    migrate(conn)

    conn.close()
    print("Veritabanı hazır.")