"""
Core 5e-style rules: abilities, skills, proficiency, checks.

Turkish display names live next to the ids so UI and narration share them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dndm.rules.dice import Advantage, DiceRoll, roll_d20

ABILITIES = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]

ABILITY_TR = {
    "strength": "Güç", "dexterity": "Çeviklik", "constitution": "Dayanıklılık",
    "intelligence": "Zeka", "wisdom": "Bilgelik", "charisma": "Karizma",
}
ABILITY_SHORT_TR = {
    "strength": "GÜÇ", "dexterity": "ÇEV", "constitution": "DAY",
    "intelligence": "ZEK", "wisdom": "BİL", "charisma": "KAR",
}

SKILL_ABILITY = {
    "athletics": "strength",
    "acrobatics": "dexterity", "sleight_of_hand": "dexterity", "stealth": "dexterity",
    "arcana": "intelligence", "history": "intelligence", "investigation": "intelligence",
    "nature": "intelligence", "religion": "intelligence",
    "animal_handling": "wisdom", "insight": "wisdom", "medicine": "wisdom",
    "perception": "wisdom", "survival": "wisdom",
    "deception": "charisma", "intimidation": "charisma", "performance": "charisma", "persuasion": "charisma",
}

SKILL_TR = {
    "athletics": "Atletizm", "acrobatics": "Akrobasi", "sleight_of_hand": "El Çabukluğu",
    "stealth": "Gizlilik", "arcana": "Arkana", "history": "Tarih", "investigation": "Araştırma",
    "nature": "Doğa", "religion": "Din", "animal_handling": "Hayvan İdaresi", "insight": "Sezgi",
    "medicine": "Tıp", "perception": "Algı", "survival": "Hayatta Kalma", "deception": "Aldatma",
    "intimidation": "Gözdağı", "performance": "Gösteri", "persuasion": "İkna",
}

DC_LADDER = [(5, "çok kolay"), (10, "kolay"), (15, "orta"), (20, "zor"), (25, "çok zor"), (30, "neredeyse imkânsız")]

Degree = Literal["critical_success", "success", "failure", "critical_failure"]
DEGREE_TR = {
    "critical_success": "KRİTİK BAŞARI", "success": "BAŞARILI",
    "failure": "BAŞARISIZ", "critical_failure": "KRİTİK BAŞARISIZLIK",
}


def modifier(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    return 2 + (max(1, level) - 1) // 4


def dc_label(dc: int) -> str:
    label = DC_LADDER[0][1]
    for threshold, name in DC_LADDER:
        if dc >= threshold:
            label = name
    return label


def skill_or_ability_name(key: str) -> str:
    return SKILL_TR.get(key) or ABILITY_TR.get(key) or key


def ability_for(key: str) -> str:
    """Skill → governing ability; ability → itself."""
    if key in SKILL_ABILITY:
        return SKILL_ABILITY[key]
    if key in ABILITIES:
        return key
    raise KeyError(f"unknown skill/ability: {key}")


@dataclass
class CheckResult:
    key: str               # skill or ability id
    dc: int
    roll: DiceRoll
    bonus: int
    total: int
    degree: Degree
    advantage: Advantage

    @property
    def success(self) -> bool:
        return self.degree in ("critical_success", "success")

    @property
    def natural(self) -> int | None:
        return self.roll.natural

    def summary_tr(self, who: str) -> str:
        sign = "+" if self.bonus >= 0 else "-"
        adv = {"advantage": " (avantajlı)", "disadvantage": " (dezavantajlı)"}.get(self.advantage, "")
        return (f"{who} — {skill_or_ability_name(self.key)} ZS {self.dc}{adv}: "
                f"zar {self.natural} {sign} {abs(self.bonus)} = {self.total} → {DEGREE_TR[self.degree]}")

    def summary_en(self, who: str) -> str:
        adv = {"advantage": " with advantage", "disadvantage": " with disadvantage"}.get(self.advantage, "")
        return (f"{who} — {self.key} check DC {self.dc}{adv}: natural {self.natural}, "
                f"total {self.total} → {self.degree.upper().replace('_', ' ')}")

    def to_dict(self) -> dict:
        return {"key": self.key, "name": skill_or_ability_name(self.key), "dc": self.dc,
                "roll": self.roll.to_dict(), "bonus": self.bonus, "total": self.total,
                "degree": self.degree, "degree_tr": DEGREE_TR[self.degree],
                "success": self.success, "advantage": self.advantage}


def combine_advantage(*sources: Advantage) -> Advantage:
    """5e: any advantage + any disadvantage cancel out to a straight roll."""
    has_adv = "advantage" in sources
    has_dis = "disadvantage" in sources
    if has_adv and not has_dis:
        return "advantage"
    if has_dis and not has_adv:
        return "disadvantage"
    return "none"


def resolve_check(bonus: int, dc: int, *, key: str, advantage: Advantage = "none",
                  nat_crits: bool = True) -> CheckResult:
    """
    Roll d20 + bonus vs DC.

    House rule (``nat_crits``): a natural 20 always succeeds (critical), a natural 1
    always fails (critical) — more dramatic at the table than strict 5e.
    """
    r = roll_d20(bonus, advantage)
    nat = r.natural or 0
    total = r.total
    if nat_crits and nat == 20:
        degree: Degree = "critical_success"
    elif nat_crits and nat == 1:
        degree = "critical_failure"
    elif total >= dc:
        degree = "critical_success" if total >= dc + 10 else "success"
    else:
        degree = "critical_failure" if total <= dc - 10 else "failure"
    return CheckResult(key=key, dc=dc, roll=r, bonus=bonus, total=total, degree=degree, advantage=advantage)
