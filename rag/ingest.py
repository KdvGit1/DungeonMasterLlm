import os
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
import config

# ─── DÖKÜMAN YÜKLEME ───────────────────────────────────────

def load_documents():
    documents = []

    # rules klasöründeki tüm dosyaları tara
    for filename in os.listdir(config.rules_dir):
        filepath = os.path.join(config.rules_dir, filename)

        if filename.endswith('.pdf'):
            # PDF okuyucu, her sayfayı ayrı döküman olarak yükler
            loader = PyPDFLoader(filepath)
            documents.extend(loader.load())

        elif filename.endswith('.txt'):
            # TXT okuyucu, dosyayı tek döküman olarak yükler
            loader = TextLoader(filepath, encoding='utf-8')
            documents.extend(loader.load())

    print(f"{len(documents)} döküman yüklendi.")
    return documents

# ─── CHUNK'LARA BÖLME ──────────────────────────────────────

def split_documents(documents):
    # RecursiveCharacterTextSplitter metni önce paragraflara,
    # sonra cümlelere, sonra kelimelere göre böler
    # chunk_size: her parçanın max karakter sayısı
    # chunk_overlap: parçalar arası örtüşme (bağlam kaybı olmasın diye)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap
    )

    chunks = splitter.split_documents(documents)
    print(f"{len(chunks)} chunk oluşturuldu.")
    return chunks

# ─── VEKTÖR DB'YE KAYDET ───────────────────────────────────

def create_vectorstore(chunks):
    # OllamaEmbeddings: her chunk'ı sayı dizisine çevirir
    # Ollama'da nomic-embed-text modeli çalışıyor olmalı
    embeddings = OllamaEmbeddings(
        model=config.embedding_model,
        base_url=config.base_url
    )

    # Chroma chunk'ları alır, embedding'e çevirir, diske kaydeder
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=config.chroma_path
    )

    print(f"ChromaDB'ye kaydedildi → {config.chroma_path}")

# ─── ANA FONKSİYON ─────────────────────────────────────────

def ingest():
    # rules klasörü boşsa dur
    if not os.path.exists(config.rules_dir) or not os.listdir(config.rules_dir):
        print("Kural dosyası bulunamadı. data/rules/ klasörüne PDF veya TXT ekle.")
        return

    # ChromaDB zaten varsa tekrar oluşturma
    if os.path.exists(config.chroma_path) and os.listdir(config.chroma_path):
        print("VektörDB zaten mevcut, ingest atlanıyor.")
        return

    documents = load_documents()
    chunks = split_documents(documents)
    create_vectorstore(chunks)
    print("İngest tamamlandı!")

# direkt çalıştırılınca ingest başlar
# başka dosyadan import edilince başlamaz
if __name__ == "__main__":
    ingest()