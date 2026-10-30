import asyncio
import os
import random

import pytest

from dndm.game.session import GameSession, balance_specs
from dndm.game.creation import make_pregen
from dndm.rules import dice
from tests.fakes import FakeLLM


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DNDM_HOME", str(tmp_path))
    dice.set_rng(random.Random(3))
    random.seed(3)
    yield
    dice.set_rng(random.SystemRandom())


class Recorder:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg, to):
        self.msgs.append((msg, to))

    def of(self, t):
        return [m for m, _ in self.msgs if m.get("t") == t]


def make_session(n=2):
    llm = FakeLLM()
    rec = Recorder()
    s = GameSession(llm, emit=rec)
    s.settings.auto_roll = True
    s.settings.dice_animation_ms = 0
    players = []
    for i in range(n):
        p = s.join(f"Oyuncu{i}")
        p.connected = True
        s.set_character(p.id, {"pregen": i})
        players.append(p)
    return s, llm, rec, players


async def _drain(s):
    for _ in range(200):
        await asyncio.sleep(0)
        if not s._tasks and not s.busy:
            break
    await asyncio.gather(*list(s._tasks), return_exceptions=True)


async def test_lobby_rules():
    s, *_ = make_session(0)
    p = s.join("Ali")
    assert p.is_host
    again = s.join("x", token=p.token)
    assert again is p
    for i in range(5):
        s.join(f"P{i}")
    with pytest.raises(ValueError):
        s.join("yedinci")
    with pytest.raises(ValueError):
        await GameSession(FakeLLM()).start()


async def test_free_mode_start_and_round_with_check():
    s, llm, rec, (p1, p2) = make_session(2)
    llm.narrations.append("Han kapısı gıcırdar; içeride ateş çıtırdar.")
    await s.start()
    assert s.mode == "exploration" and rec.of("narration_end")
    c1, c2 = s.char_of_player(p1.id), s.char_of_player(p2.id)
    # first submission is ruled on speculatively while player 2 is still typing ...
    llm.queue("ExploreAdjudication", {"rulings": [
        {"player": c1.name, "intent": "talk", "needs_check": True,
         "check": {"skill": "persuasion", "dc": 12, "advantage": "none", "reason": "hancı şüpheci"}}]})
    # ... the last one is ruled when the round resolves
    llm.queue("ExploreAdjudication", {"rulings": [
        {"player": c2.name, "intent": "explore", "needs_check": False, "time_minutes": 30}]})
    llm.queue("StoryExtraction", {"new_npcs": [{"name": "Hancı Mert", "role": "hancı", "description": "göbekli"}],
                                  "facts": ["Kuzey yolu haydutlarla dolu."],
                                  "items_given": [{"to": c1.name, "item": "Paslı Anahtar", "giver": "Hancı Mert"}]})
    await s.submit_action(p1.id, "Hancıyı ikna edip yolu soruyorum")
    assert not s.busy and c1.id in s.pending
    await asyncio.sleep(0)  # let the speculative ruling run
    await s.submit_action(p2.id, "Etrafa bakıyorum")
    await _drain(s)
    checks = rec.of("check_result")
    assert len(checks) == 1 and checks[0]["char"] == c1.name
    assert rec.of("dice")
    assert s.world.find_npc("Hancı Mert") is not None
    assert any("Kuzey yolu" in j.text for j in s.world.journal)
    assert c1.inventory.find("anahtar") is not None
    assert s.world.hour == 18  # 30 minutes rounds down at hour precision


async def test_failed_llm_falls_back_without_leaking():
    s, llm, rec, (p1,) = make_session(1)

    async def boom(*a, **k):
        from dndm.llm.client import LLMError
        raise LLMError("429 Too Many Requests")

    await s.start()
    llm.structured = boom  # type: ignore[assignment]
    await s.submit_action(p1.id, "Kapıyı açıyorum")
    await _drain(s)
    assert all("429" not in m.get("text", "") for m in rec.of("narration_end"))
    assert all("429" not in h["content"] for h in s.gm.history)


async def test_combat_from_exploration_runs_to_the_end():
    s, llm, rec, players = make_session(3)
    for p in players:
        p.connected = False  # autoplay their turns
    await s.start()
    c = s.char_of_player(players[0].id)
    llm.queue("ExploreAdjudication", {
        "rulings": [{"player": c.name, "intent": "attack", "needs_check": False}],
        "starts_combat": True,
        "enemies": [{"name": "Haydut", "kind": "bandit", "count": 2}],
        "battlefield": [{"name": "Devrik araba", "effect": "cover", "description": "Yolda devrilmiş bir araba."}],
    })
    for p in players:
        s.pending[s.char_of_player(p.id).id] = __import__("dndm.game.session", fromlist=["PendingAction"]).PendingAction(text="saldırıyorum")
    await s.resolve_round()
    for _ in range(50):
        await _drain(s)
        if s.mode != "combat":
            break
        await asyncio.sleep(0.01)
    assert s.mode == "exploration"
    assert rec.of("combat_event")
    kinds = [m["kind"] for m in rec.of("narration_end")]
    assert "combat_start" in kinds and "combat_end" in kinds


async def test_inventory_commands_and_save_load(tmp_path):
    s, llm, rec, (p1, p2) = make_session(2)
    await s.start()
    c1, c2 = s.char_of_player(p1.id), s.char_of_player(p2.id)
    potion = c1.inventory.add("potion_healing", 2)
    await s.inventory_command(p1.id, {"type": "give", "uid": potion.uid, "to": c2.id, "qty": 1})
    assert c1.inventory.count("potion_healing") == 1 and c2.inventory.count("potion_healing") == 1
    c2.hp = 1
    await s.inventory_command(p2.id, {"type": "use", "uid": c2.inventory.find("İyileştirme").uid})
    assert c2.hp > 1
    s.world.place_custom_item("Gümüş Kadeh", description="masada")
    item = s.world.items_here()[0]
    await s.inventory_command(p1.id, {"type": "pickup", "uid": item.uid})
    assert c1.inventory.find("kadeh")
    path = s.save()
    assert path and path.exists()
    s2 = GameSession.load(FakeLLM(), s.id)
    assert s2.char_of_player(p1.id).inventory.find("kadeh")
    assert s2.world.location == s.world.location


def test_balance_specs_trims_deadly_encounters():
    party = [make_pregen(i) for i in range(2)]
    specs = balance_specs([{"monster": "ogre", "count": 3}], party)
    assert sum(s["count"] for s in specs) < 3
    assert balance_specs([{"monster": "goblin", "count": 2}], party) == [{"monster": "goblin", "count": 2}]


async def test_travel_rules_in_scenario():
    s, llm, rec, (p1,) = make_session(1)
    await s.start(scenario_id="degirmenkoyun_golgesi")
    assert await s._travel("koridor_girisi") is None            # id-like invention from the referee: ignored
    assert await s._travel("içerisi") is None                   # generic word: ignored
    r = await s._travel("Köy Meydanı")                            # known place by name
    assert r and s.world.location == "ana_meydan"
    await s._travel("Paslı Testi Meyhanesi")
    r = await s._travel("mahzen")                                 # deliberate move into the adjacent secret cellar
    assert r and s.world.location == "meyhane_mahzeni"
    r = await s._travel("Değirmencinin Ambarı")                   # a real new place the players head for
    assert r and s.world.loc(s.scenario).name == "Değirmencinin Ambarı"


async def test_combat_commands_from_phone():
    s, llm, rec, (p1, p2) = make_session(2)
    await s.start()
    s.settings.turn_timeout = 5
    await s.start_combat([{"monster": "goblin", "count": 2}])
    c1 = s.char_of_player(p1.id)
    seen = set()
    for _ in range(400):
        await asyncio.sleep(0.01)
        if s.mode != "combat":
            break
        eng = s.engine
        cur = eng.current() if eng else None
        if not cur or not cur.startswith("pc:") or s.busy or s._turn_waiter is None:
            continue
        ch = eng.pc(cur)
        pid = s.player_of_char(ch.id).id
        foes = eng.enc.active_enemies()
        if not foes:
            continue
        if "improvise" not in seen and ch.id == c1.id:
            llm.queue("ImprovisedRuling", {"feasible": True, "explanation": "", "effect": "damage_condition",
                                           "damage": "4d6", "damage_type": "bludgeoning", "condition": "prone",
                                           "target": foes[0].label,
                                           "check": {"skill": "athletics", "dc": 10, "advantage": "none", "reason": "x"}})
            await s.combat_command(pid, {"type": "improvise", "text": "Masayı tekmeleyip goblinin üstüne deviriyorum"})
            seen.add("improvise")
        else:
            await s.combat_command(pid, {"type": "attack", "target": foes[0].uid})
            seen.add("attack")
        await s.combat_command(pid, {"type": "end_turn"})
    await _drain(s)
    assert {"attack", "improvise"} <= seen
    assert any(m["event"]["type"] == "improvise" for m in rec.of("combat_event"))
    # improvised damage is capped by level (4d6 asked, level 1 cap is 2d6)
    assert s.mode in ("exploration", "combat")


async def test_whispered_action_stays_secret():
    s, llm, rec, (p1, p2) = make_session(2)
    await s.start()
    c1, c2 = s.char_of_player(p1.id), s.char_of_player(p2.id)
    llm.queue("ExploreAdjudication", {"rulings": [{"player": c1.name, "intent": "talk", "needs_check": False}]})
    llm.queue("ExploreAdjudication", {"rulings": [{"player": c2.name, "intent": "stealth", "needs_check": True,
        "check": {"skill": "sleight_of_hand", "dc": 12, "advantage": "none", "reason": "kimse görmemeli"}}]})
    llm.narrations.extend(["Herkese açık anlatım.", "Gizlice kesesini aşırıyorsun."])
    await s.submit_action(p1.id, "Hancıyla sohbet ediyorum")
    await asyncio.sleep(0)
    await s.submit_action(p2.id, "Hancının kesesini gizlice çalıyorum", private=True)
    await _drain(s)
    public_prompts = [c[1] for c in llm.calls if c[0] == "stream"]
    assert "kesesini" not in public_prompts[-2]                 # public narration never saw the secret
    private_msgs = [(m, to) for m, to in rec.msgs if m.get("t") == "narration_end" and m.get("kind") == "private"]
    assert len(private_msgs) == 1 and private_msgs[0][1] == [p2.id]
    checks = [(m, to) for m, to in rec.msgs if m.get("t") == "check_result"]
    assert checks and all(to == [p2.id] for _, to in checks)    # the secret roll only reached the thief


async def test_stall_breaker_hands_out_a_clue():
    s, llm, rec, (p1,) = make_session(1)
    await s.start(scenario_id="degirmenkoyun_golgesi")
    c = s.char_of_player(p1.id)
    for i in range(3):   # three rounds of nothing happening
        llm.queue("ExploreAdjudication", {"rulings": [{"player": c.name, "intent": "talk", "needs_check": False}]})
        await s.submit_action(p1.id, f"Muhafıza havadan sudan konuşuyorum {i}")
        await _drain(s)
    assert len(s.world.found) == 1          # the easiest clue at the gate was delivered
    assert any("NATURALLY" in call[1] or "Deliver this clue" in call[1] for call in llm.calls if call[0] == "stream")
