# DevPulse – Automated Daily Tech Digest

DevPulse is an automated **AI-powered daily tech intelligence system** that collects high‑signal information from GitHub, AI/ML frameworks, research ecosystems, and curated feeds—then converts it into a clean email digest using **FastAPI**, **background crawlers**, and an **n8n automation pipeline**.

This project is designed for engineers, researchers, and founders who want a curated snapshot of meaningful updates across AI, ML, LLMs, systems research, open‑source releases, and developer tooling—without manually checking 20+ sources.

---

## 🚀 Features

* **Full backend service (FastAPI)** to aggregate and store items
* **Crawler/Scraper workers** for GitHub, HuggingFace, PyTorch, and future integrations
* **Smart ranking system** using weighted heuristics & signal scoring
* **Digest endpoint** that returns top N items for the last 24 hours
* **n8n workflow** that generates a daily HTML email
* **Optional LLM summarization** using Gemini / OpenAI / local LLM
* **Production‑ready Docker Compose setup**
* **Zero manual steps — fully automated daily delivery**

---

## 🧠 Core Purpose

DevPulse exists to solve one problem:

> *"High‑quality daily updates for engineers are scattered, noisy, and time‑consuming to track manually."*

Rather than consuming firehoses of GitHub notifications or reading huge changelogs, DevPulse filters and compiles:

* AI model releases
* ML library updates
* Systems & infra changes
* Important research connections
* OSS ecosystem movements

Then it builds a **single concise digest email** every day.

---

## 🧩 Architecture Overview

```
┌──────────────────┐     ┌──────────────────────┐
│  Crawlers / Jobs  │ --> │  FastAPI Backend      │
│  (GitHub, HF, etc)│     │  + SQLite/Postgres    │
└──────────────────┘     └──────────┬───────────┘
                                     │ /digest/json
                                     ▼
                        ┌────────────────────┐
                        │  n8n Workflow       │
                        │  (HTML + Summary)   │
                        └──────────┬─────────┘
                                   ▼
                           📧 Daily Email
```

---

## 🛠️ Tech Stack

### **Backend**

* **FastAPI** – high‑performance async backend
* **Uvicorn** – ASGI server
* **SQLite / Postgres** – depending on deployment target
* **Requests / httpx** – API fetches for feeds
* **Custom scoring engine** – ranks items by relevance

### **Automation Pipeline**

* **n8n** (self‑hosted) – orchestrates fetching → summarization → email
* **HTML templating** inside n8n for email layout
* **Gemini / OpenAI API / local LLM** (optional) – summarization chain
* **Retry and fallback mode** to bypass API outages

### **Infrastructure**

* **Docker & Docker Compose** – production‑ready, reproducible environment
* **Containerized backend + n8n** in isolated network
* **Volume‑mounted DB & logs**

### **Email Delivery**

* **SMTP** (Gmail / custom domain)
* TLS-secured send
* Minimalist HTML template with mobile‑friendly view

---

## 📦 Project Structure

```
devpulse-ai/
│
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── cron_jobs/
│   ├── collectors/ (GitHub / HF / PyTorch / etc.)
│   ├── scoring/
│   └── utils/
│
├── docker-compose.yml
├── n8n/
│   ├── workflows/
│   └── credentials/
│
└── README.md
```

---

## 📬 Daily Digest Breakdown

Each email contains:

* Date header
* Curated updates ranked by score
* Release titles & links
* Tags for quick scanning (GitHub, Release, HF, Framework, Research)
* Optional LLM‑generated summary paragraph
* Simple clean HTML layout

---

## ▶️ Running Locally

### Start all services

```
docker compose up -d --build
```

Backend will run on: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**
n8n will run on: **[http://127.0.0.1:5678](http://127.0.0.1:5678)**

### Test the digest

```
curl http://127.0.0.1:8000/digest/json?limit=50
```

---

## 🌐 Deployment Notes

* Works on any VM with Docker (Render, GCP, AWS, Hetzner)
* Can scale to Postgres for heavier workloads
* n8n can be put behind a reverse proxy (Caddy / Nginx)
* SMTP should ideally use an App Password (Gmail) or a domain provider

---

## 🧭 Roadmap

* Medium / ArXiv / RSS ingestion
* Daily GitHub trending analysis
* Repository health scoring
* ML‑specific distillation of research papers
* Agentic enrichment using structured LLM chains
* Multi‑user digest with preferences
* DevPulse v3 with full-scale AI summarization modes

---

## 📄 License

MIT License

---

## 💡 Final Note

DevPulse is designed to be a **developer-first intelligence tool**.
Simple, fast, signal‑rich, and production-ready out of the box.
