model = 'qwen3.5:2b'
base_url = 'http://localhost:11434'
context_length = 32768
temp = 0.9

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