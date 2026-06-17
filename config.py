import os
import json

# ─── API KEY LOADING ───────────────────────────────────────────
_API_KEYS_PATH = os.path.join(os.path.dirname(__file__), 'api_keys.json')
_api_keys = {}

def _load_api_keys():
    global _api_keys
    if os.path.exists(_API_KEYS_PATH):
        try:
            with open(_API_KEYS_PATH, 'r') as f:
                _api_keys = json.load(f)
        except Exception:
            _api_keys = {}

def _save_api_keys():
    with open(_API_KEYS_PATH, 'w') as f:
        # Don't save internal comments
        save_data = {k: v for k, v in _api_keys.items() if not k.startswith('_')}
        json.dump(save_data, f, indent=4)

_load_api_keys()

def get_api_key(provider):
    return _api_keys.get(f"{provider}_api_key", "")

def set_api_key(provider, key):
    _api_keys[f"{provider}_api_key"] = key
    _save_api_keys()

def get_provider_base_url(provider):
    return _api_keys.get(f"{provider}_base_url", "")

# ─── PROVIDER SELECTION ────────────────────────────────────────
# 'ollama' for local Ollama, 'openrouter' for cloud models
PROVIDER = 'ollama'  # default

# ─── OLLAMA SETTINGS (local) ───────────────────────────────────
AVAILABLE_MODELS = {
    "light_model": "qwen3.5:2b-q4_K_M",
    "recommended_model": "qwen3.5:9b",
    "heavy_model": "qwen3.5:17b"
}
AVAILABLE_TRANSLATOR_MODELS = {
    "no_model": "none",
    "light_model": "Emilio407/nllb-200-distilled-600M-4bit",
    "recommended_model": "Emilio407/nllb-200-1.3B-4bit"
}

translator_model = 'none'  # default
target_language = 'Turkish'  # default

model = 'qwen3.5:2b-q4_K_M'
base_url = 'http://localhost:11434'
context_length = 32768
temp = 0.6
num_predict = 800

# ─── OPENROUTER SETTINGS (cloud) ───────────────────────────────
# Popular OpenRouter models:
#   openrouter/owl-alpha          (OWL — the model you're using right now)
#   anthropic/claude-sonnet-4     (Claude Sonnet)
#   openai/gpt-4o                 (GPT-4o)
#   google/gemini-2.0-flash       (Gemini)
#   meta-llama/llama-4-maverick   (Llama 4)
OPENROUTER_MODELS = {
    "owl_alpha": "openrouter/owl-alpha",
    "claude_sonnet": "anthropic/claude-sonnet-4-20250514",
    "gpt_4o": "openai/gpt-4o",
    "gemini_flash": "google/gemini-2.0-flash-001",
    "llama_maverick": "meta-llama/llama-4-maverick",
    "qwen_72b": "qwen/qwen-2.5-72b-instruct",
}
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
openrouter_model = 'openrouter/owl-alpha'
openrouter_api_key = get_api_key('openrouter')  # loaded from api_keys.json

# ─── ACTIVE SETTINGS (based on PROVIDER) ───────────────────────
def get_active_base_url():
    if PROVIDER == 'openrouter':
        return OPENROUTER_BASE_URL
    return base_url

def get_active_model():
    if PROVIDER == 'openrouter':
        return openrouter_model
    return model

def get_active_api_key():
    if PROVIDER == 'openrouter':
        return get_api_key('openrouter')
    return None

def get_active_context_length():
    if PROVIDER == 'openrouter':
        return 32768  # Most OpenRouter models support large context
    return context_length

# ─── DATABASE & PATHS ──────────────────────────────────────────
sq_lite_path = 'data/dnd_gm.db'

chroma_path = 'rag/vector_store/'
embedding_model = 'nomic-embed-text'
chunk_size = 500
chunk_overlap = 50
retrieve_count = 3

message_history_size = 20
character_dir = 'data/characters/'
rules_dir = 'data/rules/'
session_dir = 'data/sessions/'
