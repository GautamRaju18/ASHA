import React, { useEffect, useState } from "react";
import { useParams, useLocation, Link } from "react-router-dom";
import { api } from "../api.js";
import TriageCard from "../components/TriageCard.jsx";

export default function Result() {
  const { caseId } = useParams();
  const location = useLocation();
  const [result, setResult] = useState(location.state?.result || null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!location.state?.result);

  useEffect(() => {
    if (result) return;
    let alive = true;
    api
      .getCase(caseId)
      .then((r) => alive && setResult(r))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [caseId, result]);

  if (loading) return <div className="center-spin"><span className="spinner" /> Loading case…</div>;
  if (error) return (
    <div>
      <div className="error">{error}</div>
      <Link className="btn secondary" to="/triage" style={{ display: "block", textAlign: "center", textDecoration: "none" }}>
        New case
      </Link>
    </div>
  );

  return (
    <div>
      <TriageCard result={result} />
      <Link className="btn" to="/triage" style={{ display: "block", textAlign: "center", textDecoration: "none", marginTop: 4 }}>
        + New case
      </Link>
    </div>
  );
}
