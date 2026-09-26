from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent

KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
INCOMING_DIR = ROOT / "data" / "incoming"
INDEX_DIR = ROOT / "index"

EMBEDDING_MODEL = "BAAI/bge-m3"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")

TOP_K = 5
MIN_SIMILARITY = 0.60

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150