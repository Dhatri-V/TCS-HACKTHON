from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from .vector_store import EmbeddingModel, VectorStore
from .retriever import Retriever
from .pipeline import IncidentRAG


print("Loading embedding model...")
embedder = EmbeddingModel()

print("Loading saved FAISS index...")
store = VectorStore(embedder)
store.load()

print("Creating retriever...")
retriever = Retriever(store)

print("Creating RAG pipeline...")
rag = IncidentRAG(retriever)


app = FastAPI(
    title="AI Incident Investigator",
    description="RAG-based incident investigation system",
    version="1.0"
)


class IncidentRequest(BaseModel):
    incident: str


@app.get("/")
def root():
    return {
        "status": "running",
        "service": "AI Incident Investigator"
    }


@app.post("/investigate")
def investigate(request: IncidentRequest):

    result = rag.investigate(request.incident)

    return {
    "historical_match_found": result["historical_match_found"],
    "retrieved_incidents": [
        {
            "source": item["chunk"].source,
            "similarity": round(item["score"], 3),
            "text": item["chunk"].text
        }
        for item in result["retrieved_incidents"]
    ],
    "investigation": result["investigation"]
}

@app.post("/investigate/file")
async def investigate_file(file: UploadFile = File(...)):

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file provided."
        )

    allowed_extensions = {
        ".txt",
        ".log",
        ".md",
        ".json",
        ".csv"
    }

    filename = file.filename.lower()

    if not any(filename.endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Supported: .txt, .log, .md, .json, .csv"
        )

    content = await file.read()

    try:
        incident = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File must be UTF-8 encoded text."
        )

    if not incident.strip():
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    result = rag.investigate(incident)

    return {
    "filename": file.filename,
    "historical_match_found": result["historical_match_found"],
    "retrieved_incidents": [
        {
            "source": item["chunk"].source,
            "similarity": round(item["score"], 3),
            "text": item["chunk"].text
        }
        for item in result["retrieved_incidents"]
    ],
    "investigation": result["investigation"]
}