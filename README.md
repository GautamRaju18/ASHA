# 🩺 ASHA Sahayak — Rural Health-Worker Triage Web App

A responsive **web application** for ASHA / ANM / frontline rural health workers in
India. A worker signs in (location captured with consent), describes a patient's
symptoms in plain or regional language, and the agent **reasons over retrieved
official health protocols** to return:

- a **color-coded triage level** (4 fixed categories),
- an explicit **REFER** flag for danger cases (with a hard danger-sign override),
- action-oriented **next steps** within ASHA scope,
- the **nearest appropriate health facility** for the worker's location,
- **citations** to the source protocol and a disclaimer on every result.

It is a standard website served over HTTP(S) — open it in any phone or desktop
browser. **No install, no PWA, no service worker, no offline mode.** A live backend
connection is assumed.

> **Decision support, not diagnosis.** Every medical statement is grounded in a
> retrieved protocol passage. Ambiguity or any danger sign biases the system
> toward referral. It supports a trained worker's judgment; it does not replace a
> clinician.

---

## Architecture

```
Browser (React SPA, responsive)
   │  /api/*
   ▼
FastAPI  ── serves the built frontend + the agent API
   │
   ▼
LangGraph agent (stateful PatientCaseState)
   intake → clarification → retrieval → triage
                                 │         │
                                 │         ▼
                                 │   danger-sign safety net (hard override)
                                 ▼         │
                              facility finder → response composer
   │                                   │
   ▼                                   ▼
Hybrid RAG (FAISS dense + BM25)    OSM Overpass + Leaflet
over protocol corpus              (free, no API key)
   │
   ▼
Ollama (local LLM, free) — pluggable to a cloud API
```

**No hardcoded medicine.** Symptom lists, danger signs, condition mappings, and
triage thresholds are **retrieved from the corpus** and reasoned over by the LLM.
The only code-level constants are infra config and the 4 fixed triage labels. The
danger-sign **override mechanism** is in code; the danger-sign **content** comes
from the corpus.

### Stack
| Layer | Choice (all free by default) |
|------|------|
| API + static host | FastAPI + Uvicorn |
| Agent orchestration | LangGraph |
| LLM | **Ollama `llama3.2`** (local) · **Gemini** / **Kimi** (free-tier APIs) · Anthropic (paid). Switch via one env var. |
| Retrieval | sentence-transformers + FAISS (dense) **+** BM25 (always-on) hybrid |
| Danger-sign net | dedicated `is_danger_sign` sub-index |
| Facilities | OpenStreetMap Overpass API (no key) |
| Map | Leaflet + OSM tiles (lazy-loaded chunk) |
| Frontend | React + React Router + Vite (no PWA) |
| Audit log | SQLite (de-identified) |

---

## Quick start

**Prerequisites:** Python 3.10+, Node 18+, and [Ollama](https://ollama.com) running.

```powershell
# 1. Get the local model (free)
ollama pull llama3.2:latest

# 2. Build + run everything (Windows)
./run.ps1
# then open http://localhost:8000
```

### Manual steps (any OS)
```bash
# backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # (Linux/Mac: .venv/bin/pip)
# frontend
cd ../frontend
npm install && npm run build
# run (serves API + UI on one origin)
cd ../backend
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Dev mode (hot-reload UI)
```bash
# terminal 1 — backend
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# terminal 2 — frontend (proxies /api to :8000)
cd frontend && npm run dev    # http://localhost:5173
```

> **HTTPS for real devices:** browser geolocation needs a secure context.
> `localhost` is exempt, so local demos work over http. For a phone demo over the
> network, put it behind an HTTPS tunnel (e.g. `cloudflared`/`ngrok`) or an HTTPS host.

---

## 60-second demo

1. Open the URL, sign in as `ASHA-1024`, share location (GPS or type a district
   like `Mysuru`).
2. Tap the **हिन्दी** example (or type):
   *"2 saal ki bachi, do din se bukhar aur tezi se saans le rahi hai, doodh nahi pee rahi."*
3. Result: **RED — EMERGENCY / REFER NOW**, danger-sign override note, next steps,
   danger signs to watch, **nearest hospital with distance + Directions**, source
   citations — all in the worker's language.
4. Run a mild case (English example) to show it returns **green HOME CARE**, proving
   it isn't always-refer.
5. Open on a laptop to show the same site is fully responsive.

Smoke-test the agent safety properties:
```bash
cd backend && .venv/Scripts/python scripts/golden_test.py
```

---

## Configuration

Copy `.env.example` → `backend/.env` (or set env vars). Everything defaults to free.

**Sharper multilingual reasoning with a free-tier cloud model** (recommended over
the local 3B model). Gemini and Kimi both use an OpenAI-compatible endpoint:
```
# Gemini (free tier)
ASHA_LLM_PROVIDER=gemini
GEMINI_API_KEY=...
ASHA_GEMINI_MODEL=gemini-2.5-flash

# or Kimi / Moonshot
ASHA_LLM_PROVIDER=kimi
KIMI_API_KEY=...
```
Free tiers rate-limit (HTTP 429); the client auto-retries with backoff, so a
single sequential case still completes. Paid Anthropic is also supported
(`ASHA_LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`).

---

## The corpus (knowledge base)

Starter protocol chunks live in `backend/corpus/*.md`, paraphrased from public
IMNCI / NHM-ASHA / WHO / IDSP guidance, each tagged with `source`, `section`,
`condition`, `age_group`, `urgency_tag`, `is_danger_sign`.

**To use the real official PDFs:** drop them into `backend/corpus/` and restart —
`ingest.py` will chunk PDFs automatically. For best retrieval and citations,
prefer the structured `### CHUNK` markdown format (see existing files). Re-index by
restarting the server (the index rebuilds from the corpus on startup).

---

## Safety & ethics checklist (§13)

- ✅ **No ungrounded output** — triage reasons only over `<context>` passages; cites them.
- ✅ **Conservative defaults** — invalid/empty model output → `URGENT_REFER_TODAY`.
- ✅ **Danger-sign override** — independent sub-index screen can only *raise* urgency.
- ✅ **In-scope** — assessment / danger signs / first response / referral / education only.
- ✅ **"Consistent with,"** never "diagnosed as."
- ✅ **Disclaimer** on every result.
- ✅ **Location consent** + manual district/PIN fallback + no silent capture.
- ✅ **No fabricated facilities** — empty results surface the 108 helpline instead.
- ✅ **Audit log** (SQLite) of inputs, citations, triage, override — de-identified.
- ✅ **No PII in URLs** — session id only; patient text stays in request bodies.

---

## Known limitations

- This deployment is configured for **Gemini `gemini-2.5-flash`** (free tier) via
  `backend/.env`, which gives fluent regional-language reasoning and accurate
  citations. The fully-local **Ollama `llama3.2`** path also works with zero
  billing, but as a 3B model its prose/nuance are weaker and it sometimes
  over-escalates (a spec-sanctioned "false alarm is acceptable" bias). Either way
  the danger-sign safety net guarantees the dangerous→refer direction.
- Free-tier APIs rate-limit (≈10 req/min, limited req/day). One case makes ~3
  model calls, so single-user demo use is fine; rapid bursts hit HTTP 429 (the
  client backs off and retries). For heavy load, raise the quota or use Ollama.
- OSM Overpass returns all `amenity=hospital|clinic|doctors`, which in some areas
  includes private/specialty clinics. For production, preload the NHM PHC/CHC
  facility registry as a local geo-table (the finder is pluggable).
- Voice input uses the browser Web Speech API where available; otherwise type.

---

## Project layout

```
backend/
  app/
    config.py          # infra config + 4 triage labels (only allowed constants)
    schemas.py         # Pydantic models + verbatim agent system prompt
    llm.py             # pluggable LLM (Ollama default / Anthropic optional)
    facilities.py      # OSM Overpass + haversine + geocoding
    audit.py           # SQLite audit log
    rag/ingest.py      # corpus → atomic, metadata-tagged chunks (md + pdf)
    rag/retriever.py   # hybrid BM25 + dense FAISS, danger-sign sub-index
    graph/state.py     # PatientCaseState
    graph/nodes.py     # intake/clarify/retrieval/triage/danger/facility/composer
    graph/build.py     # LangGraph wiring
    main.py            # FastAPI app + SPA serving
  corpus/*.md          # protocol knowledge base
  scripts/golden_test.py
frontend/
  src/pages/           # Login, Triage, Result, Facilities, History
  src/components/TriageCard.jsx
  src/App.jsx, api.js, styles.css
then run.ps1
```
