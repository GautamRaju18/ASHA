"""
Central infra configuration. The ONLY code-level constants allowed by the spec
are infra config (model names, paths, keys) and the fixed triage category labels.
No medical content lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths ---
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()
CORPUS_DIR = Path(os.getenv("ASHA_CORPUS_DIR", BACKEND_DIR / "corpus"))
DATA_DIR = Path(os.getenv("ASHA_DATA_DIR", BACKEND_DIR / "data"))
INDEX_DIR = DATA_DIR / "index"
AUDIT_DB = DATA_DIR / "audit.sqlite3"
# Frontend build (served by FastAPI when present)
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

DATA_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)

# --- LLM backend (pluggable) ---
# Provider is chosen at runtime via ASHA_LLM_PROVIDER:
#   openrouter (free models) | ollama (local, free) | gemini (free tier) | anthropic (paid)
# openrouter and gemini both use an OpenAI-compatible chat endpoint.
LLM_PROVIDER = os.getenv("ASHA_LLM_PROVIDER", "ollama").lower()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("ASHA_OLLAMA_MODEL", "llama3.2:latest")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ASHA_ANTHROPIC_MODEL", "claude-opus-4-8")

# Gemini (Google) — OpenAI-compatible endpoint.
# Models are tried in order. gemini-3.5-flash works on the FREE tier;
# gemini-3-pro-preview needs a BILLED account (free-tier quota = 0) and is kept
# in the list so it activates automatically once billing is enabled.
# Back-compat: a single ASHA_GEMINI_MODEL is still honored if set.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.getenv(
    "ASHA_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
)
GEMINI_MODELS = [m.strip() for m in os.getenv(
    "ASHA_GEMINI_MODELS",
    os.getenv("ASHA_GEMINI_MODEL", "gemini-3.5-flash,gemini-3-pro-preview"),
).split(",") if m.strip()]

# OpenRouter — OpenAI-compatible gateway to many models. We use only its FREE
# (":free") models. Each free model rate-limits (429) independently under load,
# so we register several and fail over between them. Note: Kimi/GLM are NOT
# available as free models on OpenRouter (paid-only), so they are not listed.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("ASHA_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODELS = [m.strip() for m in os.getenv(
    "ASHA_OPENROUTER_MODELS",
    "nvidia/nemotron-3-super-120b-a12b:free,"
    "poolside/laguna-m.1:free,"
    "google/gemma-4-26b-a4b-it:free",
).split(",") if m.strip()]

# Resolved (base_url, api_key, model) for the OpenAI-compatible providers.
# Each model becomes its own failover provider, preserving configured order:
#   gemini, gemini-2, ...   then   openrouter, openrouter-2, ...
OPENAI_COMPAT: dict[str, tuple[str, str, str]] = {}

GEMINI_PROVIDERS: list[str] = []
for _i, _m in enumerate(GEMINI_MODELS):
    _name = "gemini" if _i == 0 else f"gemini-{_i + 1}"
    OPENAI_COMPAT[_name] = (GEMINI_BASE_URL, GEMINI_API_KEY, _m)
    GEMINI_PROVIDERS.append(_name)

OPENROUTER_PROVIDERS: list[str] = []
for _i, _m in enumerate(OPENROUTER_MODELS):
    _name = "openrouter" if _i == 0 else f"openrouter-{_i + 1}"
    OPENAI_COMPAT[_name] = (OPENROUTER_BASE_URL, OPENROUTER_API_KEY, _m)
    OPENROUTER_PROVIDERS.append(_name)

LLM_TIMEOUT_S = float(os.getenv("ASHA_LLM_TIMEOUT", "120"))

# --- Embeddings / retrieval ---
# Dense retrieval is best-effort. If sentence-transformers + faiss are available
# the retriever runs hybrid (dense + BM25); otherwise it degrades to BM25 only.
EMBED_MODEL = os.getenv("ASHA_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
USE_DENSE = os.getenv("ASHA_USE_DENSE", "1") == "1"
RETRIEVAL_TOP_K = int(os.getenv("ASHA_TOP_K", "6"))
DANGER_TOP_K = int(os.getenv("ASHA_DANGER_TOP_K", "8"))

# --- Google Maps / Places (preferred facility source + map when key present) ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")  # server-only, unused unless OAuth login added
GOOGLE_PLACES_URL = os.getenv(
    "ASHA_GOOGLE_PLACES_URL", "https://places.googleapis.com/v1/places:searchNearby"
)

# --- Facilities (OSM Overpass = free fallback, no key) ---
OVERPASS_URL = os.getenv("ASHA_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
NOMINATIM_URL = os.getenv("ASHA_NOMINATIM_URL", "https://nominatim.openstreetmap.org")
FACILITY_RADIUS_M = int(os.getenv("ASHA_FACILITY_RADIUS_M", "15000"))
FACILITY_N = int(os.getenv("ASHA_FACILITY_N", "5"))
EMERGENCY_HELPLINE = os.getenv("ASHA_HELPLINE", "108")  # India ambulance

# --- Fixed triage category label set (the ONLY allowed medical-ish enum) ---
TRIAGE_CATEGORIES = [
    "EMERGENCY_REFER_NOW",
    "URGENT_REFER_TODAY",
    "HOME_CARE_WITH_FOLLOWUP",
    "ROUTINE_HEALTH_EDUCATION",
]
# Severity ranking used only to implement the danger-sign *override mechanism*
# (higher = more urgent). The assignment itself is reasoned by the LLM.
TRIAGE_RANK = {c: i for i, c in enumerate(reversed(TRIAGE_CATEGORIES))}

DISCLAIMER_FALLBACK = (
    "This supports your judgment and does not replace a clinician. "
    "When in doubt, refer."
)
