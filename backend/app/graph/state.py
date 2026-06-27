"""Shared PatientCaseState carried through the LangGraph nodes."""
from __future__ import annotations

from typing import TypedDict, Optional, Any


class PatientCaseState(TypedDict, total=False):
    # identifiers
    case_id: str
    session_id: str

    # raw input
    text: str
    clarifications: list[str]
    geo: dict  # {consented, lat, lng, district, pincode}

    # intake output
    symptom_profile: dict          # SymptomProfile.model_dump()
    language: str
    age_group: str

    # clarification
    needs_clarification: bool
    clarifying_questions: list[str]

    # retrieval
    retrieved: list[dict]          # protocol passages + citations
    danger_passages: list[dict]    # danger-sign sub-index hits

    # reasoning
    triage: dict                   # LLM triage JSON
    triage_category: str
    refer_flag: bool

    # safety net
    danger_sign_override: bool
    override_reason: Optional[str]

    # facilities
    facilities: list[dict]
    facility_note: Optional[str]
    helpline: Optional[str]

    # final
    result: dict
    error: Optional[str]
