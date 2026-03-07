from rag.retriever import get_relevant_rules
from game.character_manager import get_character_summary

GM_PERSONA = """
You are a Dungeons & Dragons Game Master.

STRICT RULES:
- Respond in English only
- Maximum 3 sentences per response, no exceptions
- Never repeat the same scene description
- React directly to what the player just did
- If a dice roll is needed: ROLL d20 + [ability] vs DC [number]
- On natural 20: exceptional success
- On natural 1: critical failure
"""

GAME_RULES = """
TURN STRUCTURE:
- Each player describes their action
- You determine if a dice roll is needed
- Player rolls and reports the result
- You narrate the outcome based on the roll

COMBAT RULES:
- Initiative: each combatant rolls d20 at start of combat, highest goes first
- Attack roll: d20 + strength modifier (melee) or dexterity modifier (ranged)
- Hit if attack roll >= enemy armor class
- Damage depends on weapon: d6 sword, d8 axe, d4 dagger
- A character at 0 HP is unconscious
"""

def build_system_prompt(characters, query, game_state=None):

    # ── Karakter özetleri ──
    character_section = "[PLAYERS]\n"
    print(f"DEBUG - Karakter sayısı: {len(characters)}")
    if characters:
        print(f"DEBUG - İlk karakter: {characters[0].get('name')}")
        for character in characters:
            character_section += get_character_summary(character) + "\n\n"
    else:
        character_section += "No characters loaded.\n"

    # ── RAG ile ilgili kuralları çek ──
    rules = get_relevant_rules(query)
    if rules is None:
        rules = "No specific rules found for this action.\n"
    rules_section = f"[RELEVANT RULES]\n{rules}"

    # ── Oyun durumu ──
    state_section = ""
    if game_state is not None:
        state_section = game_state.get_state_summary() + "\n\n"

    # ── Hepsini birleştir ──
    system_prompt = (
        f"{GM_PERSONA}\n\n"
        f"{state_section}"
        f"{character_section}\n"
        f"{rules_section}\n"
        f"{GAME_RULES}"
    )

    return system_prompt