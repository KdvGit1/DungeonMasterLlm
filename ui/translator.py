import threading
import time
import re
import config

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
        import torch

        cache_dir = os.path.join(os.path.dirname(__file__), "translator_models")
        os.makedirs(cache_dir, exist_ok=True)
        model_name = config.translator_model
        
        if model_name == "none":
            print("⚙️ Çeviri modeli 'none' olarak seçildi, yüklenmeyecek.")
            _loaded = True
            return
        
        # Cihaz belirleme (CPU)
        device = torch.device("cpu")
        print(f"⚙️ Çeviri modeli cihazı: {device}")
        
        try:
            # Önce sadece yereldeki (cache) dosyaları kullanarak yüklemeyi dene
            print("🔍 Model yerel önbellekte aranıyor...")
            _tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
            _model = AutoModelForSeq2SeqLM.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True, use_safetensors=True, device_map="auto")
            print(f"✅ Model yerel önbellekten başarıyla yüklendi. (Cihaz: {device})")
        except Exception as e:
            # Model yerelde yoksa veya eksikse, internetten indirerek yükle
            print(f"⚠️ Yerel model bulunamadı veya eksik, internetten indirilecek... ({type(e).__name__})")
            _tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
            _model = AutoModelForSeq2SeqLM.from_pretrained(model_name, cache_dir=cache_dir, use_safetensors=True, device_map="auto")

        elapsed = time.time() - start
        print(f"✅ NLLB-200 modeli kullanıma hazır ({elapsed:.1f}s)")
        _loaded = True

    except Exception as e:
        print(f"❌ NLLB-200 yükleme hatası: {e}")
        _load_error = str(e)
    finally:
        _loading = False


def ensure_model_loaded():
    """Model yüklenmemişse arka planda yüklemeyi başlatır."""
    global _loading, _loaded
    if getattr(config, "translator_model", "none") == "none":
        _loaded = True
        return

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
    if getattr(config, "translator_model", "none") == "none":
        return True
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

    if getattr(config, "translator_model", "none") == "none":
        return text

    if not is_ready():
        return text  # Model hazır değil, orijinali döndür

    try:
        device = next(_model.parameters()).device # Modelin o anki cihazını al
        _tokenizer.src_lang = src_lang
        
        # Yardımcı fonksiyon: Uzun metinleri cümlelere böl
        def chunk_text(text_to_chunk, max_chars=800):
            # Önce cümlelere bölmeyi dene
            sentences = re.split(r'(?<=[.!?])\s+', text_to_chunk)
            chunks = []
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                    
                if len(sentence) > max_chars:
                    # Çok uzun cümleyse kelimelere böl
                    words = sentence.split(" ")
                    temp_chunk = ""
                    for word in words:
                        if len(temp_chunk) + len(word) + 1 <= max_chars:
                            temp_chunk += (" " if temp_chunk else "") + word
                        else:
                            if temp_chunk:
                                chunks.append(temp_chunk)
                            temp_chunk = word
                    if temp_chunk:
                        chunks.append(temp_chunk)
                else:
                    chunks.append(sentence)
                
            return chunks

        def translate_chunk(chunk_str):
            # max_length uyarısını gidermek için modeli max_new_tokens ile çalıştırırken, 
            # truncation ve padding parametreleri ile de destekliyoruz.
            inputs = _tokenizer(chunk_str, return_tensors="pt", padding=True, truncation=True, max_length=1024)
            inputs = {k: v.to(device) for k, v in inputs.items()}

            translated_tokens = _model.generate(
                **inputs,
                forced_bos_token_id=_tokenizer.convert_tokens_to_ids(tgt_lang),
                max_new_tokens=1024,
                repetition_penalty=1.2,
                no_repeat_ngram_size=2
            )
            return _tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]

        paragraphs = text.split('\n')
        translated_paragraphs = []
        
        for p in paragraphs:
            if not p.strip():
                # Boş satırları aynı şekilde koru
                translated_paragraphs.append(p)
                continue
                
            chunks = chunk_text(p, max_chars=800)
            translated_chunks = []
            
            for c in chunks:
                if c.strip():
                    translated_chunks.append(translate_chunk(c))
                    
            translated_paragraphs.append(" ".join(translated_chunks))

        return '\n'.join(translated_paragraphs)

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
