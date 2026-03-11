import json
from db.database import get_connection

# ─── DB İŞLEMLERİ ────────────────────────────────────────────────────────────

def init_quests(session_id, scenario_meta):
    """
    scenario.yaml'daki quest tanımlarını DB'ye yükler (sadece ilk kez).
    """
    quests = scenario_meta.get("quests", [])
    if not quests:
        return

    conn = get_connection()
    for q in quests:
        existing = conn.execute(
            "SELECT id FROM quests WHERE session_id = ? AND quest_id = ?",
            (session_id, q["id"])
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO quests
                   (session_id, quest_id, title, description, status,
                    trigger_node, complete_node, reward_gold, reward_xp)
                   VALUES (?, ?, ?, ?, 'inactive', ?, ?, ?, ?)""",
                (
                    session_id, q["id"],
                    q.get("title", q["id"]),
                    q.get("description", ""),
                    q.get("trigger_node", ""),
                    q.get("complete_node", ""),
                    int(q.get("reward_gold", 0)),
                    int(q.get("reward_xp", 0))
                )
            )
    conn.commit()
    conn.close()

def check_node_quests(session_id, node_id):
    """
    Node geçişinde quest aktifleştirme / tamamlama kontrolü.
    Döner: list of {"event": "activated"|"completed", "quest": {...}}
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM quests WHERE session_id = ?",
        (session_id,)
    ).fetchall()
    conn.close()

    events = []
    for row in rows:
        q = dict(row)
        if q["status"] == "inactive" and q.get("trigger_node") == node_id:
            _set_status(session_id, q["quest_id"], "active")
            q["status"] = "active"
            events.append({"event": "activated", "quest": q})
            print(f"   📜 Quest aktifleşti: {q['title']}")

        elif q["status"] == "active" and q.get("complete_node") == node_id:
            _set_status(session_id, q["quest_id"], "completed")
            q["status"] = "completed"
            events.append({"event": "completed", "quest": q})
            print(f"   ✅ Quest tamamlandı: {q['title']} (+{q['reward_gold']}gp, +{q['reward_xp']}xp)")

    return events

def get_active_quests(session_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM quests WHERE session_id = ? AND status = 'active'",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_quests(session_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM quests WHERE session_id = ?",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def format_quests_for_prompt(session_id):
    active = get_active_quests(session_id)
    if not active:
        return ""
    lines = ["[ACTIVE QUESTS]"]
    for q in active:
        lines.append(f"- {q['title']}: {q['description']}")
    return "\n".join(lines)

# ─── YARDIMCI ────────────────────────────────────────────────────────────────

def _set_status(session_id, quest_id, status):
    conn = get_connection()
    conn.execute(
        "UPDATE quests SET status = ? WHERE session_id = ? AND quest_id = ?",
        (status, session_id, quest_id)
    )
    conn.commit()
    conn.close()