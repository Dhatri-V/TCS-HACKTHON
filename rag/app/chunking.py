from .schemas import Document, Chunk
from .config import CHUNK_SIZE, CHUNK_OVERLAP


def normalize_text(text: str) -> str:
    """
    Clean unnecessary whitespace from document text.
    """

    lines = text.splitlines()

    cleaned_lines = []

    for line in lines:
        line = line.strip()

        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP
):
    """
    Split text into overlapping chunks.
    """

    text = normalize_text(text)

    chunks = []

    start = 0

    while start < len(text):

        end = start + chunk_size

        chunk = text[start:end]

        chunks.append(chunk)

        start = end - overlap

    return chunks


def chunk_documents(documents):

    all_chunks = []

    for document in documents:

        chunks = chunk_text(document.text)

        for i, text in enumerate(chunks):

            chunk = Chunk(
                chunk_id=f"{document.source}_{i}",
                text=text,
                source=document.source,
                metadata=document.metadata
            )

            all_chunks.append(chunk)

    return all_chunks
