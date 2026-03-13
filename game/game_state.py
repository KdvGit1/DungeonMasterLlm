class GameState:
    def __init__(self):
        self.current_scene = "The adventure begins..."
        self.active_players = []
        self.characters = []
        self.is_combat = False
        self.combat_order = []
        self.current_turn_index = 0
        self.session_id = None
        self.turn_count = 0
        self.current_node = None
        self.combat_messages = []

        # Aktif savaş bilgisi — EncounterState nesnesi veya None
        self.active_encounter = None

        # Oyuncu onayı bekleyen encounter (Attack/Flee sorulacak)
        self.pending_encounter = None

        # Eşya alma bekleniyor mu?
        # {"name": str, "rarity": str, "value": int, "dc": int}
        self.pending_item = None

        # Oyuncu status effect'leri (knockdown, poison vb.)
        # {player_name: [{type, turns_left, ...}, ...]}
        self.player_status_effects = {}

        # Skill cooldown takibi (tur bazlı)
        # {player_name: {skill_id: remaining_turns}}
        self.skill_cooldowns = {}

    def add_player(self, user, character):
        self.active_players.append(user)
        self.characters.append(character)
        print(f"{character['name']} oyuna katıldı.")

    def start_encounter(self, encounter_state):
        """EncounterState nesnesi ile savaş başlatır."""
        self.active_encounter = encounter_state
        self.is_combat = True
        self.pending_encounter = None

        alive = [e for e in encounter_state.enemies if e["hp"] > 0]
        names = ", ".join(e["display_name"] for e in alive)
        print(f"\n⚔️  SAVAŞ BAŞLADI: {names}")
        for e in alive:
            print(f"   {e['display_name']}  HP: {e['hp']}  AC: {e['ac']}")

    def end_encounter(self):
        self.active_encounter = None
        self.is_combat = False
        self.pending_encounter = None
        print("⚔️  Savaş bitti.")

    def start_combat(self, initiative_order):
        self.combat_order = sorted(initiative_order, key=lambda x: x[1], reverse=True)
        self.is_combat = True
        self.current_turn_index = 0
        self.turn_count = 0

    def next_turn(self):
        if not self.is_combat:
            return None
        self.turn_count += 1
        self.current_turn_index = (self.current_turn_index + 1) % len(self.combat_order)
        return self.combat_order[self.current_turn_index][0]

    def end_combat(self):
        self.is_combat = False
        self.combat_order = []
        self.current_turn_index = 0

    def set_scene(self, scene_description):
        self.current_scene = scene_description

    # ── Oyuncu Status Effects ──

    def add_player_status(self, player_name, effect_type, turns_left, **extra):
        """Oyuncuya status effect ekler."""
        if player_name not in self.player_status_effects:
            self.player_status_effects[player_name] = []
        effect = {"type": effect_type, "turns_left": turns_left}
        effect.update(extra)
        self.player_status_effects[player_name].append(effect)

    def tick_player_statuses(self, player_name):
        """Tur sonu: oyuncu status effect sürelerini azalt."""
        effects = self.player_status_effects.get(player_name, [])
        remaining = []
        for se in effects:
            se["turns_left"] -= 1
            if se["turns_left"] > 0:
                remaining.append(se)
        self.player_status_effects[player_name] = remaining

    def is_player_stunned(self, player_name):
        """Oyuncu stunned mı?"""
        for se in self.player_status_effects.get(player_name, []):
            if se["type"] == "stun" and se.get("turns_left", 0) > 0:
                return True
        return False

    def get_player_dot_damage(self, player_name):
        """Oyuncunun bu tur alacağı DoT hasarını hesaplar."""
        total = 0
        for se in self.player_status_effects.get(player_name, []):
            if se["type"] == "dot" and se.get("turns_left", 0) > 0:
                total += se.get("dot_damage", 0)
        return total

    # ── Skill Cooldowns ──

    def start_skill_cooldown(self, player_name, skill_id, cooldown_turns):
        """Skill cooldown başlat."""
        if cooldown_turns <= 0:
            return
        if player_name not in self.skill_cooldowns:
            self.skill_cooldowns[player_name] = {}
        self.skill_cooldowns[player_name][skill_id] = cooldown_turns

    def tick_skill_cooldowns(self, player_name):
        """Tur sonu: tüm skill cooldown'ları 1 azalt."""
        cds = self.skill_cooldowns.get(player_name, {})
        to_remove = []
        for skill_id, remaining in cds.items():
            cds[skill_id] = remaining - 1
            if cds[skill_id] <= 0:
                to_remove.append(skill_id)
        for key in to_remove:
            del cds[key]

    def get_skill_cooldown(self, player_name, skill_id):
        """Skill'in kalan cooldown turunu döner, 0 = kullanılabilir."""
        return self.skill_cooldowns.get(player_name, {}).get(skill_id, 0)

    def get_all_skill_cooldowns(self, player_name):
        """Tüm cooldown'ları döner: {skill_id: remaining_turns}."""
        return dict(self.skill_cooldowns.get(player_name, {}))

    # ── State Summary ──

    def get_state_summary(self):
        if self.is_combat and self.active_encounter:
            from game.encounter_manager import get_encounter_status_for_prompt
            combat_status = get_encounter_status_for_prompt(self.active_encounter)
        elif self.is_combat and self.combat_order:
            current_name = self.combat_order[self.current_turn_index][0]
            combat_status = f"Combat: Active | Current Turn: {current_name}"
        else:
            combat_status = "Combat: None"

        player_names = ", ".join([c['name'] for c in self.characters]) if self.characters else "No players"
        node_info = f"\nCurrent Location: {self.current_node}" if self.current_node else ""

        return (
            f"[CURRENT GAME STATE]\n"
            f"Scene: {self.current_scene}\n"
            f"Players: {player_names}\n"
            f"{combat_status}"
            f"{node_info}"
        )