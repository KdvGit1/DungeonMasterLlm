"""Turkish-aware text helpers."""

from __future__ import annotations

import re
import unicodedata

_TR_UPPER_MAP = str.maketrans({"I": "ı", "İ": "i"})
_FOLD_MAP = str.maketrans({"ı": "i", "ğ": "g", "ş": "s", "ç": "c", "ö": "o", "ü": "u",
                           "â": "a", "î": "i", "û": "u"})


def tr_lower(s: str) -> str:
    """Lowercase with Turkish dotted/dotless i rules."""
    return s.translate(_TR_UPPER_MAP).lower()


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def fold(s: str) -> str:
    """Lowercase + strip Turkish diacritics, for forgiving matching ('PASLI' == 'paslı')."""
    s = tr_lower(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.translate(_FOLD_MAP)


def norm_key(s: str) -> str:
    """Fold and collapse to word characters only."""
    return re.sub(r"[^a-z0-9]+", " ", fold(s)).strip()


def similar(a: str, b: str) -> bool:
    """True if one folded string contains the other (names, items)."""
    fa, fb = norm_key(a), norm_key(b)
    return bool(fa and fb) and (fa == fb or fa in fb or fb in fa)
