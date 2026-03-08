import os
import yaml
import json
import requests
import config

# ─────────────────────────────────────────────────────────────
#  SENARYO YÖNETİCİSİ
# ─────────────────────────────────────────────────────────────

class ScenarioManager:

    def __init__(self, scenario_path):
        self.scenario_path = scenario_path   # örn: "scenarios/village_dragon"
        self.nodes_path    = os.path.join(scenario_path, "nodes")
        self.meta          = self._load_scenario_meta()
        self.current_node  = None            # aktif node dict

    # ─── YAML yükleme ─────────────────────────────────────────

    def _load_scenario_meta(self):
        """scenario.yaml'ı okur: title, description, start_node vb."""
        path = os.path.join(self.scenario_path, "scenario.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def load_node(self, node_id):
        """nodes/{node_id}.yaml dosyasını yükler, current_node'u günceller."""
        path = os.path.join(self.nodes_path, f"{node_id}.yaml")
        with open(path, "r", encoding="utf-8") as f:
            self.current_node = yaml.safe_load(f)
        print(f"\n📍 Yeni lokasyon: {self.current_node.get('title', node_id)}")
        return self.current_node

    # ─── Başlangıç ────────────────────────────────────────────

    def start(self):
        """start_node'u yükler."""
        start_id = self.meta.get("start_node", "00_village_gates")
        self.load_node(start_id)

    # ─── System prompt için çıktılar ──────────────────────────

    def get_node_for_prompt(self):
        """
        Mevcut node'un scene + gm_instructions + available_actions bilgisini
        system prompt'a eklenecek formatta döner.
        """
        if not self.current_node:
            return ""

        node = self.current_node
        lines = []
        lines.append("[CURRENT SCENARIO NODE]")
        lines.append(f"Location: {node.get('title', '?')}")

        if node.get("scene"):
            lines.append(f"\nScene:\n{node['scene'].strip()}")

        if node.get("gm_instructions"):
            lines.append(f"\nGM Instructions (do NOT reveal to players):\n{node['gm_instructions'].strip()}")

        if node.get("available_actions"):
            lines.append(f"\nMANDATORY ACTIONS & DCs (when player attempts any of these, use EXACTLY these DC values and demand a ROLL — do not skip or invent your own):\n{node['available_actions'].strip()}")

        return "\n".join(lines) + "\n"

    def get_npcs_for_prompt(self):
        """
        Node içindeki NPC'lerin tam bilgisini (secret dahil) döner.
        Bu bölüm sadece GM system prompt'una gider.
        """
        if not self.current_node:
            return ""

        npcs = self.current_node.get("npcs", [])
        if not npcs:
            return ""

        lines = ["[SCENARIO NPCS IN THIS LOCATION]"]
        for npc in npcs:
            lines.append(f"\nNPC: {npc.get('name', '?')}")
            lines.append(f"  Role       : {npc.get('role', '?')}")
            lines.append(f"  Appearance : {npc.get('appearance', '?')}")
            lines.append(f"  Personality: {npc.get('personality', '?')}")
            lines.append(f"  SECRET (never reveal): {npc.get('secret', '?')}")

        return "\n".join(lines) + "\n"

    # ─── Trigger kontrolü ─────────────────────────────────────

    def check_trigger(self, recent_messages):
        """
        Son N mesajı ve mevcut node'un trigger'larını AI'a gönderir.
        Eğer bir trigger koşulu gerçekleştiyse next_node id'sini döner,
        yoksa None döner.

        Küçük, hızlı bir çağrı: temperature=0.1, num_predict=20
        """
        if not self.current_node:
            return None

        triggers = self.current_node.get("triggers", [])
        if not triggers:
            return None

        # Son 4 mesajı al
        last_msgs = recent_messages[-4:] if len(recent_messages) > 4 else recent_messages

        # Konuşma özetini hazırla
        conversation = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in last_msgs
        )

        # Trigger listesini düz metin yap
        trigger_list = "\n".join(
            f"- If '{t['condition']}' → {t['next_node']}"
            for t in triggers
        )

        prompt = f"""You are checking if any scene transition condition is met.

RECENT CONVERSATION:
{conversation}

TRIGGER CONDITIONS (check each one):
{trigger_list}

Instructions:
- Read the conversation carefully.
- If ANY trigger condition is clearly met, respond with ONLY the next_node value (e.g. "01_tavern").
- If NO condition is met, respond with ONLY the word "none".
- Do NOT explain. Do NOT add punctuation. One word only."""

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
                        "temperature": 0.1,
                        "num_predict": 20
                    }
                }
            )
            result = response.json()
            answer = result["message"]["content"].strip().lower()

            # "none" veya boş gelirse geçiş yok
            if answer == "none" or not answer:
                return None

            # Gelen cevap geçerli bir node mu?
            valid_ids = [t["next_node"] for t in triggers]
            if answer in valid_ids:
                return answer

            # Cevap içinde geçerli bir node id var mı?
            for node_id in valid_ids:
                if node_id in answer:
                    return node_id

            return None

        except Exception as e:
            print(f"⚠️  Trigger check hatası: {e}")
            return None