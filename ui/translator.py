"""
ui/translator.py — NLLB-200 çeviri servisi
Model: facebook/nllb-200-distilled-1.3B
Lazy singleton: ilk çağrıda yüklenir, sonraki çağrılarda tekrar kullanılır.
"""

import threading
import time

# ─── GLOBAL STATE ─────────────────────────────────────────────────────────────

_model = None
_tokenizer = None
_lock = threading.Lock()
_loading = False
_loaded = False
_load_error = None

# NLLB dil kodları
LANG_EN = "eng_Latn"
LANG_TR = "tur_Latn"


# ─── MODEL YÜKLEME ───────────────────────────────────────────────────────────

def _load_model():
    """Modeli arka planda yükler."""
    global _model, _tokenizer, _loading, _loaded, _load_error

    try:
        print("🔄 NLLB-200 modeli yükleniyor...")
        start = time.time()

        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        import os
        
        cache_dir = os.path.join(os.path.dirname(__file__), "translator_models")
        os.makedirs(cache_dir, exist_ok=True)

        model_name = "facebook/nllb-200-distilled-1.3B"
        _tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
        _model = AutoModelForSeq2SeqLM.from_pretrained(model_name, cache_dir=cache_dir)

        elapsed = time.time() - start
        print(f"✅ NLLB-200 modeli yüklendi ({elapsed:.1f}s)")
        _loaded = True

    except Exception as e:
        print(f"❌ NLLB-200 yükleme hatası: {e}")
        _load_error = str(e)
    finally:
        _loading = False


def ensure_model_loaded():
    """Model yüklenmemişse arka planda yüklemeyi başlatır."""
    global _loading
    with _lock:
        if _loaded or _loading:
            return
        _loading = True

    thread = threading.Thread(target=_load_model, daemon=True)
    thread.start()


def get_status():
    """Model yüklenme durumunu döndürür."""
    if _loaded:
        return {"status": "ready"}
    if _loading:
        return {"status": "loading"}
    if _load_error:
        return {"status": "error", "error": _load_error}
    return {"status": "not_started"}


def is_ready():
    """Model hazır mı?"""
    return _loaded and _model is not None and _tokenizer is not None


# ─── ÇEVİRİ ──────────────────────────────────────────────────────────────────

def translate(text, src_lang=LANG_EN, tgt_lang=LANG_TR):
    """
    Tek bir metni çevirir.
    Varsayılan: İngilizce → Türkçe.
    Model hazır değilse orijinal metni döndürür.
    """
    if not text or not text.strip():
        return text

    if not is_ready():
        return text  # Model hazır değil, orijinali döndür

    try:
        _tokenizer.src_lang = src_lang
        inputs = _tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)

        translated_tokens = _model.generate(
            **inputs,
            forced_bos_token_id=_tokenizer.convert_tokens_to_ids(tgt_lang),
            max_new_tokens=512,
        )

        result = _tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]
        return result

    except Exception as e:
        print(f"⚠️ Çeviri hatası: {e}")
        return text  # Hata durumunda orijinali döndür


def translate_en_to_tr(text):
    """İngilizce → Türkçe çeviri kısayolu."""
    return translate(text, LANG_EN, LANG_TR)


def translate_tr_to_en(text):
    """Türkçe → İngilizce çeviri kısayolu."""
    return translate(text, LANG_TR, LANG_EN)


def translate_npc_data(npc_public):
    """
    NPC public verisini çevirir.
    İsim çevrilmez, role/appearance/personality çevrilir.
    """
    if not is_ready() or not npc_public:
        return npc_public

    translated = {}
    for key, value in npc_public.items():
        if key in ("role", "appearance", "personality") and value:
            translated[key] = translate_en_to_tr(value)
        else:
            translated[key] = value
    return translated
