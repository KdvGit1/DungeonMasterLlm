"""
Dice engine.

The server is the single source of truth for every roll. Each roll returns the
individual dice (sides + face value) so the table view can animate real dice
landing on exactly those faces.

Notation: ``2d6+3``, ``d20``, ``1d20-1``, ``4d6kh3`` (keep highest 3),
``2d20kl1`` (keep lowest), ``1d8+1d6+2``.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Literal

Advantage = Literal["none", "advantage", "disadvantage"]

_TERM_RE = re.compile(r"([+-])?\s*(?:(\d*)d(\d+)(?:(kh|kl)(\d+))?|(\d+))", re.I)
VALID_SIDES = {2, 3, 4, 6, 8, 10, 12, 20, 100}

_rng: random.Random = random.SystemRandom()


def set_rng(rng: random.Random) -> None:
    """Swap the RNG (tests use a seeded ``random.Random``)."""
    global _rng
    _rng = rng


def get_rng() -> random.Random:
    return _rng


@dataclass
class Die:
    sides: int
    value: int
    kept: bool = True

    def to_dict(self) -> dict:
        return {"sides": self.sides, "value": self.value, "kept": self.kept}


@dataclass
class DiceRoll:
    notation: str
    dice: list[Die] = field(default_factory=list)
    modifier: int = 0
    total: int = 0

    @property
    def kept_values(self) -> list[int]:
        return [d.value for d in self.dice if d.kept]

    @property
    def natural(self) -> int | None:
        """Face of the kept d20 for single-d20 rolls (crit / fumble detection)."""
        d20s = [d for d in self.dice if d.sides == 20 and d.kept]
        return d20s[0].value if len(d20s) == 1 else None

    def to_dict(self) -> dict:
        return {"notation": self.notation, "dice": [d.to_dict() for d in self.dice],
                "modifier": self.modifier, "total": self.total, "natural": self.natural}


class DiceError(ValueError):
    pass


def parse(notation: str) -> list[tuple[int, int, int, str | None, int | None]]:
    """Return terms as (sign, count, sides, keep_mode, keep_n); constants have sides=0."""
    s = notation.replace(" ", "").lower()
    if not s:
        raise DiceError("empty notation")
    pos = 0
    terms = []
    while pos < len(s):
        m = _TERM_RE.match(s, pos)
        if not m or m.end() == pos:
            raise DiceError(f"bad dice notation: {notation!r}")
        sign = -1 if m.group(1) == "-" else 1
        if pos > 0 and m.group(1) is None:
            raise DiceError(f"missing operator in {notation!r}")
        if m.group(6) is not None:
            terms.append((sign, int(m.group(6)), 0, None, None))
        else:
            count = int(m.group(2)) if m.group(2) else 1
            sides = int(m.group(3))
            if sides not in VALID_SIDES:
                raise DiceError(f"d{sides} is not a supported die")
            if not 1 <= count <= 40:
                raise DiceError("dice count must be 1..40")
            keep_mode = m.group(4)
            keep_n = int(m.group(5)) if m.group(5) else None
            if keep_n is not None and not 1 <= keep_n <= count:
                raise DiceError("keep count out of range")
            terms.append((sign, count, sides, keep_mode, keep_n))
        pos = m.end()
    return terms


def roll(notation: str, *, advantage: Advantage = "none") -> DiceRoll:
    """Roll dice notation. ``advantage`` applies to a lone ``1d20`` term (rolls 2, keeps one)."""
    terms = parse(notation)
    result = DiceRoll(notation=notation)
    total = 0
    for sign, count, sides, keep_mode, keep_n in terms:
        if sides == 0:
            result.modifier += sign * count
            total += sign * count
            continue
        if sides == 20 and count == 1 and keep_mode is None and advantage != "none":
            count, keep_mode, keep_n = 2, ("kh" if advantage == "advantage" else "kl"), 1
        dice = [Die(sides, _rng.randint(1, sides)) for _ in range(count)]
        if keep_mode:
            order = sorted(range(count), key=lambda i: dice[i].value, reverse=(keep_mode == "kh"))
            keep_idx = set(order[:keep_n])
            for i, d in enumerate(dice):
                d.kept = i in keep_idx
        total += sign * sum(d.value for d in dice if d.kept)
        result.dice.extend(dice)
    result.total = total
    return result


def roll_d20(modifier: int = 0, advantage: Advantage = "none") -> DiceRoll:
    mod = f"+{modifier}" if modifier >= 0 else str(modifier)
    return roll(f"1d20{mod if modifier else ''}", advantage=advantage)


def average(notation: str) -> float:
    """Expected value (used for monster HP defaults and balancing)."""
    avg = 0.0
    for sign, count, sides, keep_mode, keep_n in parse(notation):
        if sides == 0:
            avg += sign * count
        else:
            n = keep_n if keep_mode else count
            avg += sign * n * (sides + 1) / 2
    return avg


def max_value(notation: str) -> int:
    total = 0
    for sign, count, sides, keep_mode, keep_n in parse(notation):
        n = keep_n if keep_mode else count
        total += sign * (count if sides == 0 else n * sides)
    return total


def double_dice(notation: str) -> str:
    """Critical hit: double the number of dice, keep flat modifiers (5e rule)."""
    out = []
    for sign, count, sides, keep_mode, keep_n in parse(notation):
        op = "-" if sign < 0 else "+"
        if sides == 0:
            out.append(f"{op}{count}")
        else:
            out.append(f"{op}{count * 2}d{sides}")
    s = "".join(out)
    return s[1:] if s.startswith("+") else s
