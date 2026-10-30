import random
from collections import Counter

import pytest

from dndm.rules import dice
from dndm.rules.core import (combine_advantage, dc_label, modifier, proficiency_bonus,
                             resolve_check)


@pytest.fixture(autouse=True)
def seeded():
    dice.set_rng(random.Random(1234))
    yield
    dice.set_rng(random.SystemRandom())


def test_parse_and_roll_basic():
    r = dice.roll("2d6+3")
    assert len(r.dice) == 2 and all(d.sides == 6 for d in r.dice)
    assert r.total == sum(r.kept_values) + 3
    assert r.modifier == 3


def test_multiple_terms_and_negative():
    r = dice.roll("1d8+1d6-1")
    assert [d.sides for d in r.dice] == [8, 6]
    assert r.total == sum(r.kept_values) - 1


def test_keep_highest():
    r = dice.roll("4d6kh3")
    assert len(r.dice) == 4
    kept = [d for d in r.dice if d.kept]
    dropped = [d for d in r.dice if not d.kept]
    assert len(kept) == 3 and len(dropped) == 1
    assert dropped[0].value <= min(d.value for d in kept)


def test_advantage_keeps_higher_d20():
    for _ in range(200):
        r = dice.roll("1d20+2", advantage="advantage")
        assert len(r.dice) == 2
        assert r.natural == max(d.value for d in r.dice)
        r = dice.roll("1d20", advantage="disadvantage")
        assert r.natural == min(d.value for d in r.dice)


def test_d20_distribution_is_uniform_enough():
    c = Counter(dice.roll("1d20").natural for _ in range(20000))
    assert set(c) == set(range(1, 21))
    assert max(c.values()) - min(c.values()) < 250


@pytest.mark.parametrize("bad", ["", "d7", "2x6", "1d6+", "0d6", "50d6", "3d6kh5", "1d6 2"])
def test_bad_notation(bad):
    with pytest.raises(dice.DiceError):
        dice.roll(bad)


def test_average_max_double():
    assert dice.average("2d6+3") == 10
    assert dice.max_value("1d8+2") == 10
    assert dice.double_dice("2d6+3") == "4d6+3"
    assert dice.double_dice("1d8+1d6") == "2d8+2d6"


def test_modifier_and_proficiency():
    assert [modifier(s) for s in (1, 8, 9, 10, 11, 14, 16, 20)] == [-5, -1, -1, 0, 0, 2, 3, 5]
    assert [proficiency_bonus(l) for l in (1, 4, 5, 9, 13, 17)] == [2, 2, 3, 4, 5, 6]


def test_combine_advantage():
    assert combine_advantage("advantage", "none") == "advantage"
    assert combine_advantage("advantage", "disadvantage") == "none"
    assert combine_advantage("disadvantage", "disadvantage") == "disadvantage"


def test_dc_label():
    assert dc_label(5) == "çok kolay"
    assert dc_label(14) == "kolay"
    assert dc_label(15) == "orta"
    assert dc_label(22) == "zor"


def test_resolve_check_degrees_consistent():
    for _ in range(500):
        c = resolve_check(3, 15, key="stealth")
        nat = c.natural
        if nat == 20:
            assert c.degree == "critical_success"
        elif nat == 1:
            assert c.degree == "critical_failure"
        else:
            assert c.success == (c.total >= 15)
        assert "Gizlilik" in c.summary_tr("Lira")
