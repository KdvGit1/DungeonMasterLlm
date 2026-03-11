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

        # Aktif savaş bilgisi
        # {"enemy_name": str, "hp": int, "max_hp": int, "ac": int, "damage_dice": int, "xp_reward": int}
        self.active_encounter = None

        # Eşya alma bekleniyor mu?
        # {"name": str, "rarity": str, "value": int, "dc": int}
        self.pending_item = None

    def add_player(self, user, character):
        self.active_players.append(user)
        self.characters.append(character)
        print(f"{character['name']} oyuna katıldı.")

    def start_encounter(self, encounter_data):
        """Combat.check_combat_start'tan gelen dict ile savaş başlatır."""
        self.active_encounter = encounter_data
        self.is_combat = True
        print(f"\n⚔️  SAVAŞ BAŞLADI: {encounter_data['enemy_name']}")
        print(f"   HP: {encounter_data['hp']}  AC: {encounter_data['ac']}")

    def end_encounter(self):
        self.active_encounter = None
        self.is_combat = False
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

    def get_state_summary(self):
        if self.is_combat and self.active_encounter:
            enc = self.active_encounter
            combat_status = (
                f"Combat: ACTIVE\n"
                f"Enemy: {enc['enemy_name']}  HP: {enc['hp']}/{enc['max_hp']}  AC: {enc['ac']}"
            )
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