import React from "react";
import { Link } from "react-router-dom";

const CATEGORY_META = {
  EMERGENCY_REFER_NOW: { cls: "b-red", label: "EMERGENCY — REFER NOW", sub: "Send to hospital immediately" },
  URGENT_REFER_TODAY: { cls: "b-orange", label: "URGENT — REFER TODAY", sub: "Needs medical care today" },
  HOME_CARE_WITH_FOLLOWUP: { cls: "b-green", label: "HOME CARE + FOLLOW-UP", sub: "Manage at home and watch" },
  ROUTINE_HEALTH_EDUCATION: { cls: "b-blue", label: "ROUTINE / HEALTH EDUCATION", sub: "No acute illness" },
};

function speak(result) {
  try {
    const parts = [
      CATEGORY_META[result.triage_category]?.label,
      result.reasoning_trace,
      ...(result.next_steps || []),
    ].filter(Boolean);
    const u = new SpeechSynthesisUtterance(parts.join(". "));
    u.lang = result.language === "hi" ? "hi-IN" : "en-IN";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  } catch (_) {}
}

export default function TriageCard({ result }) {
  if (!result) return null;
  const meta = CATEGORY_META[result.triage_category] || {
    cls: "b-orange", label: result.triage_category || "REVIEW", sub: "",
  };
  const top = (result.facilities || [])[0];

  return (
    <div>
      {/* 1. Triage banner */}
      <div className={"banner " + meta.cls}>
        <div className="cat">{meta.label}</div>
        <div className="sub">{meta.sub}</div>
      </div>

      {/* 2. REFER flag */}
      {result.refer_flag && (
        <div className="refer">
          <div className="tag">⚑ REFER {result.triage_category === "EMERGENCY_REFER_NOW" ? "IMMEDIATELY" : "TODAY"}</div>
          <div className="muted" style={{ marginTop: 4 }}>
            Tell the family this needs a doctor{result.triage_category === "EMERGENCY_REFER_NOW" ? " now" : " today"}.
            Keep the patient comfortable and warm on the way. Call {result.helpline || "108"} for an ambulance if needed.
          </div>
          {result.danger_sign_override && (
            <div className="override">⚠ Danger-sign safety check forced this referral.</div>
          )}
        </div>
      )}

      {/* 3. Consistent-with conditions */}
      {(result.conditions_consistent_with || []).length > 0 && (
        <div className="card">
          <h2>Consistent with</h2>
          <p className="muted" style={{ marginTop: 0 }}>This is not a diagnosis.</p>
          {result.conditions_consistent_with.map((c, i) => (
            <span className="pill" key={i}>
              {c.condition}{c.citation ? ` — ${c.citation}` : ""}
            </span>
          ))}
          {result.confidence && <div className="conf" style={{ marginTop: 8 }}>Confidence: {result.confidence}</div>}
        </div>
      )}

      {/* reasoning */}
      {result.reasoning_trace && (
        <div className="card">
          <h2>Why</h2>
          <p style={{ margin: 0 }}>{result.reasoning_trace}</p>
        </div>
      )}

      {/* 4. Next steps */}
      {(result.next_steps || []).length > 0 && (
        <div className="card">
          <h2>What to do</h2>
          <ol className="steps">
            {result.next_steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        </div>
      )}

      {/* 5. Danger signs to watch */}
      {(result.danger_signs_to_watch || []).length > 0 && (
        <div className="card">
          <h2>Danger signs — return at once if</h2>
          <ul className="signs">
            {result.danger_signs_to_watch.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      )}

      {/* 6. Nearest facility */}
      <div className="card">
        <h2>Nearest facility</h2>
        {top ? (
          <>
            <div className="facility">
              <div>
                <div className="fname">{top.name}</div>
                <div className="ftype">{top.type}{top.distance_km != null ? ` · ${top.distance_km} km` : ""}</div>
              </div>
              <div className="fbtns">
                {top.phone && <a className="act call" href={`tel:${top.phone}`}>📞 Call</a>}
                {top.directions_url && <a className="act" href={top.directions_url} target="_blank" rel="noreferrer">🧭 Directions</a>}
              </div>
            </div>
            <Link to="/facilities" state={{ facilities: result.facilities, urgency: result.triage_category }}
              className="muted" style={{ display: "inline-block", marginTop: 6 }}>
              See all nearby facilities & map →
            </Link>
          </>
        ) : (
          <div className="notice">
            {result.facility_note || "No facility found."} Helpline / ambulance: <b>{result.helpline || "108"}</b>.
          </div>
        )}
      </div>

      {/* 7. Citations */}
      {(result.citations || []).length > 0 && (
        <div className="card">
          <details>
            <summary>Based on these protocols</summary>
            {result.citations.map((c, i) => (
              <div className="cite" key={i}>• {c.source}{c.section ? ` §${c.section}` : ""}</div>
            ))}
          </details>
        </div>
      )}

      {/* 8. Disclaimer + read aloud */}
      <div className="card">
        <button className="btn ghost" onClick={() => speak(result)}>🔊 Read aloud</button>
        <div className="disclaimer">{result.disclaimer || "This supports your judgment and does not replace a clinician."}</div>
      </div>
    </div>
  );
}
