"""
LangGraph nodes. All medical reasoning is grounded in retrieved corpus passages
and performed by the LLM — no symptom lists, danger signs, or thresholds are
hardcoded. The only code-level logic is structural (is the case described enough)
and the danger-sign OVERRIDE MECHANISM (content comes from the corpus).
"""
from __future__ import annotations

import json
from typing import Optional

from app.config import (
    TRIAGE_CATEGORIES,
    TRIAGE_RANK,
    DISCLAIMER_FALLBACK,
    EMERGENCY_HELPLINE,
)
from app.llm import complete_json
from app.schemas import AGENT_SYSTEM_PROMPT
from app.rag.retriever import get_retriever
from app.facilities import find_facilities
from app.graph.state import PatientCaseState

# Urgency tag per category -> drives facility tier selection.
_CATEGORY_URGENCY = {
    "EMERGENCY_REFER_NOW": "emergency",
    "URGENT_REFER_TODAY": "emergency",   # same-day -> CHC/hospital tier
    "HOME_CARE_WITH_FOLLOWUP": "routine",
    "ROUTINE_HEALTH_EDUCATION": "routine",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _normalize_age_group(profile: dict, llm_hint: Optional[str] = None) -> str:
    """Structural demographic bucketing (not a medical threshold judgement)."""
    p = profile.get("patient", {}) or {}
    if p.get("pregnant"):
        return "maternal"
    val, unit = p.get("age_value"), (p.get("age_unit") or "").lower()
    if val is not None:
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = None
        if val is not None:
            if unit in ("day", "days", "week", "weeks"):
                return "neonate"
            if unit in ("month", "months"):
                return "neonate" if val < 2 else "child"
            if unit in ("year", "years"):
                return "child" if val < 5 else "adult"
    # fall back to the LLM's inferred band, then the profile's own value
    hint = (llm_hint or profile.get("age_group") or "general").lower()
    return hint if hint in ("neonate", "child", "adult", "maternal", "general") else "general"


def _build_query(profile: dict) -> str:
    parts = [
        profile.get("chief_complaint", ""),
        " ".join(profile.get("symptoms", []) or []),
        " ".join(profile.get("stated_danger_signs", []) or []),
        profile.get("duration", "") or "",
    ]
    return " ".join(p for p in parts if p).strip() or profile.get("free_text_raw", "")


def _format_context(passages: list[dict]) -> str:
    lines = []
    for i, p in enumerate(passages, 1):
        lines.append(
            f"[{i}] SOURCE: {p['source']} | SECTION: {p['section']} "
            f"| age_group: {p['age_group']} | danger_sign: {p['is_danger_sign']}\n"
            f"{p['text']}"
        )
    return "\n\n".join(lines) if lines else "(no relevant protocol passages found)"


def _citation_label(p: dict) -> str:
    return f"{p['source']}" + (f" §{p['section']}" if p.get("section") else "")


# --------------------------------------------------------------------------- #
# Node 1 — Intake / Language
# --------------------------------------------------------------------------- #
INTAKE_SYS = (
    "You extract a structured clinical SUMMARY from a frontline health worker's "
    "free-text description of a patient. Do NOT diagnose. "
    "Return ONLY JSON with this exact shape:\n"
    "{\n"
    '  "language": "<hi if the worker wrote in Hindi (Devanagari or Hinglish/'
    'romanized Hindi); otherwise en. Only these two values are allowed>",\n'
    '  "patient": {"age_value": <number|null>, "age_unit": "<days|months|years|null>", '
    '"sex": "<male|female|null>", "pregnant": <true|false|null>},\n'
    '  "chief_complaint": "<short phrase in English>",\n'
    '  "symptoms": ["<symptom>", ...],\n'
    '  "duration": "<e.g. 2 days|null>",\n'
    '  "severity_reported": "<mild|moderate|severe|null>",\n'
    '  "vitals": {},\n'
    '  "stated_danger_signs": ["<any alarming sign the worker mentioned>", ...]\n'
    "}\n"
    "Translate symptom/complaint terms into English for matching, but keep the "
    "detected language code accurate. If a field is unknown, use null or [] — never guess.\n"
    "Also infer an age band when the worker uses words instead of numbers: a "
    "'newborn' is days old, a 'baby/infant' is months old, a 'child' is under 5 "
    "years, and 'adult/man/woman' is an adult. Add a field "
    '"age_group": "<neonate|child|adult|maternal|general>" (use general only if '
    "you truly cannot tell)."
)


def intake_node(state: PatientCaseState) -> PatientCaseState:
    text = state.get("text", "")
    clarifications = state.get("clarifications") or []
    user = "Worker description:\n" + text
    if clarifications:
        user += "\n\nAdditional answers from the worker:\n- " + "\n- ".join(clarifications)

    data = complete_json(INTAKE_SYS, user, temperature=0.0) or {}
    if not isinstance(data, dict):
        data = {}

    profile = {
        "patient": data.get("patient") or {},
        "chief_complaint": data.get("chief_complaint", "") or "",
        "symptoms": data.get("symptoms") or [],
        "duration": data.get("duration"),
        "severity_reported": data.get("severity_reported"),
        "vitals": data.get("vitals") or {},
        "stated_danger_signs": data.get("stated_danger_signs") or [],
        "free_text_raw": text,
        # Only Hindi and English are supported; anything else falls back to English.
        "language": "hi" if str(data.get("language", "")).lower().startswith("hi") else "en",
    }
    profile["age_group"] = _normalize_age_group(profile, data.get("age_group"))

    state["symptom_profile"] = profile
    state["language"] = profile["language"]
    state["age_group"] = profile["age_group"]
    return state


# --------------------------------------------------------------------------- #
# Node 2 — Clarification (conditional)
# --------------------------------------------------------------------------- #
CLARIFY_SYS = (
    "You decide whether a frontline health worker has given enough information to "
    "triage a patient safely. A case is TRIAGE-READY if you know roughly the "
    "patient's age band and the main complaint. If a decisive detail is missing "
    "(age, how long the symptoms have lasted, or whether a key danger sign is "
    "present), generate at most 3 short follow-up questions in the SAME language "
    "as the worker. Return ONLY JSON: "
    '{"ready": <true|false>, "questions": ["...", ...]}. '
    "If ready, questions must be []."
)


def clarification_node(state: PatientCaseState) -> PatientCaseState:
    profile = state.get("symptom_profile", {})
    # Ask at most once: if the worker already answered clarifications, proceed
    # conservatively rather than looping.
    if state.get("clarifications"):
        state["needs_clarification"] = False
        return state

    # Cost/latency guard (also keeps free-tier API calls down): only spend an LLM
    # call deciding clarification when the case is plausibly sparse. A case that
    # already has a known age band AND a complaint with 2+ symptoms is detailed
    # enough to triage directly.
    symptoms = profile.get("symptoms") or []
    detailed = (
        profile.get("age_group", "general") != "general"
        and bool(profile.get("chief_complaint"))
        and len(symptoms) >= 2
    )
    if detailed:
        state["needs_clarification"] = False
        return state

    user = (
        f"Worker language: {profile.get('language')}\n"
        f"Structured case so far:\n{json.dumps(profile, ensure_ascii=False)}"
    )
    data = complete_json(CLARIFY_SYS, user, temperature=0.0) or {}
    questions = data.get("questions") or [] if isinstance(data, dict) else []
    ready = bool(data.get("ready", True)) if isinstance(data, dict) else True

    # Structural gate: only pause when the case is genuinely too sparse to triage
    # safely. A case with a complaint and at least a couple of symptoms proceeds —
    # the conservative defaults and the danger-sign safety net handle residual
    # uncertainty, which is safer than blocking a possibly-urgent case behind a
    # question loop.
    symptoms = profile.get("symptoms") or []
    has_complaint = bool(profile.get("chief_complaint") or symptoms)
    sparse = (
        len(symptoms) <= 1
        and not profile.get("duration")
        and profile.get("age_group", "general") == "general"
    )
    if not ready and questions and (not has_complaint or sparse):
        state["needs_clarification"] = True
        state["clarifying_questions"] = questions[:3]
    else:
        state["needs_clarification"] = False
    return state


# --------------------------------------------------------------------------- #
# Node 3 — Retrieval (RAG)
# --------------------------------------------------------------------------- #
def retrieval_node(state: PatientCaseState) -> PatientCaseState:
    profile = state.get("symptom_profile", {})
    query = _build_query(profile)
    r = get_retriever()
    age_group = profile.get("age_group", "general")
    state["retrieved"] = r.search(query, age_group=age_group)
    state["danger_passages"] = r.search_danger_signs(query, age_group=age_group)
    return state


# --------------------------------------------------------------------------- #
# Node 4 — Triage Reasoning
# --------------------------------------------------------------------------- #
def triage_node(state: PatientCaseState) -> PatientCaseState:
    profile = state.get("symptom_profile", {})
    passages = state.get("retrieved", [])
    context = _format_context(passages)

    schema_hint = (
        "Return ONLY JSON with this shape:\n"
        "{\n"
        '  "triage_category": "EMERGENCY_REFER_NOW|URGENT_REFER_TODAY|'
        'HOME_CARE_WITH_FOLLOWUP|ROUTINE_HEALTH_EDUCATION",\n'
        '  "refer_flag": <true|false>,\n'
        '  "conditions_consistent_with": [{"condition": "...", "citation": "<source §section>"}],\n'
        '  "confidence": "low|medium|high",\n'
        '  "reasoning_trace": "2-4 short sentences in the worker language",\n'
        '  "next_steps": ["imperative action in the worker language", ...],\n'
        '  "danger_signs_to_watch": ["...", ...],\n'
        '  "citations": [{"source": "...", "section": "..."}],\n'
        '  "disclaimer": "one short line in the worker language"\n'
        "}"
    )

    user = (
        f"<context>\n{context}\n</context>\n\n"
        f"PATIENT CASE (structured):\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"Worker language code: {profile.get('language', 'en')}\n\n"
        f"{schema_hint}\n\n"
        "Decide the triage category using ONLY the context above. If the context "
        "does not cover this case, choose at least URGENT_REFER_TODAY and say so. "
        "But if the protocols describe a clear home-care / no-danger-sign path that "
        "matches this patient AND no danger sign is present, you SHOULD choose "
        "HOME_CARE_WITH_FOLLOWUP or ROUTINE_HEALTH_EDUCATION — do not over-escalate "
        "beyond what the protocols indicate. Escalate only for genuine danger signs "
        "or real ambiguity. Write reasoning_trace and next_steps in the worker's "
        "language (code given above), not in English."
    )

    data = complete_json(AGENT_SYSTEM_PROMPT, user, temperature=0.0, retries=1)

    if not isinstance(data, dict) or data.get("triage_category") not in TRIAGE_CATEGORIES:
        # Conservative default when the model fails to produce a valid category.
        data = {
            "triage_category": "URGENT_REFER_TODAY",
            "refer_flag": True,
            "conditions_consistent_with": [],
            "confidence": "low",
            "reasoning_trace": ("The assistant could not confidently match this case "
                                "to the protocols, so it is recommending referral to be safe."),
            "next_steps": ["Refer the patient to the nearest PHC/CHC for assessment today.",
                           f"If the patient looks very unwell, call {EMERGENCY_HELPLINE}."],
            "danger_signs_to_watch": [],
            "citations": [{"source": c.get("source", ""), "section": c.get("section", "")}
                          for c in passages[:3]],
            "disclaimer": DISCLAIMER_FALLBACK,
            "_fallback": True,
        }

    # normalise refer_flag with category
    cat = data["triage_category"]
    if cat in ("EMERGENCY_REFER_NOW", "URGENT_REFER_TODAY"):
        data["refer_flag"] = True

    state["triage"] = data
    state["triage_category"] = cat
    state["refer_flag"] = bool(data.get("refer_flag"))
    return state


# --------------------------------------------------------------------------- #
# Node 5 — Danger-Sign / Referral safety net (override mechanism in code,
# danger-sign CONTENT from the corpus)
# --------------------------------------------------------------------------- #
DANGER_SYS = (
    "You are a safety checker for a frontline health worker. You are given danger-sign "
    "passages from official protocols and a structured patient case. Decide whether "
    "the patient clearly shows ANY danger sign listed in the passages. Be conservative: "
    "if a listed danger sign is plausibly present, flag it. Use ONLY the passages. "
    "Return ONLY JSON: "
    '{"danger_present": <true|false>, "level": "emergency|urgent", '
    '"matched_signs": ["...", ...], "reason": "one short sentence", '
    '"citation": "<source §section>"}. '
    "Use level=emergency for life-threatening signs, otherwise urgent."
)


def danger_sign_node(state: PatientCaseState) -> PatientCaseState:
    profile = state.get("symptom_profile", {})
    danger_passages = state.get("danger_passages", [])
    state["danger_sign_override"] = False
    state["override_reason"] = None

    if not danger_passages:
        return state

    context = _format_context(danger_passages)
    user = (
        f"<danger_sign_protocols>\n{context}\n</danger_sign_protocols>\n\n"
        f"PATIENT CASE:\n{json.dumps(profile, ensure_ascii=False)}"
    )
    data = complete_json(DANGER_SYS, user, temperature=0.0) or {}
    if not isinstance(data, dict) or not data.get("danger_present"):
        return state

    level = data.get("level", "urgent")
    forced = "EMERGENCY_REFER_NOW" if level == "emergency" else "URGENT_REFER_TODAY"

    current = state.get("triage_category", "ROUTINE_HEALTH_EDUCATION")
    # Hard override: never let the final category be LESS urgent than the
    # danger-sign screen demands.
    if TRIAGE_RANK.get(forced, 0) > TRIAGE_RANK.get(current, 0):
        state["triage_category"] = forced
        state["refer_flag"] = True
        state["danger_sign_override"] = True
        signs = ", ".join(data.get("matched_signs", []) or []) or "a protocol danger sign"
        state["override_reason"] = data.get("reason") or f"Danger sign detected: {signs}."

        # reflect override into the triage payload shown to the worker
        triage = state.get("triage", {})
        triage["triage_category"] = forced
        triage["refer_flag"] = True
        existing = triage.get("danger_signs_to_watch", []) or []
        for s in (data.get("matched_signs") or []):
            if s not in existing:
                existing.append(s)
        triage["danger_signs_to_watch"] = existing
        cit = data.get("citation")
        if cit and isinstance(triage.get("citations"), list):
            triage["citations"].append({"source": cit, "section": ""})
        state["triage"] = triage
    return state


# --------------------------------------------------------------------------- #
# Node 6 — Facility Finder
# --------------------------------------------------------------------------- #
def facility_node(state: PatientCaseState) -> PatientCaseState:
    geo = state.get("geo") or {}
    category = state.get("triage_category", "URGENT_REFER_TODAY")
    urgency = _CATEGORY_URGENCY.get(category, "emergency")
    lat, lng = geo.get("lat"), geo.get("lng")
    facilities, note = find_facilities(lat, lng, urgency)
    state["facilities"] = facilities
    state["facility_note"] = note
    state["helpline"] = EMERGENCY_HELPLINE
    return state


# --------------------------------------------------------------------------- #
# Node 7 — Response Composer
# --------------------------------------------------------------------------- #
def composer_node(state: PatientCaseState) -> PatientCaseState:
    triage = state.get("triage", {})
    profile = state.get("symptom_profile", {})

    conditions = []
    for c in triage.get("conditions_consistent_with", []) or []:
        if isinstance(c, dict):
            conditions.append({"condition": c.get("condition", ""),
                               "citation": c.get("citation")})
        elif isinstance(c, str):
            conditions.append({"condition": c, "citation": None})

    citations = []
    seen = set()
    for c in triage.get("citations", []) or []:
        if isinstance(c, dict):
            label = (c.get("source", ""), c.get("section", ""))
        else:
            label = (str(c), "")
        if label not in seen and label[0]:
            seen.add(label)
            citations.append({"source": label[0], "section": label[1]})

    result = {
        "case_id": state.get("case_id"),
        "status": "complete",
        "language": state.get("language", "en"),
        "clarifying_questions": None,
        "triage_category": state.get("triage_category"),
        "refer_flag": bool(state.get("refer_flag")),
        "danger_sign_override": bool(state.get("danger_sign_override")),
        "conditions_consistent_with": conditions,
        "confidence": triage.get("confidence"),
        "reasoning_trace": triage.get("reasoning_trace"),
        "next_steps": triage.get("next_steps", []) or [],
        "danger_signs_to_watch": triage.get("danger_signs_to_watch", []) or [],
        "citations": citations,
        "disclaimer": triage.get("disclaimer") or DISCLAIMER_FALLBACK,
        "facilities": state.get("facilities", []),
        "facility_note": state.get("facility_note"),
        "helpline": state.get("helpline", EMERGENCY_HELPLINE),
        "symptom_profile": profile,
        "error": None,
    }
    if state.get("danger_sign_override") and state.get("override_reason"):
        note = state["override_reason"]
        if note not in (result["reasoning_trace"] or ""):
            result["reasoning_trace"] = (
                (result["reasoning_trace"] or "") +
                f" [Safety override: {note}]"
            ).strip()

    state["result"] = result
    return state


def clarification_result(state: PatientCaseState) -> dict:
    """Build the early-return payload when clarification is needed."""
    return {
        "case_id": state.get("case_id"),
        "status": "needs_clarification",
        "language": state.get("language", "en"),
        "clarifying_questions": state.get("clarifying_questions", []),
        "disclaimer": DISCLAIMER_FALLBACK,
        "symptom_profile": state.get("symptom_profile"),
    }
