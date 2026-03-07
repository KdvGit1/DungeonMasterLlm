class GameState:
    def __init__(self):
        # mevcut sahne açıklaması, AI her sahnede bunu günceller
        self.current_scene = "The adventure begins..."

        # oturumdaki oyuncular ve karakterleri
        # örnek: [{"user": {...}, "character": {...}}]
        self.active_players = []
        self.characters = []

        # savaş durumu
        self.is_combat = False

        # savaş sırası, initiative'e göre sıralı liste
        # örnek: [("Aragorn", 18), ("Legolas", 15), ("Goblin", 12)]
        self.combat_order = []

        # şu an kimin sırası olduğunu takip eden index
        self.current_turn_index = 0

        # aktif oturum ID'si, session_manager'dan gelecek
        self.session_id = None

        # kaçıncı tur olduğunu sayar
        self.turn_count = 0

    # ─── OYUNCU EKLEME ─────────────────────────────────────

    def add_player(self, user, character):
        # oyuncuyu ve karakterini listeye ekle
        self.active_players.append(user)
        self.characters.append(character)
        print(f"{character['name']} oyuna katıldı.")

    # ─── SAVAŞ BAŞLAT ──────────────────────────────────────

    def start_combat(self, initiative_order):
        # initiative_order: [("Aragorn", 18), ("Goblin", 12)] gibi liste
        # büyükten küçüğe sırala, en yüksek initiative ilk gider
        self.combat_order = sorted(
            initiative_order,
            key=lambda x: x[1],
            reverse=True
        )
        self.is_combat = True
        self.current_turn_index = 0
        self.turn_count = 0
        print("Savaş başladı!")
        print("Sıralama:")
        for name, initiative in self.combat_order:
            print(f"  {name}: {initiative}")

    # ─── SIRAYI İLERLET ────────────────────────────────────

    def next_turn(self):
        if not self.is_combat:
            return None

        self.turn_count += 1

        # % operatörü listeyi döngüsel hale getirir
        # son kişiden sonra tekrar ilk kişiye döner
        self.current_turn_index = (
            self.current_turn_index + 1
        ) % len(self.combat_order)

        current_name = self.combat_order[self.current_turn_index][0]
        print(f"Sıra: {current_name}")
        return current_name

    # ─── SAVAŞI BİTİR ──────────────────────────────────────

    def end_combat(self):
        self.is_combat = False
        self.combat_order = []
        self.current_turn_index = 0
        print("Savaş bitti!")

    # ─── SAHNE GÜNCELLE ────────────────────────────────────

    def set_scene(self, scene_description):
        # AI yeni bir sahne tarif ettiğinde burası güncellenir
        self.current_scene = scene_description

    # ─── DURUM ÖZETİ ───────────────────────────────────────

    def get_state_summary(self):
        # mevcut oyun durumunu string olarak döndürür
        # system_prompt.py bunu system prompt'a ekleyecek

        # savaş durumu
        if self.is_combat and self.combat_order:
            current_name = self.combat_order[self.current_turn_index][0]
            combat_status = (
                f"Combat: Active\n"
                f"Turn Order: {', '.join([name for name, _ in self.combat_order])}\n"
                f"Current Turn: {current_name}\n"
                f"Round: {self.turn_count}"
            )
        else:
            combat_status = "Combat: None"

        # oyuncu listesi
        player_names = ", ".join(
            [c['name'] for c in self.characters]
        ) if self.characters else "No players"

        summary = (
            f"[CURRENT GAME STATE]\n"
            f"Scene: {self.current_scene}\n"
            f"Players: {player_names}\n"
            f"{combat_status}"
        )

        return summary