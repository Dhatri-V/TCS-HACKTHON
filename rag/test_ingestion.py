print("TEST FILE STARTED")

from app.ingestion import load_documents

print("IMPORT SUCCESS")

documents = load_documents("data/knowledge")

print("Documents loaded:", len(documents))

for document in documents:
    print("=" * 50)
    print("SOURCE:", document.source)
    print("METADATA:", document.metadata)
    print("CONTENT:")
    print(document.text)