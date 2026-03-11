import re
import json
import requests
import config

# ─── GM CEVABINI ANALİZ ET ───────────────────────────────────────────────────

def parse_gm_events(gm_response, context=""):
    """
    GM cevabını analiz eder: eşya, altın, quest ipuçları.
    Döner:
    {
        "item_found": {"name": "Rusty Key", "rarity": "common", "value": 5} veya None,
        "gold_found": 0,
        "quest_hint": ""
    }
    """
    prompt = f"""You are analyzing a D&D Game Master's response to extract game events.

GM RESPONSE:
\"\"\"{gm_response}\"\"\"

Extract ONLY what is explicitly described as:
1. An item the player FINDS or is GIVEN (not already owned, not enemy's)
2. Gold/coins the player FINDS or RECEIVES
3. A quest-related discovery (finding a clue, a person, a location tied to a task)

For items: estimate rarity (common/uncommon/rare/very_rare) and approximate gold value.
If nothing is found, return nulls/zeros.

Respond ONLY with valid JSON:
{{
    "item_found": {{"name": "Rusty Key", "rarity": "common", "value": 5}},
    "gold_found": 0,
    "quest_hint": ""
}}
or if nothing:
{{
    "item_found": null,
    "gold_found": 0,
    "quest_hint": ""
}}"""

    try:
        response = requests.post(
            f"{config.base_url}/api/chat",
            json={
                "model": config.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {"num_ctx": 2048, "temperature": 0.1, "num_predict": 80}
            }
        )
        answer = response.json()["message"]["content"].strip()
        answer = re.sub(r'```json|```', '', answer).strip()
        match = re.search(r'\{.*\}', answer, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            return {
                "item_found": data.get("item_found"),
                "gold_found": int(data.get("gold_found", 0)),
                "quest_hint": data.get("quest_hint", "")
            }
    except Exception as e:
        print(f"   ❌ parse_gm_events HATA: {e}")

    return {"item_found": None, "gold_found": 0, "quest_hint": ""}