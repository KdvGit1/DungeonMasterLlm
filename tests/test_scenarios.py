import pytest

from dndm.paths import scenarios_dir
from dndm.world.scenario import list_scenarios, load_scenario
from dndm.world.state import WorldState
from dndm.world.validate import lore_problems, validate

SCENARIOS = sorted(p.name for p in scenarios_dir().iterdir() if (p / "scenario.yaml").exists())


def test_there_are_scenarios():
    assert SCENARIOS
    listed = list_scenarios()
    assert all(not s.get("broken") for s in listed), listed


@pytest.mark.parametrize("sid", SCENARIOS)
def test_scenario_is_valid_and_classic(sid):
    sc = load_scenario(scenarios_dir() / sid)
    problems = validate(sc)
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("sid", SCENARIOS)
def test_scenario_is_explorable(sid):
    sc = load_scenario(scenarios_dir() / sid)
    ws = WorldState.from_scenario(sc)
    # the start shows some visible exits and every hidden place has a way to be revealed
    assert ws.exits(sc), "start location has no visible exits"
    hidden = {lid for lid, loc in sc.locations.items() if loc.hidden}
    revealers = {t for loc in sc.locations.values() for d in loc.discoveries for t in d.leads_to}
    adjacent = {ex for loc in sc.locations.values() for ex in loc.exits}  # findable by deliberate exploration
    for lid in hidden:
        assert lid in revealers or lid in adjacent, f"hidden place {lid} can never be found"
    # lots to discover
    assert sum(len(l.discoveries) for l in sc.locations.values()) >= len(sc.locations)
    # multiple endings and at least one threat clock (the world moves on its own)
    assert len(sc.endings) >= 2 and sc.fronts


def test_lore_checker_catches_genre_breaks():
    from dndm.world.scenario import Location, Scenario
    sc = Scenario(title="x", pitch="Uzay gemisi ile gelen robotlar", premise="Waterdeep sokaklarında",
                  start_location="a", locations={"a": Location(name="A", description="Bir telefon çalıyor")})
    probs = lore_problems(sc)
    assert any("uzay gemisi" in p for p in probs)
    assert any("telefon" in p for p in probs)
    assert any("waterdeep" in p for p in probs)
