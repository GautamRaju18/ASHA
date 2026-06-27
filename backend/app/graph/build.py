"""
LangGraph wiring of the triage agent.

Flow:
    intake -> clarification -> (needs_clarification? END : retrieval)
    retrieval -> triage -> danger_sign(override) -> facility -> composer -> END
"""
from __future__ import annotations

import uuid
from typing import Optional

from langgraph.graph import StateGraph, END

from app.graph.state import PatientCaseState
from app.graph import nodes


def _route_after_clarify(state: PatientCaseState) -> str:
    return "clarify_end" if state.get("needs_clarification") else "retrieval"


def build_graph():
    g = StateGraph(PatientCaseState)
    g.add_node("intake", nodes.intake_node)
    g.add_node("clarification", nodes.clarification_node)
    g.add_node("retrieval", nodes.retrieval_node)
    g.add_node("assess", nodes.triage_node)
    g.add_node("danger_sign", nodes.danger_sign_node)
    g.add_node("facility", nodes.facility_node)
    g.add_node("composer", nodes.composer_node)

    g.set_entry_point("intake")
    g.add_edge("intake", "clarification")
    g.add_conditional_edges(
        "clarification",
        _route_after_clarify,
        {"clarify_end": END, "retrieval": "retrieval"},
    )
    g.add_edge("retrieval", "assess")
    g.add_edge("assess", "danger_sign")
    g.add_edge("danger_sign", "facility")
    g.add_edge("facility", "composer")
    g.add_edge("composer", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_case(text: str, session_id: str, geo: Optional[dict] = None,
             clarifications: Optional[list[str]] = None,
             case_id: Optional[str] = None) -> dict:
    """Execute the graph for one case and return the final result payload."""
    case_id = case_id or uuid.uuid4().hex[:12]
    init: PatientCaseState = {
        "case_id": case_id,
        "session_id": session_id,
        "text": text,
        "clarifications": clarifications or [],
        "geo": geo or {},
    }
    final = get_graph().invoke(init)

    if final.get("needs_clarification"):
        return nodes.clarification_result(final)
    return final.get("result") or {
        "case_id": case_id,
        "status": "error",
        "error": "No result produced.",
    }
