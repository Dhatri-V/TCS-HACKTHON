from app.ingestion import load_documents
from app.chunking import chunk_documents


documents = load_documents("data/knowledge")

chunks = chunk_documents(documents)

print("Documents:", len(documents))
print("Chunks:", len(chunks))

for chunk in chunks:

    print("=" * 50)
    print("CHUNK ID:", chunk.chunk_id)
    print("SOURCE:", chunk.source)
    print("TEXT:")
    print(chunk.text)