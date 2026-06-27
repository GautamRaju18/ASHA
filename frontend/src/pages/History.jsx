import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

const LABEL = {
  EMERGENCY_REFER_NOW: ["Emergency", "#c62828"],
  URGENT_REFER_TODAY: ["Urgent", "#ef6c00"],
  HOME_CARE_WITH_FOLLOWUP: ["Home care", "#0b6e4f"],
  ROUTINE_HEALTH_EDUCATION: ["Routine", "#1565c0"],
};

export default function History() {
  const { sess } = useApp();
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .history(sess.session_id)
      .then((r) => setCases(r.cases || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [sess]);

  if (loading) return <div className="center-spin"><span className="spinner" /> Loading history…</div>;

  return (
    <div>
      <div className="card">
        <h1>Case history</h1>
        <p className="muted" style={{ marginTop: 0 }}>Your cases this session (de-identified).</p>
        {error && <div className="error">{error}</div>}
        {cases.length === 0 && <p className="muted">No cases yet.</p>}
        {cases.map((c) => {
          const [label, color] = LABEL[c.triage_category] || ["—", "#5f6b66"];
          return (
            <Link
              key={c.case_id}
              to={`/result/${c.case_id}`}
              style={{ textDecoration: "none", color: "inherit" }}
            >
              <div className="facility">
                <div>
                  <div className="fname">
                    <span className="pill" style={{ background: color, color: "#fff" }}>{label}</span>
                    {c.danger_override ? " ⚑" : ""}
                  </div>
                  <div className="ftype">
                    {new Date(c.created_at * 1000).toLocaleString()} · {c.language || "—"}
                  </div>
                </div>
                <div className="fdist">View →</div>
              </div>
            </Link>
          );
        })}
      </div>
      <Link className="btn" to="/triage"
        style={{ display: "block", textAlign: "center", textDecoration: "none" }}>
        + New case
      </Link>
    </div>
  );
}
