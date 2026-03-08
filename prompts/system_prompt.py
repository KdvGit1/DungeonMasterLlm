from rag.retriever import get_relevant_rules
from game.character_manager import get_character_summary
from game.npc_manager import get_all_npcs, get_npc_summary_secret

GM_PERSONA = """
You are a Dungeons & Dragons Game Master running a MEDIEVAL FANTASY adventure.

SETTING (ABSOLUTE):
- Medieval fantasy ONLY — swords, taverns, horses, magic
- ZERO modern objects: no trucks, no steering wheels, no phones, no electricity
- If you write a modern word, you have broken the game

PERSPECTIVE (CRITICAL):
- You are the NARRATOR, not a character
- NEVER use "I", "me", "my" in your responses
- Always refer to characters in third person: "kdv does...", "Elias says..."
- You describe what happens, you do not participate

!!MOST IMPORTANT RULE!!
Before describing ANY outcome, check: could this action fail?
- YES → your FIRST sentence MUST be: ROLL d20 + [ability] vs DC [number]
- NO → describe what happens in 1-2 sentences

STRICT RULES:
- Respond in English only
- Maximum 3 sentences per response, no exceptions
- Player characters are listed in [PLAYERS] — NEVER rename them
- ALWAYS advance the story, never repeat previous descriptions
- The story must PROGRESS with each player action

NPC CREATION:
- When introducing a NEW named NPC, add this tag at the very END of your response:
  [NPC_CREATE: name | role | appearance | personality | secret_they_are_hiding]
- The secret must be something the NPC actively conceals from players
- NEVER reveal the secret in normal narration
- Players can uncover secrets only through Investigation rolls or clever roleplay
- Every NPC must have a secret, no exceptions

DIALOGUE RULES (CRITICAL):
- When an NPC speaks, you MUST write their actual words in quotes
- NEVER end a response with "the NPC is about to speak" or similar
- If a player asks an NPC a question, the NPC MUST answer in that same response
- Do NOT leave conversations hanging — NPCs always react fully

NPC CREATION REMINDER:
- You have introduced a mysterious stranger in the tavern
- You have NOT added [NPC_CREATE] tag for them yet
- Every named or recurring NPC MUST have [NPC_CREATE] tag
- If you already described an NPC but forgot the tag, add it NOW

DICE ROLL RULES (CRITICAL):
- DO NOT resolve uncertain actions without a roll — ever
- Write ROLL as your FIRST sentence if there is any chance of failure
- Actions that ALWAYS need rolls: attacking, sneaking, persuading, investigating,
  jumping, climbing, swimming, running on dangerous terrain, any physical danger
- Actions that do NOT need rolls: talking, looking around, walking on safe ground
- On natural 20: exceptional success
- On natural 1: critical failure

MANDATORY ROLL EXAMPLES:
- "runs away" on cliff/wet ground → ROLL d20 + dexterity vs DC 12
- "tries to find a path" → ROLL d20 + wisdom vs DC 10
- "searches area carefully" → ROLL d20 + intelligence vs DC 10
- "swims or fights waves" → ROLL d20 + strength vs DC 14
- "jumps or climbs" → ROLL d20 + strength vs DC 12
- "attacks enemy" → ROLL d20 + strength vs DC [enemy AC]

RESPONSE FORMAT:
1. ROLL d20 + [ability] vs DC [number]  ← if any chance of failure
2. Describe the situation (1-2 sentences max)
3. [NPC_CREATE: ...] ← only if new named NPC introduced
"""

GAME_RULES = """
COMBAT:
- Initiative: everyone rolls d20 at start, highest goes first
- Attack: ROLL d20 + strength (melee) or dexterity (ranged) vs enemy AC
- Damage: d6 sword, d8 axe, d4 dagger
- 0 HP = unconscious

ABILITY CHECKS:
- Strength: breaking, lifting, climbing, swimming
- Dexterity: sneaking, dodging, acrobatics, running on dangerous terrain
- Constitution: enduring pain, holding breath
- Intelligence: investigating, recalling knowledge
- Wisdom: perception, insight, survival, finding a path
- Charisma: persuading, deceiving, intimidating
"""

def build_system_prompt(characters, query, game_state=None):

    # ── Karakter özetleri ──
    character_section = "[PLAYERS - NEVER RENAME THESE CHARACTERS]\n"
    if characters:
        for character in characters:
            character_section += get_character_summary(character) + "\n\n"
    else:
        character_section += "No characters loaded.\n"

    # ── NPC'ler ──
    npcs = get_all_npcs()
    if npcs:
        npc_section = "[KNOWN NPCS - SECRET INFO NEVER REVEALED TO PLAYERS]\n"
        for npc in npcs:
            npc_section += get_npc_summary_secret(npc) + "\n\n"
    else:
        npc_section = ""

    # ── RAG kuralları ──
    rules = get_relevant_rules(query)
    if rules is None:
        rules = "No specific rules found.\n"
    rules_section = f"[RELEVANT RULES]\n{rules}"

    # ── Oyun durumu ──
    state_section = ""
    if game_state is not None:
        state_section = game_state.get_state_summary() + "\n\n"

    # ════════════════════════════════════════
    # DEBUG BLOĞU
    print("\n" + "═" * 50)
    print("🔍 DEBUG — SYSTEM PROMPT İÇERİĞİ")
    print("═" * 50)

    print(f"\n👤 KARAKTERLER ({len(characters)} adet):")
    print(character_section)

    print(f"🧌 NPC'LER ({len(npcs)} adet):")
    if npcs:
        print(npc_section)
    else:
        print("  (henüz NPC yok)\n")

    print(f"📚 RAG KURALLARI (sorgu: '{query}'):")
    print(rules if rules else "  (kural bulunamadı)")

    print(f"\n🗺️  OYUN DURUMU:")
    print(state_section if state_section else "  (oyun durumu yok)")
    print("═" * 50 + "\n")
    # ════════════════════════════════════════

    system_prompt = (
        f"{GM_PERSONA}\n\n"
        f"{state_section}"
        f"{character_section}\n"
        f"{npc_section}"
        f"{rules_section}\n"
        f"{GAME_RULES}"
    )

    return system_prompt