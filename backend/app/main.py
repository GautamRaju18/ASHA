"""
FastAPI entrypoint. Exposes the agent API and serves the built frontend so the
whole thing is one deployable website.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import audit, llm
from app.config import FRONTEND_DIST, EMERGENCY_HELPLINE
from app.facilities import (
    find_facilities,
    geocode_district,
    reverse_geocode,
)
from app.graph.build import run_case
from app.rag.retriever import get_retriever
from app.schemas import LoginRequest, TriageRequest, TriageResult

app = FastAPI(title="ASHA Sahayak", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Minimal in-memory session store (session_id -> worker info).
_SESSIONS: dict[str, dict] = {}


@app.on_event("startup")
def _startup() -> None:
    audit.init_db()
    try:
        stats = get_retriever().stats()
        print(f"[startup] retriever ready: {stats}")
    except Exception as e:
        print(f"[startup] WARNING retriever failed to build: {e}")


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    try:
        rstats = get_retriever().stats()
    except Exception as e:
        rstats = {"error": str(e)}
    return {"status": "ok", "llm": llm.health(), "retriever": rstats}


# --------------------------------------------------------------------------- #
# Auth (lightweight)
# --------------------------------------------------------------------------- #
@app.post("/api/login")
def login(req: LoginRequest) -> dict:
    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = {"worker_id": req.worker_id, "name": req.name}
    return {"session_id": session_id, "worker_id": req.worker_id, "helpline": EMERGENCY_HELPLINE}


# --------------------------------------------------------------------------- #
# Geo helpers (manual fallback + reverse geocode for display)
# --------------------------------------------------------------------------- #
class ManualGeoRequest(BaseModel):
    district: Optional[str] = None
    pincode: Optional[str] = None


@app.post("/api/geo/resolve")
def geo_resolve(req: ManualGeoRequest) -> dict:
    coords = geocode_district(req.district, req.pincode)
    if not coords:
        raise HTTPException(status_code=404, detail="Could not locate that district/PIN.")
    lat, lng = coords
    return {"lat": lat, "lng": lng, "label": reverse_geocode(lat, lng)}


class ReverseGeoRequest(BaseModel):
    lat: float
    lng: float


@app.post("/api/geo/label")
def geo_label(req: ReverseGeoRequest) -> dict:
    return {"label": reverse_geocode(req.lat, req.lng)}


# --------------------------------------------------------------------------- #
# Facilities (for the /facilities page)
# --------------------------------------------------------------------------- #
@app.get("/api/facilities")
def facilities(lat: float, lng: float, urgency: str = "emergency") -> dict:
    found, note = find_facilities(lat, lng, urgency)
    return {"facilities": found, "note": note, "helpline": EMERGENCY_HELPLINE}


# --------------------------------------------------------------------------- #
# Triage (the main endpoint)
# --------------------------------------------------------------------------- #
@app.post("/api/triage", response_model=TriageResult)
def triage(req: TriageRequest) -> TriageResult:
    worker = _SESSIONS.get(req.session_id, {})
    geo = req.geo.model_dump() if req.geo else {}
    try:
        result = run_case(
            text=req.text,
            session_id=req.session_id,
            geo=geo,
            clarifications=req.clarifications,
        )
    except Exception as e:
        # Conservative failure: tell the worker to refer rather than hiding the error.
        raise HTTPException(status_code=500, detail=f"Triage failed: {e}")

    audit.log_case(
        case_id=result.get("case_id"),
        session_id=req.session_id,
        worker_id=worker.get("worker_id"),
        result=result,
        profile=result.get("symptom_profile"),
    )
    return TriageResult(**result)


@app.get("/api/case/{case_id}", response_model=TriageResult)
def get_case(case_id: str) -> TriageResult:
    data = audit.get_case(case_id)
    if not data:
        raise HTTPException(status_code=404, detail="Case not found.")
    return TriageResult(**data)


@app.get("/api/history")
def history(session_id: str) -> dict:
    return {"cases": audit.list_cases(session_id=session_id)}


# --------------------------------------------------------------------------- #
# Serve the built frontend (SPA) — must be mounted LAST.
# --------------------------------------------------------------------------- #
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    def root() -> dict:
        return {
            "message": "ASHA Sahayak API is running. Build the frontend "
                       "(cd frontend && npm install && npm run build) to serve the UI here.",
            "docs": "/docs",
        }
