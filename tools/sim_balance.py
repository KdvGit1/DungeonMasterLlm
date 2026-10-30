"""Combat balance report: python -m tools.sim_balance [battles]"""

import statistics
import sys
from collections import Counter

from dndm.game.combat.autoplay import simulate
from dndm.game.combat.engine import CombatEngine
from tests.test_combat import SCENARIOS, party


def main(n: int = 200) -> None:
    print(f"{'senaryo':32} {'zafer':>6} {'yenilgi':>7} {'kaçış':>5} {'tur':>5} {'PC ölüm':>8} {'PC düşme':>8}")
    for label, level, specs in SCENARIOS:
        res = Counter()
        rounds, deaths, downs = [], 0, 0
        for _ in range(n):
            p = party(4, level)
            eng = CombatEngine(CombatEngine.build(specs, p), p)
            res[simulate(eng)] += 1
            rounds.append(eng.enc.round)
            deaths += sum(1 for c in p.values() if c.dead)
            downs += sum(1 for ev in eng.enc.log if ev.type == "down")
        print(f"{label:32} {res['victory'] / n:6.0%} {res['defeat'] / n:7.0%} {res['fled'] / n:5.0%} "
              f"{statistics.mean(rounds):5.1f} {deaths / n:8.2f} {downs / n:8.2f}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
