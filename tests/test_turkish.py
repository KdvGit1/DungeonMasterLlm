import pytest

from dndm.gm.turkish import fix_name_suffixes, trim_to_sentence
from dndm.text import fold, similar, tr_lower


@pytest.mark.parametrize("bad,good", [
    ("Lira'ın kılıcı", "Lira'nın kılıcı"),
    ("Brenna'ın sesi", "Brenna'nın sesi"),
    ("Mira'in kitabı", "Mira'nın kitabı"),
    ("Lira'a doğru", "Lira'ya doğru"),
    ("Lira'ı gördü", "Lira'yı gördü"),
    ("Pip'ın lavtası", "Pip'in lavtası"),
    ("Kael'in baltası", "Kael'in baltası"),
    ("Borin'in tezgâhı", "Borin'in tezgâhı"),
    ("Dorn'a bakıyor", "Dorn'a bakıyor"),
    ("Lira'nın gözleri", "Lira'nın gözleri"),
    ("Silas'ın tek gözü", "Silas'ın tek gözü"),
    ("Elara'dan uzak", "Elara'dan uzak"),
    ("Thorne'un yayı", "Thorne'un yayı"),
])
def test_suffix_fixer(bad, good):
    assert fix_name_suffixes(bad) == good


def test_suffix_fixer_respects_name_filter():
    assert fix_name_suffixes("Lira'ın ve Ankara'ın", ["Lira Gölgeayak"]) == "Lira'nın ve Ankara'ın"


def test_trim_to_sentence():
    assert trim_to_sentence("Kapı açılır. Içeride bir ses duyulur. Muhafız bağırarak kel") == \
        "Kapı açılır. Içeride bir ses duyulur."
    assert trim_to_sentence("Tamam.") == "Tamam."
    assert trim_to_sentence('"Gel," dedi.') == '"Gel," dedi.'


def test_turkish_casefold_helpers():
    assert tr_lower("IŞIK İzmir") == "ışık izmir"
    assert fold("PASLI DEMİR") == "pasli demir"
    assert similar("Paslı Demir Anahtar", "pasli anahtar") is False
    assert similar("Paslı Demir Anahtar", "demir anahtar")
