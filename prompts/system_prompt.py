from rag.retriever import get_relevant_rules
from game.character_manager import get_character_summary
from game.npc_manager import get_all_npcs, get_npc_summary_secret
import config

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
{language_rule}
- Maximum 3 sentences per response, no exceptions
- Player characters are listed in [PLAYERS] — NEVER rename them
- ALWAYS advance the story, never repeat previous descriptions
- You MAY invent NPCs freely; scenario NPCs are listed in [SCENARIO NPCS]
- When introducing important NPCs, ALWAYS give them a proper name (e.g. "Garret the guard", not just "a guard")

DICE ROLL RULES:
- The dice system handles rolls automatically BEFORE you respond
- If [DICE ROLL RESULT] section exists below: narrate the outcome of that roll, do NOT ask for another roll
- If no [DICE ROLL RESULT] exists: the action needed no roll, narrate freely
- On natural 20: describe exceptional success with dramatic flair
- On natural 1: describe critical failure with consequences

RESPONSE FORMAT:
1. Describe what happens based on the roll result (if any)
2. End with what the player sees, hears, or can do next
"""

GAME_RULES = """
COMBAT:
- Initiative: everyone rolls d20 at start, highest goes first
- Attack: roll result vs enemy AC
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

def build_system_prompt(characters, query, game_state=None, scenario_manager=None, roll_info=None, session_id=None):

    # ── Karakter özetleri ──
    character_section = "[PLAYERS - NEVER RENAME THESE CHARACTERS]\n"
    if characters:
        for character in characters:
            character_section += get_character_summary(character) + "\n\n"
    else:
        character_section += "No characters loaded.\n"

    # ── DB'deki NPC'ler (gizli bilgilerle, sadece bu oturumun NPC'leri) ──
    npcs = get_all_npcs(session_id) if session_id else []
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
        scenario_section += (
            "\n[SCENARIO RULES — ACTIVE]\n"
            "- The scene description above defines the EXACT setting — match its atmosphere, weather, and mood\n"
            "- NPCs listed in [SCENARIO NPCS IN THIS LOCATION] are physically present — involve at least one in your response\n"
            "- Use each NPC's personality and appearance as described — never contradict them\n"
            "- NEVER reveal an NPC's secret in normal narration\n"
        )

    # ── RAG kuralları ──
    rules = get_relevant_rules(query)
    if rules is None:
        rules = "No specific rules found.\n"
    rules_section = f"[RELEVANT RULES]\n{rules}"

    # ── Oyun durumu ──
    state_section = ""
    if game_state is not None:
        state_section = game_state.get_state_summary() + "\n\n"

    # ── Zar sonucu (varsa) ──
    # Bu bölüm GM'e "zar zaten atıldı, sonucu narrate et" der
    roll_section = ""
    if roll_info:
        roll_section = (
            f"[DICE ROLL RESULT — ALREADY EXECUTED]\n"
            f"{roll_info}\n"
            f"Narrate the outcome based on this result. "
            f"Do NOT ask for another roll. Do NOT ignore this result.\n\n"
        )

    language_rule = "- Respond in English only"
    language_override = ""
    if getattr(config, "translator_model", "none") == "none":
        target_lang = getattr(config, "target_language", "Turkish")
        language_rule = f"- Respond in {target_lang} only"
        language_override = f"\n[CRITICAL LANGUAGE INSTRUCTION]\nYou MUST speak and reply EXCLUSIVELY in {target_lang}. Do NOT reply in English.\n"
        
    gm_persona_formatted = GM_PERSONA.replace("{language_rule}", language_rule)

    # ── Hepsini birleştir ──
    system_prompt = (
        f"{gm_persona_formatted}\n\n"
        f"{state_section}"
        f"{roll_section}"
        f"{scenario_section}\n"
        f"{character_section}\n"
        f"{npc_section}"
        f"{rules_section}\n"
        f"{GAME_RULES}"
        f"{language_override}"
    )

    return system_prompt