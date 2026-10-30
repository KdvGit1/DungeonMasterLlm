from dndm.rules import data


def test_all_data_loads_and_is_consistent():
    problems = data.validate_all()
    assert problems == [], "\n".join(problems)


def test_counts():
    assert len(data.races()) == 9
    assert len(data.classes()) >= 8
    assert len(data.monsters()) >= 40
    assert len(data.items()) >= 80
    assert len(data.spells()) >= 40


def test_turkish_names_present():
    for coll in (data.items(), data.races(), data.classes(), data.spells(), data.monsters()):
        for key, entry in coll.items():
            assert entry.name and entry.name.strip(), key


def test_monster_attack_lookup():
    gob = data.monster("goblin")
    assert gob.attack("scimitar").hit == 4
    assert data.monster("troll").multiattack == ["bite", "claws", "claws"]
