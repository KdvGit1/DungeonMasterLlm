"""
Model benchmark for DnD Master.

Usage:
    python -m tools.bench.run_bench MODEL [MODEL ...] [--runs 2] [--out .runtime/bench]

Writes one JSON file per model with every raw output plus automatic scores.
Narration quality (Turkish fluency, vividness) is judged by reading the outputs;
the automatic scores cover what can be measured mechanically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import time
from pathlib import Path

from dndm.llm.client import LLMError, OllamaClient
from dndm.llm.schemas import Adjudication, Extraction
from tools.bench import cases

REFUSAL_PATTERNS = [
    r"\bI can'?t\b", r"\bI cannot\b", r"\bI'm sorry\b", r"\bas an AI\b", r"\bI won'?t\b",
    r"üzgünüm", r"yapamam", r"yardımcı olamam", r"bir yapay zeka", r"uygun değil", r"içerik politika",
    r"\bcannot fulfill\b", r"\bnot able to\b",
]
EN_STOPWORDS = {"the", "and", "with", "his", "her", "you", "that", "this", "into", "from", "they", "was", "were", "is"}
TR_CHARS = set("çğıöşüÇĞİÖŞÜ")


def word_count(t: str) -> int:
    return len(re.findall(r"\w+", t, re.U))


def english_ratio(t: str) -> float:
    words = re.findall(r"[A-Za-z]+", t)
    if not words:
        return 0.0
    allw = re.findall(r"\w+", t, re.U)
    return sum(1 for w in words if w.lower() in EN_STOPWORDS) / max(1, len(allw))


def refused(t: str) -> bool:
    return any(re.search(p, t, re.I) for p in REFUSAL_PATTERNS)


def vram_used_mb() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:
        return None


def score_ruling(ruling, exp) -> dict:
    s = {}
    if exp.get("needs_check") is not None:
        s["needs_check"] = ruling.needs_check == exp["needs_check"]
    if "skills" in exp and ruling.needs_check and ruling.check:
        s["skill"] = ruling.check.skill in exp["skills"]
        lo, hi = exp["dc"]
        s["dc"] = lo <= ruling.check.dc <= hi
    elif "skills" in exp:
        s["skill"] = False
        s["dc"] = False
    if "starts_combat" in exp:
        s["combat"] = ruling.starts_combat == exp["starts_combat"]
    if "intents" in exp:
        s["intent"] = ruling.intent in exp["intents"]
    return s


async def bench_model(model: str, runs: int, out_dir: Path) -> dict:
    client = OllamaClient(model, num_ctx=8192, timeout=300)
    report: dict = {"model": model, "adjudication": [], "narration": [], "extraction": [], "errors": []}

    # warm-up (load weights) — also measures load time
    t0 = time.perf_counter()
    try:
        await client.complete([{"role": "user", "content": "Merhaba, tek kelimeyle cevap ver."}], max_tokens=5)
    except LLMError as e:
        report["errors"].append(f"warmup: {e}")
        await client.aclose()
        return report
    report["load_seconds"] = round(time.perf_counter() - t0, 1)
    report["vram_mb"] = vram_used_mb()

    # ── Adjudication (structured) ──
    for action, exp in cases.ADJUDICATION_CASES:
        msg = [{"role": "user", "content": f"{cases.WORLD}\nPLAYER ACTIONS:\n{action}"}]
        try:
            adj, res = await client.structured(msg, Adjudication, system=cases.ADJUDICATOR_SYSTEM,
                                               temperature=0.1, max_tokens=400)
            ruling = adj.rulings[0] if adj.rulings else None
            sc = score_ruling(ruling, exp) if ruling else {"empty": False}
            report["adjudication"].append({"action": action, "output": adj.model_dump(), "score": sc,
                                           "seconds": round(res.total_seconds, 2)})
        except LLMError as e:
            report["adjudication"].append({"action": action, "error": str(e), "score": {"valid": False}})

    # ── Narration (streaming) ──
    for name, case in cases.NARRATION_CASES.items():
        for run in range(runs):
            prompt = (f"{cases.WORLD}\nPLAYER ACTIONS THIS ROUND:\n{case['actions']}\n\n"
                      f"RESOLVED OUTCOMES (engine decided, narrate them faithfully):\n{case['outcomes']}\n\n"
                      f"Write the narration now, in Turkish, {case['words'][0]}-{case['words'][1]} words.")
            stats: dict = {}
            chunks = []
            try:
                async for piece in client.stream([{"role": "user", "content": prompt}], system=cases.GM_SYSTEM,
                                                 temperature=0.85, max_tokens=700, stats=stats):
                    chunks.append(piece)
            except LLMError as e:
                report["errors"].append(f"{name}#{run}: {e}")
                continue
            text = "".join(chunks).strip()
            res = stats.get("result")
            wc = word_count(text)
            item = {
                "case": name, "run": run, "text": text, "words": wc,
                "in_range": case["words"][0] <= wc <= case["words"][1] * 1.25,
                "refused": refused(text),
                "english_ratio": round(english_ratio(text), 3),
                "has_tr_chars": any(c in TR_CHARS for c in text),
                "tok_s": round(res.tokens_per_second, 1) if res else None,
                "ttft": round(res.first_token_seconds, 2) if res and res.first_token_seconds else None,
                "prompt_tok_s": round(res.prompt_tokens_per_second, 1) if res else None,
                "prompt_tokens": res.prompt_tokens if res else None,
            }
            if "names" in case:
                item["names_covered"] = sum(1 for n in case["names"] if n in text)
            report["narration"].append(item)

    # ── Extraction (structured) ──
    for run in range(runs):
        try:
            ex, res = await client.structured(
                [{"role": "user", "content": f"Extract story elements from this Turkish GM narration:\n\n"
                                             f"{cases.EXTRACTION_TEXT}"}],
                Extraction, system="You extract structured data from RPG narration. Keep names as written.",
                temperature=0.1, max_tokens=600)
            npcs = {n.name.lower() for n in ex.new_npcs}
            items = " ".join(i.name.lower() for i in ex.items_in_scene)
            places = " ".join(p.lower() for p in ex.places_mentioned)
            exp = cases.EXTRACTION_EXPECT
            sc = {
                "npcs": sum(1 for e in exp["npcs"] if any(e in n for n in npcs)) / len(exp["npcs"]),
                "items": all(e in items for e in exp["items"]),
                "places": all(e in places for e in exp["places"]),
                "no_player_as_npc": not any(n in npcs for n in ("kael", "lira")),
            }
            report["extraction"].append({"output": ex.model_dump(), "score": sc})
        except LLMError as e:
            report["extraction"].append({"error": str(e)})

    report["vram_mb_after"] = vram_used_mb()
    report["summary"] = summarize(report)
    await client.aclose()
    safe = re.sub(r"[^\w.-]+", "_", model)
    (out_dir / f"{safe}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def summarize(r: dict) -> dict:
    adj = r["adjudication"]
    checks = [v for a in adj for v in a.get("score", {}).values()]
    narr = r["narration"]
    tok = [n["tok_s"] for n in narr if n.get("tok_s")]
    ttft = [n["ttft"] for n in narr if n.get("ttft")]
    ptok = [n["prompt_tok_s"] for n in narr if n.get("prompt_tok_s")]
    six = [n.get("names_covered", 0) for n in narr if n["case"] == "six_players"]
    ext = [e["score"] for e in r["extraction"] if "score" in e]
    return {
        "adjudication_accuracy": round(sum(checks) / len(checks), 3) if checks else 0,
        "adjudication_errors": sum(1 for a in adj if "error" in a),
        "narration_refusals": sum(1 for n in narr if n["refused"]),
        "narration_english_ratio_avg": round(sum(n["english_ratio"] for n in narr) / max(1, len(narr)), 3),
        "narration_length_ok": f"{sum(1 for n in narr if n['in_range'])}/{len(narr)}",
        "six_player_names_avg": round(sum(six) / len(six), 2) if six else None,
        "extraction_npc_recall": round(sum(e["npcs"] for e in ext) / len(ext), 2) if ext else None,
        "extraction_items_places": f"{sum(1 for e in ext if e['items'] and e['places'])}/{len(ext)}",
        "gen_tok_s_avg": round(sum(tok) / len(tok), 1) if tok else None,
        "prompt_tok_s_avg": round(sum(ptok) / len(ptok), 1) if ptok else None,
        "ttft_avg": round(sum(ttft) / len(ttft), 2) if ttft else None,
        "load_seconds": r.get("load_seconds"),
        "vram_mb": r.get("vram_mb_after"),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--out", default=".runtime/bench")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for m in args.models:
        print(f"=== {m}", flush=True)
        rep = await bench_model(m, args.runs, out)
        print(json.dumps(rep.get("summary", rep.get("errors")), ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
