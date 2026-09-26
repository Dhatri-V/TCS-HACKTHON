# AI Incident Investigator — RAG Module

An AI-powered incident investigation system that uses **semantic search + historical incident retrieval + a local LLM** to investigate new production incidents.

The system takes a new incident log as input, retrieves similar historical incidents using **BGE-M3 + FAISS**, and uses **Qwen 3** to generate a structured investigation report.

---

## 🚀 Architecture

```text
                    NEW INCIDENT
                         │
                         ▼
                ┌─────────────────┐
                │    FastAPI      │
                │  File / JSON    │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │   BGE-M3        │
                │   Embeddings    │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │      FAISS      │
                │ Vector Search   │
                └────────┬────────┘
                         │
                         ▼
              Similar Historical
                   Incidents
                         │
                         ▼
                ┌─────────────────┐
                │     Qwen 3      │
                │ Local LLM       │
                └────────┬────────┘
                         │
                         ▼
             Structured Investigation
                    JSON Report
                         │
                         ▼
                Human Verification
                         │
                         ▼
              Simulated Remediation
```

---

## 🎯 Problem

Production incidents often require engineers to manually:

* Analyze logs
* Identify possible root causes
* Search previous incidents
* Find relevant runbooks
* Decide what should be verified
* Determine possible remediation steps

This can increase incident resolution time.

The goal of this system is to act as an **AI Incident Investigator / SRE Copilot** that helps engineers investigate incidents using historical operational knowledge.

---

## 💡 Solution

The system separates the **current incident** from the **historical knowledge base**.

### Current incident

The incoming incident is treated as new evidence.

It is **NOT added to the FAISS index**.

### Historical knowledge

Previous incidents are stored in:

```text
data/knowledge/
```

These incidents are embedded and stored in FAISS.

When a new incident arrives:

```text
New Incident
     ↓
Embedding
     ↓
FAISS Similarity Search
     ↓
Historical Incidents
     ↓
Qwen 3 Investigation
```

This allows the system to investigate incidents that were not present in the original dataset.

---

# 🧠 Technology Stack

| Component       | Technology  |
| --------------- | ----------- |
| API             | FastAPI     |
| LLM             | Qwen 3      |
| LLM Runtime     | Ollama      |
| Embeddings      | BAAI/BGE-M3 |
| Vector Database | FAISS       |
| Language        | Python      |
| Validation      | Pydantic    |
| Server          | Uvicorn     |

---

# 📁 Project Structure

```text
rags/
│
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── schemas.py
│   ├── ingestion.py
│   ├── chunking.py
│   ├── vector_store.py
│   ├── retriever.py
│   ├── llm.py
│   ├── pipeline.py
│   ├── main.py
│   └── build_index.py
│
├── data/
│   ├── knowledge/
│   │   ├── incident_01.txt
│   │   ├── incident_2.txt
│   │   └── incident_3.txt
│   │
│   └── incoming/
│
├── index/
│   ├── incidents.faiss
│   └── chunks.pkl
│
├── test_incident.log
│
├── test_*.py
│
└── README.md
```

---

# 🔄 Pipeline

## 1. Knowledge Ingestion

Historical incidents are loaded from:

```text
data/knowledge/
```

Supported formats:

```text
.txt
.md
.log
.json
.csv
```

The ingestion layer converts these files into a common document representation.

---

## 2. Chunking

Large documents are divided into smaller chunks.

Current configuration:

```text
Chunk size: 900 characters
Overlap: 150 characters
```

This improves semantic retrieval by allowing FAISS to search smaller pieces of historical knowledge.

---

## 3. Embeddings

Historical chunks are converted into vector representations using:

```text
BAAI/bge-m3
```

The embeddings are normalized so that inner-product similarity behaves as cosine similarity.

---

## 4. FAISS Index

The embeddings are stored using:

```text
FAISS IndexFlatIP
```

The generated index is persisted to:

```text
index/incidents.faiss
```

The corresponding chunk metadata is stored in:

```text
index/chunks.pkl
```

This means the index does not need to be rebuilt every time the API starts.

---

## 5. Retrieval

When a new incident arrives, the incident is embedded and compared against historical incidents.

The system retrieves the most semantically similar incidents.

A similarity threshold is applied to avoid using weak historical matches.

Current prototype threshold:

```text
0.60
```

---

## 6. LLM Investigation

The retrieved historical incidents and current incident are provided to:

```text
Qwen 3
```

running locally through:

```text
Ollama
```

The model is instructed to:

* Analyze the current incident
* Identify a possible root-cause hypothesis
* Separate current evidence from historical evidence
* Explain historical similarity
* Generate verification steps
* Recommend remediation only when supported
* Avoid claiming that fixes were executed

---

# 🛡️ Safety / Grounding

The system follows a verification-first approach.

A historical incident does **not** automatically prove that the current incident has the same root cause.

For example:

```text
Historical Incident:
Database connection pool exhaustion

Current Incident:
Database connection timeout
503 errors
```

The system may generate:

```text
Root Cause:
Connection pool exhaustion

Status:
UNVERIFIED
```

It then provides verification steps instead of immediately executing a fix.

This reduces the risk of an AI system blindly applying infrastructure changes based only on historical similarity.

---

# 📊 Example

### Input

```text
2026-09-26 10:32:14 ERROR payment-api Database connection timeout
2026-09-26 10:32:15 ERROR payment-api Request failed with status 503
2026-09-26 10:32:16 WARN payment-api High latency detected
2026-09-26 10:32:17 ERROR payment-api Request timeout
```

### Retrieved historical incident

```text
incident_01.txt

Similarity: 0.725

503 errors
Latency increased
Database connections at 100%

Root Cause:
Connection pool exhaustion
```

### AI Investigation

```json
{
  "root_cause": {
    "hypothesis": "Connection pool exhaustion",
    "status": "UNVERIFIED"
  },
  "confidence": "MEDIUM"
}
```

The system then generates verification steps such as checking current connection-pool utilization before recommending remediation.

---

# 🌐 API

Start the server:

```cmd
uvicorn app.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

---

# 📌 API Endpoints

## Health Check

```http
GET /
```

Example response:

```json
{
  "status": "running",
  "service": "AI Incident Investigator"
}
```

---

## Investigate Incident

```http
POST /investigate
```

Request:

```json
{
  "incident": "Database connection timeout\n503 errors\nHigh latency"
}
```

---

## Investigate Uploaded File

```http
POST /investigate/file
```

Supported files:

```text
.txt
.log
.md
.json
.csv
```

Upload an incident log through Swagger:

```text
http://127.0.0.1:8000/docs
```

Select:

```text
POST /investigate/file
```

Then click:

```text
Try it out → Choose File → Execute
```

---

# 🛠️ Installation

## 1. Create virtual environment

```cmd
python -m venv .venv
```

Activate:

```cmd
.venv\Scripts\activate
```

---

## 2. Install dependencies

```cmd
pip install fastapi uvicorn requests sentence-transformers faiss-cpu pydantic python-multipart
```

---

## 3. Install Ollama

Install Ollama and make sure the Ollama service is running.

Check installed models:

```cmd
ollama list
```

The project currently uses:

```text
qwen3:4b
```

You can change the model through the `OLLAMA_MODEL` environment variable.

---

# 🏗️ Build the Historical Index

Whenever the historical knowledge base changes, rebuild the index:

```cmd
python -m app.build_index
```

This creates:

```text
index/incidents.faiss
index/chunks.pkl
```

---

# ▶️ Run the Application

Start Ollama first.

Then activate the virtual environment:

```cmd
.venv\Scripts\activate
```

Start FastAPI:

```cmd
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

---

# 🔬 Design Principle

The most important design decision is:

```text
CURRENT INCIDENT
       ≠
HISTORICAL KNOWLEDGE
```

The current incident is used for investigation but is not automatically stored as historical knowledge.

This prevents the system from contaminating its knowledge base with unverified incidents.

Historical information is used as supporting context rather than proof of the current root cause.

---

# 🚧 Current Scope

The current module focuses on:

* Incident ingestion
* Semantic retrieval
* Historical incident comparison
* AI root-cause hypothesis generation
* Evidence extraction
* Verification steps
* Remediation recommendation
* Structured investigation output

Infrastructure changes are **not executed**.

Remediation is currently treated as a recommendation/simulation layer.

---

# 🔮 Future Improvements

Potential extensions include:

* Cross-encoder reranking
* Kubernetes integration
* CloudWatch / Prometheus integration
* Real-time log streaming
* Runbook retrieval
* Multi-agent incident investigation
* Human approval workflow
* Automated remediation simulation
* Incident timeline generation
* Observability dashboard
* Feedback-based retrieval improvement
* Larger production incident knowledge base

---

# 🏆 Hackathon Value

The system demonstrates an end-to-end AI-assisted incident investigation workflow:

```text
Real Incident
     ↓
AI Retrieval
     ↓
Historical Knowledge
     ↓
Root Cause Hypothesis
     ↓
Evidence
     ↓
Verification
     ↓
Human Approval
     ↓
Safe Remediation Simulation
```

The architecture is designed around **human-in-the-loop incident response**, rather than allowing an LLM to directly modify production infrastructure.

---

## License

This project was developed as a hackathon prototype.
