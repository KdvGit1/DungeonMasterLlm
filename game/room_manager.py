"""
game/room_manager.py — Multiplayer room/lobby system.

A Room holds multiple players, tracks turn submissions, and manages
round-based gameplay where the GM responds to all players at once.
"""

import random
import string
import threading
from game.game_state import GameState


class Room:
    """A multiplayer game room."""

    def __init__(self, room_code, host_username):
        self.room_code = room_code
        self.host_username = host_username

        # {username: character_dict}
        self.players = {}

        # Game infrastructure
        self.game_state = GameState()
        self.scenario_manager = None
        self.session_id = None
        self.game_started = False

        # Turn tracking: {username: action_string or "__PASS__"}
        self.current_round_actions = {}
        self.processing_actions = {}

        # Latest round results (so joining/polling clients can read them)
        self.last_round_result = None

        # Round counter
        self.round_number = 0

        # True while _process_round is running (LLM call in progress)
        self.round_processing = False

        self._lock = threading.Lock()

    # ── Player management ────────────────────────────────────

    def add_player(self, username, character):
        """Add a player with their character to the room."""
        with self._lock:
            self.players[username] = character
            self.game_state.add_player({"username": username}, character)

    def remove_player(self, username):
        """Remove a player from the room."""
        with self._lock:
            self.players.pop(username, None)
            # Also remove any pending action
            self.current_round_actions.pop(username, None)

    def get_player_names(self):
        """Return list of character names."""
        return [c["name"] for c in self.players.values()]

    def get_username_for_character(self, char_name):
        """Find username by character name."""
        for username, char in self.players.items():
            if char["name"].lower() == char_name.lower():
                return username
        return None

    def get_character_for_username(self, username):
        """Get character dict for a username."""
        return self.players.get(username)

    # ── Turn management ──────────────────────────────────────

    def submit_action(self, username, action):
        """Player submits their action for this round."""
        with self._lock:
            if username not in self.players:
                return False
            self.current_round_actions[username] = action
            return True

    def pass_turn(self, username):
        """Player passes their turn this round."""
        with self._lock:
            if username not in self.players:
                return False
            self.current_round_actions[username] = "__PASS__"
            return True

    def all_actions_submitted(self):
        """Check if every player has acted or passed."""
        with self._lock:
            return len(self.current_round_actions) >= len(self.players) and len(self.players) > 0

    def consume_round_actions(self):
        """Return all actions and clear for next round."""
        with self._lock:
            actions = dict(self.current_round_actions)
            self.processing_actions = dict(self.current_round_actions)
            self.current_round_actions.clear()
            self.round_number += 1
            return actions

    def get_submission_status(self):
        """Return who has submitted (with action text) and who hasn't."""
        with self._lock:
            submitted = {}
            source_actions = self.processing_actions if self.round_processing else self.current_round_actions
            for u in source_actions:
                char = self.players.get(u)
                pname = char["name"] if char else u
                action = source_actions[u]
                submitted[pname] = "PASS" if action == "__PASS__" else action
            
            if self.round_processing:
                waiting_for = []
            else:
                waiting_for = [u for u in self.players if u not in source_actions]
                
            return {
                "submitted": submitted,
                "waiting_for": waiting_for,
                "total_players": len(self.players),
                "all_ready": len(source_actions) >= len(self.players) and len(self.players) > 0,
            }

    def has_user_submitted(self, username):
        """Check if a specific user has submitted this round."""
        with self._lock:
            return username in self.current_round_actions


# ═══════════════════════════════════════════════════════════════════════
# GLOBAL ROOM REGISTRY
# ═══════════════════════════════════════════════════════════════════════

_rooms = {}          # {room_code: Room}
_rooms_lock = threading.Lock()
_user_rooms = {}     # {username: room_code}  — track which room each user is in


def _generate_code(length=4):
    """Generate a random room code like 'A3K9'."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(chars, k=length))
        if code not in _rooms:
            return code


def create_room(host_username):
    """Create a new room. Returns the room code."""
    with _rooms_lock:
        code = _generate_code()
        room = Room(code, host_username)
        _rooms[code] = room
        _user_rooms[host_username] = code
        print(f"🏠 Room created: {code} by {host_username}")
        return code


def join_room(room_code, username):
    """Join an existing room (character assigned later). Returns Room or None."""
    with _rooms_lock:
        room = _rooms.get(room_code.upper())
        if room is None:
            return None
        if room.game_started and username not in room.players:
            return None  # Can't join an already-started game
        _user_rooms[username] = room_code.upper()
        return room


def get_room(room_code):
    """Get a room by code."""
    return _rooms.get(room_code.upper()) if room_code else None


def get_room_for_user(username):
    """Get the room a user is currently in."""
    code = _user_rooms.get(username)
    if code:
        return _rooms.get(code)
    return None


def get_room_code_for_user(username):
    """Get the room code a user is currently in."""
    return _user_rooms.get(username)


def leave_room(username):
    """Remove a user from their current room."""
    with _rooms_lock:
        code = _user_rooms.pop(username, None)
        if code and code in _rooms:
            _rooms[code].remove_player(username)
            # If room is empty, clean it up
            if not _rooms[code].players:
                _rooms.pop(code, None)
                print(f"🏠 Room {code} deleted (empty)")
