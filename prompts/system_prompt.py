from rag.retriever import get_relevant_rules
from game.character_manager import get_character_summary
from game.npc_manager import get_all_npcs, get_npc_summary_secret
from game.inventory_manager import format_inventory_for_prompt, format_all_inventories_for_prompt
from game.quest_manager import format_quests_for_prompt
from game.xp_manager import format_stats_for_prompt
import config

# ─── GM KİŞİLİĞİ ─────────────────────────────────────────────────────────────

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
- When introducing important NPCs, ALWAYS give them a proper name

DICE ROLL RULES:
- The dice system handles rolls automatically BEFORE you respond
- If [DICE ROLL RESULT] section exists below: narrate the outcome, do NOT ask for another roll
- If no [DICE ROLL RESULT] exists: the action needed no roll, narrate freely
- On natural 20: describe exceptional success with dramatic flair
- On natural 1: describe critical failure with consequences

INVENTORY RULE (CRITICAL):
- [INVENTORY] section is the ONLY source of truth for what the player owns
- If an item is not listed there, the player does NOT have it — regardless of past messages
- NEVER give the player items they didn't earn through gameplay

RESPONSE FORMAT:
1. Describe what happens based on the roll result (if any)
2. End with what the player sees, hears, or can do next
"""

GM_PERSONA_MULTIPLAYER = """
MULTIPLAYER RULES (CRITICAL):
- Multiple players are acting simultaneously in the same world
- [PLAYER ACTIONS THIS ROUND] lists what each player did this round
- You MUST address ALL players' actions in a SINGLE response
- Describe what happens for each player, weaving their actions into one cohesive narrative
- Players who PASS do nothing — do not narrate actions for them
- Keep the response concise: maximum 2 sentences per player's action
- All players share the same world, NPCs, and environment
- Each player has their OWN separate inventory — check [INVENTORY] sections per player
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

def build_system_prompt(characters, query, game_state=None, scenario_manager=None,
                        roll_info=None, session_id=None, round_actions=None):

    # ── Karakter özetleri ──
    character_section = "[PLAYERS - NEVER RENAME THESE CHARACTERS]\n"
    if characters:
        for character in characters:
            character_section += get_character_summary(character) + "\n\n"
    else:
        character_section += "No characters loaded.\n"

    # ── Player stats (HP, gold, seviye) ──
    stats_section = ""
    if session_id and characters:
        for char in characters:
            stats_section += format_stats_for_prompt(session_id, char["name"]) + "\n"

    # ── Envanter ──
    inventory_section = ""
    if session_id:
        if characters and len(characters) > 1:
            # Multiplayer: show all players' inventories
            player_names = [c["name"] for c in characters]
            inventory_section = format_all_inventories_for_prompt(session_id, player_names) + "\n"
        elif characters:
            inventory_section = format_inventory_for_prompt(session_id, characters[0]["name"]) + "\n"
        else:
            inventory_section = format_inventory_for_prompt(session_id) + "\n"

    # ── Aktif questler ──
    quest_section = ""
    if session_id:
        quest_section = format_quests_for_prompt(session_id)
        if quest_section:
            quest_section += "\n"

    # ── DB'deki NPC'ler ──
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

        node = scenario_manager.current_node or {}
        npc_names = [n.get("name", "?") for n in node.get("npcs", [])]
        npc_list_str = ", ".join(npc_names) if npc_names else "none"

        scenario_section += (
            "\n[SCENARIO RULES — MANDATORY]\n"
            "- The scene description above defines the EXACT setting — match atmosphere, weather, and mood\n"
            f"- NPCs PHYSICALLY PRESENT: {npc_list_str}\n"
            "- You MUST mention at least one of these NPCs by name in EVERY response\n"
            "- Use their exact personality and appearance as described\n"
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

    # ── Zar sonucu ──
    roll_section = ""
    if roll_info:
        roll_section = (
            f"[DICE ROLL RESULT — ALREADY EXECUTED]\n"
            f"{roll_info}\n"
            f"Narrate the outcome. Do NOT ask for another roll. Do NOT ignore this result.\n\n"
        )

    # ── Round actions (multiplayer) ──
    round_actions_section = ""
    if round_actions:
        round_actions_section = "[PLAYER ACTIONS THIS ROUND]\n"
        for pname, act in round_actions.items():
            if act == "__PASS__":
                round_actions_section += f"- {pname}: PASSES (does nothing this round)\n"
            else:
                round_actions_section += f"- {pname}: {act}\n"
        round_actions_section += "\n"

    # ── Dil kuralı ──
    language_rule = "- Respond in English only"
    language_override = ""
    if getattr(config, "translator_model", "none") == "none":
        target_lang = getattr(config, "target_language", "Turkish")
        language_rule = f"- Respond in {target_lang} only"
        language_override = (
            f"\n[CRITICAL LANGUAGE INSTRUCTION]\n"
            f"You MUST speak and reply EXCLUSIVELY in {target_lang}. Do NOT reply in English.\n"
        )

    gm_persona_formatted = GM_PERSONA.replace("{language_rule}", language_rule)

    # ── Multiplayer persona ──
    multiplayer_section = ""
    if round_actions and len(round_actions) > 0:
        multiplayer_section = GM_PERSONA_MULTIPLAYER + "\n"

    # ── Hepsini birleştir ──
    system_prompt = (
        f"{gm_persona_formatted}\n\n"
        f"{multiplayer_section}"
        f"{state_section}"
        f"{stats_section}"
        f"{inventory_section}"
        f"{quest_section}"
        f"{round_actions_section}"
        f"{roll_section}"
        f"{scenario_section}\n"
        f"{character_section}\n"
        f"{npc_section}"
        f"{rules_section}\n"
        f"{GAME_RULES}"
        f"{language_override}"
    )

    return system_prompt