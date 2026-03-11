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

def create_inventory_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            player_name TEXT NOT NULL DEFAULT '',
            item_name TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            value INTEGER DEFAULT 0,
            rarity TEXT DEFAULT 'common',
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    ''')

def create_player_stats_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            hp INTEGER DEFAULT 10,
            max_hp INTEGER DEFAULT 10,
            gold INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            ability_xp TEXT DEFAULT '{}',
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    ''')

def create_quests_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            quest_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT CHECK(status IN ('inactive','active','completed','failed')) DEFAULT 'inactive',
            trigger_node TEXT DEFAULT '',
            complete_node TEXT DEFAULT '',
            reward_gold INTEGER DEFAULT 0,
            reward_xp INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    ''')

# ─── MİGRATION ─────────────────────────────────────────────

def migrate(conn):
    cursor = conn.cursor()

    # characters tablosu
    cursor.execute("PRAGMA table_info(characters)")
    columns = [row["name"] for row in cursor.fetchall()]

    if "secret_info" not in columns:
        cursor.execute("ALTER TABLE characters ADD COLUMN secret_info TEXT")
        print("Migration: secret_info sütunu eklendi.")

    if "type" not in columns:
        cursor.execute("ALTER TABLE characters ADD COLUMN type TEXT DEFAULT 'player'")
        print("Migration: type sütunu eklendi.")

    if "session_id" not in columns:
        cursor.execute("ALTER TABLE characters ADD COLUMN session_id INTEGER REFERENCES sessions(id)")
        print("Migration: session_id sütunu eklendi.")

    # user_id NOT NULL kaldır
    cursor.execute("PRAGMA table_info(characters)")
    needs_rebuild = any(row[1] == "user_id" and row[3] == 1 for row in cursor.fetchall())

    if needs_rebuild:
        print("Migration: user_id NOT NULL kaldırılıyor...")
        cursor.execute('''
            CREATE TABLE characters_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                secret_info TEXT,
                type TEXT CHECK(type IN ('player', 'npc')) DEFAULT 'player',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                session_id INTEGER REFERENCES sessions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        cursor.execute('''
            INSERT INTO characters_new (id, user_id, name, data, secret_info, type, updated_at, session_id)
            SELECT id, user_id, name, data, secret_info, type, updated_at, session_id FROM characters
        ''')
        cursor.execute("DROP TABLE characters")
        cursor.execute("ALTER TABLE characters_new RENAME TO characters")
        print("Migration: characters tablosu yeniden oluşturuldu.")

    # Yeni tablolar — yoksa ekle
    create_inventory_table(cursor)
    create_player_stats_table(cursor)
    create_quests_table(cursor)

    # inventory tablosuna player_name sütunu ekle (multiplayer için)
    cursor.execute("PRAGMA table_info(inventory)")
    inv_columns = [row["name"] for row in cursor.fetchall()]
    if "player_name" not in inv_columns:
        cursor.execute("ALTER TABLE inventory ADD COLUMN player_name TEXT NOT NULL DEFAULT ''")
        print("Migration: inventory.player_name sütunu eklendi.")

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
    migrate(conn)
    conn.close()
    print("Veritabanı hazır.")