"""
Deterministic Turkish post-editing for model output.

Small models often break the suffixes on proper nouns ending in a vowel:
"Lira'ın" → "Lira'nın", "Lira'a" → "Lira'ya", "Lira'ı" → "Lira'yı", and get
vowel harmony wrong ("Mira'in"). These rules are purely orthographic, so they
can be fixed reliably after generation.
"""

from __future__ import annotations

import re

VOWELS = "aeıioöuüâîûAEIİOÖUÜÂÎÛ"
BACK = set("aıouâûAIOUÂÛ")
ROUND = set("oöuüOÖUÜûÛ")

_NAME_SUFFIX = re.compile(r"\b([A-ZÇĞİÖŞÜ][\wçğıöşüâîû]*?)(['’])([a-zçğıöşü]+)\b")


def _last_vowel(word: str) -> str | None:
    for ch in reversed(word):
        if ch in VOWELS:
            return ch.lower()
    return None


def _harmony4(v: str) -> str:
    if v in "aıâ":
        return "ı"
    if v in "ei":
        return "i"
    if v in "ouû":
        return "u"
    return "ü"


def _harmony2(v: str) -> str:
    return "a" if v in "aıouâû" else "e"


GENITIVE = {"ın", "in", "un", "ün", "nın", "nin", "nun", "nün"}
ACCUS = {"ı", "i", "u", "ü", "yı", "yi", "yu", "yü"}
DATIVE = {"a", "e", "ya", "ye"}


def _fix_one(name: str, suffix: str) -> str | None:
    """Return the corrected suffix for name+suffix, or None to keep as is."""
    v = _last_vowel(name)
    if v is None:
        return None
    ends_vowel = name[-1] in VOWELS
    h4, h2 = _harmony4(v), _harmony2(v)
    low = suffix.lower()
    # foreign names with a silent final 'e' ("Thorne" = /torn/) legitimately take back-vowel
    # suffixes without a buffer consonant ("Thorne'un") — trust the model there
    if name[-1] in "eE" and low[:1] in ("u", "ı", "a", "o"):
        return None
    # genitive + optional continuation ("'nın", "'ın", "'nınki")
    m = re.match(r"^(n?)([ıiuü])n(.*)$", low)
    if m:
        tail = m.group(3)
        return ("n" if ends_vowel else "") + h4 + "n" + tail
    # dative ('a', 'ya', 'ya' + nothing else)
    m = re.match(r"^(y?)([ae])$", low)
    if m:
        return ("y" if ends_vowel else "") + h2
    # accusative ('ı', 'yı')
    m = re.match(r"^(y?)([ıiuü])$", low)
    if m:
        return ("y" if ends_vowel else "") + h4
    return None


def fix_name_suffixes(text: str, names: list[str] | None = None) -> str:
    """Fix case suffixes after apostrophes on capitalised names (optionally restricted to ``names``)."""
    allowed = {n.split()[0] for n in (names or [])} | {n for n in (names or [])}

    def repl(m: re.Match) -> str:
        name, apos, suffix = m.group(1), m.group(2), m.group(3)
        if allowed and name not in allowed:
            return m.group(0)
        if len(name) < 2 or name.isupper():
            return m.group(0)
        fixed = _fix_one(name, suffix)
        if fixed is None or fixed == suffix:
            return m.group(0)
        return f"{name}{apos}{fixed}"

    return _NAME_SUFFIX.sub(repl, text)


_SENT_END = re.compile(r"[.!?…»\"”)]\s*$")


def trim_to_sentence(text: str) -> str:
    """If generation was cut mid-sentence, drop the dangling fragment."""
    t = text.rstrip()
    if not t or _SENT_END.search(t):
        return t
    last = max(t.rfind(". "), t.rfind("! "), t.rfind("? "), t.rfind(".\n"), t.rfind("!\n"), t.rfind("?\n"),
               t.rfind(".\""), t.rfind("!\""), t.rfind("?\""), t.rfind(".”"))
    if last < len(t) * 0.5:
        return t + "…"
    cut = t[: last + 2].rstrip()
    return cut


_BIRER = re.compile(r"\b([Bb])irer\b(?!\s+(?:birer|tane|adet))")


_BIRERER = re.compile(r"\b([Bb])irer(?:er)+\b")


def fix_common_tics(text: str) -> str:
    """Model-specific Turkish tics. Gemma overuses distributive 'birer' where plain 'bir' is meant."""
    text = _BIRERER.sub(lambda m: m.group(1) + "ir", text)
    return _BIRER.sub(lambda m: m.group(1) + "ir", text)
