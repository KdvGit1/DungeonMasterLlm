from rag.retriever import get_relevant_rules
from game.character_manager import get_character_summary
from game.npc_manager import get_all_npcs, get_npc_summary_secret

# ─── GM KİŞİLİĞİ (SABİT) ────────────────────────────────────────────────────

GM_PERSONA = """
You are a Dungeons & Dragons Game Master.

SETTING: Medieval fantasy world only. No phones, no modern technology.

PERSPECTIVE (CRITICAL):
- You are the NARRATOR, not a character
- NEVER use "I", "me", "my" in your responses
- Always refer to characters in third person: "Elias does...", "she says..."
- You describe what happens, you do not participate

STRICT RULES:
- Respond in English only
- Maximum 3 sentences per response, no exceptions
- Player characters are listed in [PLAYERS] — NEVER rename them
- ALWAYS advance the story, never repeat previous descriptions
- You MAY invent NPCs freely; scenario NPCs are listed in [SCENARIO NPCS]

NPC CREATION (for NPCs NOT already listed in scenario):
- When introducing a NEW named NPC, add this tag at the very END of your response:
  [NPC_CREATE: name | role | appearance | personality | secret_they_are_hiding]
- The secret must be something the NPC actively conceals from players
- NEVER reveal the secret in normal narration
- Every NPC must have a secret, no exceptions

DICE ROLL RULES (CRITICAL):
- Any action with uncertain outcome REQUIRES a dice roll
- Do NOT resolve uncertain actions without asking for a roll first
- When a roll is needed write exactly: ROLL d20 + [ability] vs DC [number]
- Actions that need rolls: attacking, sneaking, persuading, investigating, jumping
- Actions that do NOT need rolls: talking, looking around, walking normally
- On natural 20: exceptional success
- On natural 1: critical failure

RESPONSE FORMAT:
1. Describe what happens (1-2 sentences max)
2. If uncertain outcome: ROLL d20 + [ability] vs DC [number]
3. If new NPC introduced: [NPC_CREATE: ...] at the end
"""

GAME_RULES = """
COMBAT:
- Initiative: everyone rolls d20 at start, highest goes first
- Attack: ROLL d20 + strength (melee) or dexterity (ranged) vs enemy AC
- Damage: d6 sword, d8 axe, d4 dagger
- 0 HP = unconscious

ABILITY CHECKS:
- Strength: breaking, lifting, climbing
- Dexterity: sneaking, dodging, acrobatics
- Constitution: enduring pain, holding breath
- Intelligence: investigating, recalling knowledge
- Wisdom: perception, insight, survival
- Charisma: persuading, deceiving, intimidating
"""

# ─── SİSTEM PROMPT OLUŞTUR ───────────────────────────────────────────────────

def build_system_prompt(characters, query, game_state=None, scenario_manager=None):

    # ── Karakter özetleri ──
    character_section = "[PLAYERS - NEVER RENAME THESE CHARACTERS]\n"
    if characters:
        for character in characters:
            character_section += get_character_summary(character) + "\n\n"
    else:
        character_section += "No characters loaded.\n"

    # ── DB'deki NPC'ler (gizli bilgilerle) ──
    npcs = get_all_npcs()
    if npcs:
        npc_section = "[KNOWN NPCS - SECRET INFO NEVER REVEALED TO PLAYERS]\n"
        for npc in npcs:
            npc_section += get_npc_summary_secret(npc) + "\n\n"
    else:
        npc_section = ""

    # ── Senaryo node bölümü ──
    scenario_section = ""
    if scenario_manager is not None:
        scenario_section += scenario_manager.get_node_for_prompt()
        scenario_section += scenario_manager.get_npcs_for_prompt()

    # ── RAG kuralları ──
    rules = get_relevant_rules(query)
    if rules is None:
        rules = "No specific rules found.\n"
    rules_section = f"[RELEVANT RULES]\n{rules}"

    # ── Oyun durumu ──
    state_section = ""
    if game_state is not None:
        state_section = game_state.get_state_summary() + "\n\n"

    # ── Hepsini birleştir ──
    system_prompt = (
        f"{GM_PERSONA}\n\n"
        f"{state_section}"
        f"{scenario_section}\n"
        f"{character_section}\n"
        f"{npc_section}"
        f"{rules_section}\n"
        f"{GAME_RULES}"
    )

    return system_prompt