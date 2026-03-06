import random

def d4() -> int:
    return random.randint(1, 4)

def d6() -> int:
    return random.randint(1, 6)

def d8() -> int:
    return random.randint(1, 8)

def d10() -> int:
    return random.randint(1, 10)

def d12() -> int:
    return random.randint(1, 12)

def d20() -> int:
    return random.randint(1, 20)

def d100() -> int:
    return random.randint(1, 100)

def roll(count, sides) -> int:
    total = 0
    for i in range(count):
        total += random.randint(1, sides)
    return total

def roll_with_advantage() -> int:
    return max(d20(), d20())

def roll_with_disadvantage() -> int:
    return min(d20(), d20())

def get_modifier(score) -> int:
    return (score - 10) // 2

def ability_check(modifier, dc) -> dict:
    roll_result = d20()
    total = roll_result + modifier
    return {
        "roll": roll_result,
        "modifier": modifier,
        "total": total,
        "dc": dc,
        "success": total >= dc
    }