from db.database import get_connection

# Eşya nadirliğine göre alma zorluğu
RARITY_DC = {
    "common":    6,
    "uncommon": 10,
    "rare":     14,
    "very_rare":18
}

# ─── TEMEL İŞLEMLER ──────────────────────────────────────────────────────────

def get_inventory(session_id, player_name=""):
    conn = get_connection()
    rows = conn.execute(
        "SELECT item_name, quantity, value, rarity FROM inventory WHERE session_id = ? AND player_name = ?",
        (session_id, player_name)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_item(session_id, item_name, quantity=1, value=0, rarity="common", player_name=""):
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, quantity FROM inventory WHERE session_id = ? AND player_name = ? AND LOWER(item_name) = LOWER(?)",
        (session_id, player_name, item_name)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE inventory SET quantity = quantity + ? WHERE id = ?",
            (quantity, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO inventory (session_id, player_name, item_name, quantity, value, rarity) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, player_name, item_name, quantity, value, rarity)
        )
    conn.commit()
    conn.close()

def use_item(session_id, item_name, player_name=""):
    """
    Birebir isim eşleşmesi gerekir (büyük/küçük harf fark etmez).
    Döner: (True, mesaj) veya (False, hata mesajı)
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, item_name, quantity FROM inventory WHERE session_id = ? AND player_name = ?",
        (session_id, player_name)
    ).fetchall()
    conn.close()

    matched = None
    for row in rows:
        if row["item_name"].lower() == item_name.lower():
            matched = row
            break

    if not matched:
        item_list = ", ".join([r["item_name"] for r in rows]) if rows else "boş"
        return False, f"'{item_name}' envanterinde yok.\n🎒 Mevcut: {item_list}"

    # Miktarı düşür veya sil
    conn = get_connection()
    if matched["quantity"] > 1:
        conn.execute(
            "UPDATE inventory SET quantity = quantity - 1 WHERE id = ?",
            (matched["id"],)
        )
    else:
        conn.execute("DELETE FROM inventory WHERE id = ?", (matched["id"],))
    conn.commit()
    conn.close()

    return True, f"✅ {matched['item_name']} kullanıldı."

def remove_item(session_id, item_name, player_name=""):
    """use_item ile aynı mantık, sadece kullanım mesajı farklı."""
    success, msg = use_item(session_id, item_name, player_name)
    return success

# ─── YARDIMCI ────────────────────────────────────────────────────────────────

def get_pickup_dc(rarity):
    return RARITY_DC.get(rarity, 8)

def format_inventory_for_prompt(session_id, player_name=""):
    items = get_inventory(session_id, player_name)
    if not items:
        return f"[INVENTORY — {player_name}]\nEmpty — player has no items."
    lines = [
        f"[INVENTORY — {player_name} — ONLY ITEMS LISTED HERE EXIST IN THIS PLAYER'S POSSESSION]",
        "RULE: If an item is not in this list, the player does NOT have it, regardless of past messages."
    ]
    for item in items:
        lines.append(f"- {item['item_name']} x{item['quantity']}  ({item['rarity']}, {item['value']}gp)")
    return "\n".join(lines)

def format_all_inventories_for_prompt(session_id, player_names):
    """Format inventories for ALL players (multiplayer prompt)."""
    sections = []
    for pname in player_names:
        sections.append(format_inventory_for_prompt(session_id, pname))
    return "\n\n".join(sections)

def display_inventory(session_id, player_name=""):
    items = get_inventory(session_id, player_name)
    if not items:
        print(f"🎒 {player_name} envanter boş.")
        return
    print(f"🎒 {player_name} envanter:")
    for item in items:
        print(f"   • {item['item_name']} x{item['quantity']}  [{item['rarity']}] — {item['value']}gp")