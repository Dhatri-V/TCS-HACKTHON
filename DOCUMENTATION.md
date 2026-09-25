# TCS Cloud Incident Monitor
## Complete Project Documentation — TCS Hackathon 2026

---

> [!IMPORTANT]
> This document covers the full system built for TCS Hackathon 2026. It describes **what the system is**, **what problem it solves**, **how every component works**, and **how all parts connect together**.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Solution Overview](#2-solution-overview)
3. [System Architecture](#3-system-architecture)
4. [Technology Stack](#4-technology-stack)
5. [Component Deep-Dive](#5-component-deep-dive)
6. [The Full Data Flow — Step by Step](#6-the-full-data-flow--step-by-step)
7. [API Reference](#7-api-reference)
8. [File and Folder Structure](#8-file-and-folder-structure)
9. [Environment Variables](#9-environment-variables)
10. [How to Run the System](#10-how-to-run-the-system)
11. [Log Format Specification](#11-log-format-specification)
12. [Incident Payload — What Gets Sent to the AI Agent](#12-incident-payload--what-gets-sent-to-the-ai-agent)
13. [Error Handling and Resilience](#13-error-handling-and-resilience)
14. [What This System Does NOT Do](#14-what-this-system-does-not-do)
15. [Key Design Decisions](#15-key-design-decisions)

---

## 1. Problem Statement

Modern cloud applications generate **thousands of log entries every minute**. When something goes wrong — a failed API call, a database crash, an invalid user operation — a log entry with level `ERROR` or `CRITICAL` is written to a log file.

**The core problems:**
- Engineers cannot manually watch log files 24/7
- Errors are buried among thousands of INFO messages
- By the time a human notices the error, real damage has already happened
- There is no automated pipeline to catch errors, classify them, and escalate them for AI-powered root cause analysis

**This project solves the detection and escalation problem.** It:
1. Provides a working web application that performs real operations (product management)
2. Automatically writes structured logs for every single operation
3. Runs a background Python process that reads those logs in real time
4. Classifies each log line by severity using rule-based logic
5. Forwards every `ERROR` and `CRITICAL` event to an external AI Agent for root cause analysis

---

## 2. Solution Overview

The TCS Cloud Incident Monitor is a **3-tier web application + automated log processing pipeline**.

```
╔══════════════════════════════════════════════════════════════════════╗
║                    TCS CLOUD INCIDENT MONITOR                        ║
║                                                                      ║
║  ┌─────────────┐     HTTP      ┌──────────────┐     Mongoose         ║
║  │  React UI   │ ──────────▶  │  Express API │ ──────────────▶      ║
║  │  (Port 3000)│  Axios calls  │  (Port 5000) │    MongoDB Atlas      ║
║  └─────────────┘              └──────────────┘                       ║
║                                      │                               ║
║                                      │ Winston Logger                ║
║                                      ▼                               ║
║                             backend/logs/application.log             ║
║                                      │                               ║
║                                      │  (tail — reads new lines)    ║
║                                      ▼                               ║
║                          ┌─────────────────────┐                     ║
║                          │   Python Processor   │                     ║
║                          │   (polls every 5s)   │                     ║
║                          └─────────────────────┘                     ║
║                                      │                               ║
║                         ┌────────────┴────────────┐                 ║
║                         ▼            ▼             ▼                 ║
║                       INFO         WARN         ERROR / CRITICAL     ║
║                       (skip)      (log)        (build incident)      ║
║                                                       │              ║
║                                                       ▼              ║
║                                              External AI Agent API   ║
║                                              (POST /api/analyze)     ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 3. System Architecture

The system has **three independently runnable services**:

| Service | Technology | Port | Responsibility |
|---------|-----------|------|----------------|
| **Frontend** | React + Vite | 3000 | User interface for product management |
| **Backend** | Node.js + Express | 5000 | REST API, business logic, logging |
| **Log Processor** | Python 3 | N/A | Reads logs, classifies, forwards incidents |

All three communicate through **files and HTTP**:
- Frontend ↔ Backend: HTTP (Axios REST calls)
- Backend → Log File: Winston writes JSON to `application.log`
- Log Processor ← Log File: Python reads new lines from `application.log`
- Log Processor → AI Agent: HTTP POST with structured incident payload

---

## 4. Technology Stack

### Frontend
| Technology | Version | Why Chosen |
|-----------|---------|------------|
| **React** | 18 | Component-based UI, reactive state management |
| **Vite** | 5 | Ultra-fast dev server and bundler |
| **Axios** | 1.x | Promise-based HTTP client for API calls |
| **Vanilla CSS** | — | Full control, no framework overhead |
| **Inter + JetBrains Mono** | Google Fonts | Modern, readable typography |

### Backend
| Technology | Version | Why Chosen |
|-----------|---------|------------|
| **Node.js** | 20+ | Non-blocking I/O, same language as frontend |
| **Express** | 4.x | Minimal, flexible HTTP server framework |
| **Mongoose** | 8.x | MongoDB object modelling with schema validation |
| **Winston** | 3.x | Structured JSON logging with multiple transports |
| **dotenv** | 16.x | Environment variable management |
| **cors** | 2.x | Cross-origin request handling |
| **nodemon** | 3.x | Auto-restart on file changes during development |
| **swagger-jsdoc + swagger-ui-express** | — | Auto-generated interactive API documentation |

### Database
| Technology | Why Chosen |
|-----------|------------|
| **MongoDB Atlas** | Cloud-hosted NoSQL, flexible document schema, free tier available |

### Log Processor
| Technology | Why Chosen |
|-----------|------------|
| **Python 3.10+** | Excellent for file I/O, scripting, and data processing |
| **requests** | Simple, reliable HTTP POST to Agent API |
| **python-dotenv** | Reads `.env` configuration |
| **venv** | Isolated Python dependencies, no system pollution |

---

## 5. Component Deep-Dive

### 5.1 Frontend — React Dashboard

**Location:** `frontend/`  
**URL:** `http://localhost:3000`

#### What It Does

The frontend is a **single-page dark-mode dashboard** built with React. It provides:

- **Stats bar** — Total products, average price, highest price, log processor status indicator
- **Product creation form** — Create new products with name and price validation
- **Product table** — Lists all products with inline edit and delete per row
- **Toast notifications** — Slide-in success/error/info messages for every operation
- **Online/Offline indicator** — Live green/red dot showing backend connection health
- **Pipeline visualiser** — Shows the complete data flow: React → Axios → Express → MongoDB → Winston → Python → Classifier → Agent API

---

### 5.2 Backend — Express REST API

**Location:** `backend/`  
**URL:** `http://localhost:5000`  
**API Docs:** `http://localhost:5000/api-docs`

#### What It Does

The backend is a **RESTful API server** that:
- Connects to MongoDB Atlas on startup (with 5 retry attempts and 3s delays)
- Exposes 5 CRUD endpoints for product management
- Logs **every single operation** to `backend/logs/application.log` using Winston
- Handles all errors centrally — no stack traces ever reach the frontend

---

### 5.3 Database — MongoDB Atlas

**Type:** Cloud-hosted NoSQL Document Database  
**Collection:** `products`

---

### 5.4 Log Processor — Python Pipeline

**Location:** `log-processor/`  
**Run:** `venv\Scripts\python main.py` (Windows)

#### What It Does

The Python log processor is an **autonomous background service** that:
1. Watches `backend/logs/application.log` for new content every 5 seconds
2. Reads only **new lines** written since the last check (never reprocesses old ones)
3. Parses each JSON log line into a clean Python dict
4. Classifies the severity level using rule-based logic
5. For `ERROR` / `CRITICAL` — builds a structured incident and HTTP POSTs it to the AI Agent
6. Retries failed deliveries with linear backoff
7. Saves undeliverable incidents to disk for automatic replay on next startup

---

## 6. The Full Data Flow — Step by Step

```
User Action → Backend API → MongoDB → Winston Log File → Python Processor → AI Agent API
```

1. **User Action:** Product creation/update/delete form submitted on React UI.
2. **Axios POST:** Request sent to Node.js backend (`http://localhost:5000/api/products`).
3. **Database Save:** Mongoose persists data to MongoDB Atlas.
4. **Winston Log:** Backend emits JSON log line to `backend/logs/application.log`.
5. **Python Tail:** Background log processor detects new line at byte offset.
6. **Classification:** Rule-based classifier checks severity (`INFO` vs `ERROR`/`CRITICAL`).
7. **Incident Escalation:** If `ERROR`/`CRITICAL`, structured incident JSON payload is posted to external AI Agent API.

---

## 7. API Reference

- `GET /api/products` — Get all products
- `GET /api/products/:id` — Get single product
- `POST /api/products` — Create product
- `PUT /api/products/:id` — Update product
- `DELETE /api/products/:id` — Delete product
- `GET /health` — Health check status

---

## 8. File and Folder Structure

```
tcs-cloud-incident-monitor/
├── backend/                  # Node.js Express API & Winston logger
├── frontend/                 # React UI Dashboard (Vite)
├── log-processor/            # Python automated log processor & incident forwarder
├── DOCUMENTATION.md          # Complete architecture & developer guide
└── README.md                 # Quick start guide
```

---

## 9. How to Run the System

### 1. Backend:
```bash
cd backend
npm run dev
```

### 2. Frontend:
```bash
cd frontend
npm run dev -- --port 3000
```

### 3. Log Processor:
```bash
cd log-processor
venv\Scripts\activate
python main.py
```

---

*TCS Hackathon 2026 | Built with React + Node.js + MongoDB + Python*
