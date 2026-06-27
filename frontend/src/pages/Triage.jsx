import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

const EXAMPLES = [
  { lang: "हिन्दी", text: "2 saal ki bachi, do din se bukhar aur tezi se saans le rahi hai, doodh nahi pee rahi." },
  { lang: "English", text: "Adult with mild runny nose and cough for 1 day, eating and drinking normally." },
];

// Supported languages: Hindi and English only. Maps to a Web Speech locale.
const SPEECH_LOCALES = { hi: "hi-IN", en: "en-IN" };
const LANG_LABELS = { hi: "हिन्दी", en: "English" };

export default function Triage() {
  const { sess, geo } = useApp();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [questions, setQuestions] = useState(null); // clarifying questions
  const [answers, setAnswers] = useState([]);
  const [speechLang, setSpeechLang] = useState("hi");
  const [recording, setRecording] = useState(false);
  const recRef = useRef(null);
  const netRetryRef = useRef(0); // auto-retry counter for transient "network" errors

  const submit = async (clarifications = null) => {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const payload = {
        session_id: sess.session_id,
        text: text.trim(),
        clarifications,
        geo: geo
          ? { consented: true, lat: geo.lat ?? null, lng: geo.lng ?? null, district: geo.label ?? null }
          : { consented: false },
      };
      const res = await api.triage(payload);
      if (res.status === "needs_clarification") {
        setQuestions(res.clarifying_questions || []);
        setAnswers((res.clarifying_questions || []).map(() => ""));
      } else {
        navigate(`/result/${res.case_id}`, { state: { result: res } });
      }
    } catch (err) {
      setError(err.message || "Triage failed. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  const submitClarifications = () => {
    // append the Q/A pairs to the original text so the agent re-runs with context
    const qa = questions.map((q, i) => `${q} ${answers[i] || ""}`.trim());
    setQuestions(null);
    submit(qa);
  };

  const startRecognition = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    rec.lang = SPEECH_LOCALES[speechLang] || "en-IN";
    rec.interimResults = true;     // show partial words so the user sees it working
    rec.continuous = false;
    rec.maxAlternatives = 1;

    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const tr = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += tr + " ";
        else interim += tr;
      }
      // live-preview the interim text on top of whatever was already typed
      setText((prev) => {
        const base = prev.replace(/\s*\[…[^\]]*\]$/, "");
        return interim ? `${base} [… ${interim.trim()}]`.trim() : `${base} ${finalText}`.trim();
      });
    };
    rec.onerror = (e) => {
      // "network" usually means the browser's speech backend (Google's servers)
      // is unreachable — most often because the browser BLOCKS it (Brave and some
      // Chromium builds disable Web Speech), not because the user is offline.
      // Retry once silently for genuine transient blips before warning.
      if (e.error === "network" && netRetryRef.current < 1 && navigator.onLine) {
        netRetryRef.current += 1;
        setTimeout(() => { try { rec.start(); } catch { /* already running */ } }, 600);
        return;
      }
      setRecording(false);
      const networkMsg = navigator.onLine
        ? "Voice typing couldn't reach the speech service. This browser is likely blocking it — Brave and some Chromium browsers disable voice typing. Open this page in Google Chrome to use the mic, or type your description instead."
        : "You appear to be offline. Voice typing needs an internet connection.";
      const map = {
        "not-allowed": "Microphone permission was blocked. Allow the mic in your browser's address-bar icon, then try again.",
        "service-not-allowed": "Microphone blocked by the browser. Allow mic access and retry.",
        "no-speech": "Didn't catch any speech. Tap Speak and talk clearly.",
        "audio-capture": "No microphone found. Check that a mic is connected.",
        "network": networkMsg,
        "aborted": "",
      };
      const msg = map[e.error] ?? `Voice error: ${e.error}. Please type instead.`;
      if (msg) setError(msg);
    };
    rec.onend = () => {
      setRecording(false);
      // strip any leftover interim marker
      setText((prev) => prev.replace(/\s*\[…[^\]]*\]$/, "").trim());
    };
    recRef.current = rec;
    netRetryRef.current = 0;
    setRecording(true);
    setError("");
    try {
      rec.start();
    } catch {
      // calling start() twice throws; ignore
    }
  };

  const toggleVoice = async () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setError("Voice input needs Chrome, Edge, or another Chromium browser. Please type instead.");
      return;
    }
    if (!window.isSecureContext) {
      setError("Voice input needs a secure page (https:// or localhost). Open the site over HTTPS, or type instead.");
      return;
    }
    if (recording) {
      recRef.current?.stop();
      return;
    }
    // Brave blocks the Web Speech backend, so warn before the user even speaks.
    try {
      if (navigator.brave && (await navigator.brave.isBrave())) {
        setError("Brave blocks voice typing (the Web Speech service is disabled for privacy). Please open this page in Google Chrome to use the mic, or type your description instead.");
        return;
      }
    } catch { /* brave API not present — carry on */ }
    // Explicitly request mic permission first — this reliably triggers the
    // browser prompt and surfaces a clear error if the mic is unavailable.
    try {
      if (navigator.mediaDevices?.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop()); // release immediately; SR opens its own
      }
    } catch (err) {
      setError(
        err?.name === "NotAllowedError"
          ? "Microphone permission denied. Allow mic access in your browser settings, then tap Speak again."
          : "Could not access the microphone. Check it is connected and allowed."
      );
      return;
    }
    startRecognition();
  };

  if (questions) {
    return (
      <div className="card">
        <h2>A few quick questions</h2>
        <p className="muted">The protocols need a little more detail to be safe.</p>
        {questions.map((q, i) => (
          <div key={i}>
            <label>{q}</label>
            <input
              type="text"
              value={answers[i]}
              onChange={(e) => {
                const next = [...answers];
                next[i] = e.target.value;
                setAnswers(next);
              }}
            />
          </div>
        ))}
        <div style={{ height: 12 }} />
        <button className="btn" onClick={submitClarifications} disabled={busy}>
          {busy ? <span className="spinner" /> : "Continue"}
        </button>
      </div>
    );
  }

  return (
    <div>
      {!geo && (
        <div className="notice">
          No location set — facility suggestions will be limited. You can set it from a new sign-in.
        </div>
      )}
      <div className="card">
        <h1>Describe the patient</h1>
        <p className="muted">
          Type or speak in your language: who the patient is (age), the symptoms,
          how long, and anything alarming.
        </p>
        {error && <div className="error">{error}</div>}
        <label htmlFor="sym">Symptoms</label>
        <div style={{ display: "flex", gap: 8 }}>
          <textarea
            id="sym"
            value={text}
            placeholder="e.g. 2 saal ki bachi, 2 din se bukhar aur tezi se saans…"
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <div className="lang-chips">
          <select value={speechLang} onChange={(e) => setSpeechLang(e.target.value)}
            style={{ width: "auto", padding: "8px 10px" }}>
            {Object.keys(SPEECH_LOCALES).map((l) => (
              <option key={l} value={l}>{LANG_LABELS[l]}</option>
            ))}
          </select>
          <button className={"mic" + (recording ? " rec" : "")} onClick={toggleVoice} type="button"
            title="Voice input">
            {recording ? "● Stop" : "🎤 Speak"}
          </button>
        </div>

        <div style={{ height: 14 }} />
        <button className="btn" onClick={() => submit(null)} disabled={busy || !text.trim()}>
          {busy ? (<><span className="spinner" /> &nbsp;Checking protocols…</>) : "Get triage"}
        </button>
      </div>

      <div className="card">
        <h2>Try an example</h2>
        <div className="lang-chips">
          {EXAMPLES.map((ex, i) => (
            <button key={i} onClick={() => setText(ex.text)}>{ex.lang}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
