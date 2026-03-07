import os
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import config

_vectorstore = None

def load_vectorstore():
    global _vectorstore

    if not os.path.exists(config.chroma_path):
        print("VektörDB bulunamadı. Önce ingest.py çalıştır.")
        return None

    if _vectorstore is None:
        embeddings = OllamaEmbeddings(
            model=config.embedding_model,
            base_url=config.base_url
        )
        _vectorstore = Chroma(
            persist_directory=config.chroma_path,
            embedding_function=embeddings
        )
        print("VektörDB yüklendi.")

    return _vectorstore

def get_relevant_rules(query):
    vectorstore = load_vectorstore()

    if vectorstore is None:
        return None

    # similarity_search: sorguya en yakın chunk'ları döndürür
    results = vectorstore.similarity_search(query, k=config.retrieve_count)

    # her chunk'ın sadece metnini al, numaralandırarak birleştir
    rules_text = ""
    for i, doc in enumerate(results, 1):
        rules_text += f"Kural {i}:\n{doc.page_content}\n\n"

    return rules_text