# TCS Cloud Incident Monitor 🚀
> **TCS Hackathon 2026** — Automated Real-Time Cloud Incident Monitoring, Log Severity Classification, and AI Agent Escalation Pipeline.

---

## 📖 Complete Documentation

For the full detailed architecture, step-by-step data flow, API specification, design decisions, and log format specs, see **[DOCUMENTATION.md](./DOCUMENTATION.md)**.

---

## 🌟 Solution Overview

The TCS Cloud Incident Monitor is a 3-tier web application coupled with an autonomous Python background log processor:

1. **Frontend (React 18 + Vite)** — Port `3000`: Dark-mode dashboard for product management, status indicators, and live pipeline visualization.
2. **Backend (Node.js + Express + MongoDB Atlas)** — Port `5000`: RESTful CRUD API that logs every single operation as structured JSON to `backend/logs/application.log` using Winston.
3. **Log Processor (Python 3)** — Non-blocking background worker that tails `application.log` using offset tracking, classifies severities (`INFO` / `WARN` / `ERROR` / `CRITICAL`), and forwards incidents to an external AI Agent via HTTP POST.

```
React UI (3000) ──> Express API (5000) ──> MongoDB Atlas
                         │
                   Winston Logger
                         │
                         ▼
             backend/logs/application.log
                         │
             Python Processor (Tail & Classify)
                         │
                         ▼ (ERROR / CRITICAL)
               External AI Agent API
```

---

## 🚀 Quick Start Guide

### Prerequisites
- Node.js 20+
- Python 3.10+
- Active MongoDB Atlas connection string in `backend/.env`

### 1. Start the Backend API (Terminal 1)
```bash
cd backend
npm install
npm run dev
```
- Server: `http://localhost:5000`
- Swagger Docs: `http://localhost:5000/api-docs`

### 2. Start the Frontend Dashboard (Terminal 2)
```bash
cd frontend
npm install
npm run dev -- --port 3000
```
- Open browser: `http://localhost:3000`

### 3. Start the Log Processor (Terminal 3)
```bash
cd log-processor
venv\Scripts\activate      # Windows (or source venv/bin/activate on Linux/Mac)
python main.py
```

---

## 🧪 Testing the Python Pipeline
```bash
cd log-processor
venv\Scripts\activate
python -m unittest test_pipeline.py
```
*(All 16 unit tests passing)*

---

## 📂 Project Structure

```
tcs-cloud-incident-monitor/
├── backend/                  # Express REST API, MongoDB connection, Winston JSON Logger
├── frontend/                 # React 18 single-page dashboard with Vite
├── log-processor/            # Python real-time log tailing, rule classifier, AI agent forwarder
├── DOCUMENTATION.md          # Full project architecture and detailed documentation
└── README.md                 # Quick start guide
```
