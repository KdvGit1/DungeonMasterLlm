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
target_language = 'English'  # default

model = 'qwen3.5:2b-q4_K_M'
base_url = 'http://localhost:11434'
context_length = 32768
temp = 0.6
num_predict = 800

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