"""Pydantic request/response schemas + the verbatim agent system prompt."""
from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# §7 AGENT SYSTEM PROMPT — dropped in verbatim as the LLM system message.
# --------------------------------------------------------------------------- #
AGENT_SYSTEM_PROMPT = """\
You are ASHA Sahayak, a clinical decision-SUPPORT assistant for trained Indian
frontline health workers (ASHA/ANM). You DO NOT diagnose or prescribe. You help
a trained worker decide how urgent a case is and where to send the patient.

ABSOLUTE RULES
- Use ONLY the protocol passages provided to you in <context>. If they do not
  cover the case, say so and recommend referral. Never use outside medical
  "knowledge" or guess.
- Cite the source protocol for every recommendation.
- Be conservative: any danger sign, any serious ambiguity, or any missing
  decisive detail -> escalate to referral. A false alarm is acceptable; a missed
  emergency is not.
- Stay within ASHA scope: assessment, danger-sign recognition, first response,
  referral, and health education only. No prescription dosing or clinical
  procedures beyond that scope.
- Frame conditions as "consistent with", never as a confirmed diagnosis.
- Reply in the SAME language the worker used. Keep it short, concrete, and
  action-first. Assume a small phone screen.

OUTPUT (return strict JSON matching the schema you are given):
- triage_category: one of EMERGENCY_REFER_NOW | URGENT_REFER_TODAY |
  HOME_CARE_WITH_FOLLOWUP | ROUTINE_HEALTH_EDUCATION
- refer_flag: true/false  (true for the two referral categories OR any danger sign)
- conditions_consistent_with: short list, each with the citation it came from
- confidence: low | medium | high
- reasoning_trace: 2-4 plain-language sentences a worker can verify
- next_steps: numbered, imperative actions within ASHA scope
- danger_signs_to_watch: from the protocols
- citations: source + section for each claim
- disclaimer: one short line

If critical info is missing, instead return a `clarifying_questions` array
(max 3) and nothing else.
"""

# --------------------------------------------------------------------------- #
# API request models
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=64)
    name: Optional[str] = None


class GeoConsent(BaseModel):
    consented: bool = False
    lat: Optional[float] = None
    lng: Optional[float] = None
    district: Optional[str] = None
    pincode: Optional[str] = None


class TriageRequest(BaseModel):
    session_id: str
    text: str = Field(..., min_length=1)
    # answers to previously asked clarifying questions, appended to the case
    clarifications: Optional[list[str]] = None
    geo: Optional[GeoConsent] = None


# --------------------------------------------------------------------------- #
# Structured extraction (Intake node output)
# --------------------------------------------------------------------------- #
class PatientInfo(BaseModel):
    age_value: Optional[float] = None
    age_unit: Optional[str] = None  # days | months | years
    sex: Optional[str] = None
    pregnant: Optional[bool] = None


class SymptomProfile(BaseModel):
    patient: PatientInfo = PatientInfo()
    chief_complaint: str = ""
    symptoms: list[str] = []
    duration: Optional[str] = None
    severity_reported: Optional[str] = None
    vitals: dict = {}
    stated_danger_signs: list[str] = []
    free_text_raw: str = ""
    language: str = "en"
    age_group: str = "general"  # neonate | child | adult | maternal | general


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #
class Citation(BaseModel):
    source: str
    section: str = ""


class ConditionMatch(BaseModel):
    condition: str
    citation: Optional[str] = None


class Facility(BaseModel):
    name: str
    type: str
    distance_km: Optional[float] = None
    phone: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    directions_url: Optional[str] = None


class TriageResult(BaseModel):
    case_id: str
    status: Literal["complete", "needs_clarification", "error"] = "complete"
    language: str = "en"

    clarifying_questions: Optional[list[str]] = None

    triage_category: Optional[str] = None
    refer_flag: bool = False
    danger_sign_override: bool = False
    conditions_consistent_with: list[ConditionMatch] = []
    confidence: Optional[str] = None
    reasoning_trace: Optional[str] = None
    next_steps: list[str] = []
    danger_signs_to_watch: list[str] = []
    citations: list[Citation] = []
    disclaimer: str = ""

    facilities: list[Facility] = []
    facility_note: Optional[str] = None
    helpline: Optional[str] = None

    symptom_profile: Optional[SymptomProfile] = None
    error: Optional[str] = None
