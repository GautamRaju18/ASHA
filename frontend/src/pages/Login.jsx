import React, { useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

export default function Login() {
  const { onLogin } = useApp();
  const [workerId, setWorkerId] = useState("");
  const [name, setName] = useState("");
  const [step, setStep] = useState("login"); // login | location
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [district, setDistrict] = useState("");
  const [pincode, setPincode] = useState("");
  const [geoMsg, setGeoMsg] = useState("");

  const doLogin = async (e) => {
    e.preventDefault();
    if (!workerId.trim()) return;
    setBusy(true);
    setError("");
    try {
      const s = await api.login(workerId.trim(), name.trim() || null);
      setSession(s);
      setStep("location");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  // hold the logged-in session until location step finishes
  const [sessionData, setSession] = useState(null);

  const useBrowserLocation = () => {
    setError("");
    setGeoMsg("Requesting location permission…");
    if (!navigator.geolocation) {
      setGeoMsg("");
      setError("This browser does not support location. Enter your district below.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude, longitude } = pos.coords;
        let label = null;
        try {
          label = (await api.reverseLabel(latitude, longitude)).label;
        } catch (_) {}
        finishLocation({ consented: true, lat: latitude, lng: longitude, label });
      },
      (err) => {
        setGeoMsg("");
        setError(
          err.code === err.PERMISSION_DENIED
            ? "Location permission denied. Enter your district or PIN code instead."
            : "Could not get location. Enter your district or PIN code instead."
        );
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  const useManualLocation = async () => {
    if (!district.trim() && !pincode.trim()) {
      setError("Enter a district name or PIN code.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.resolveDistrict(district.trim() || null, pincode.trim() || null);
      finishLocation({
        consented: true,
        lat: r.lat,
        lng: r.lng,
        label: r.label || district.trim() || pincode.trim(),
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const skipLocation = () => finishLocation(null);

  const finishLocation = (geo) => {
    onLogin(sessionData, geo);
  };

  if (step === "login") {
    return (
      <div>
        <div className="card">
          <h1>🩺 ASHA Sahayak</h1>
          <p className="muted">
            Triage <b>support</b> for frontline health workers. Describe a patient's
            symptoms in your language; get an urgency level, what to do, and the
            nearest health facility — grounded in official protocols.
            This supports your judgment and does not replace a clinician.
          </p>
        </div>
        <form className="card" onSubmit={doLogin}>
          <h2>Sign in</h2>
          {error && <div className="error">{error}</div>}
          <label htmlFor="wid">Worker ID</label>
          <input id="wid" type="text" value={workerId} placeholder="e.g. ASHA-1024"
            onChange={(e) => setWorkerId(e.target.value)} autoComplete="off" />
          <label htmlFor="nm">Name (optional)</label>
          <input id="nm" type="text" value={name} placeholder="Your name"
            onChange={(e) => setName(e.target.value)} autoComplete="off" />
          <div style={{ height: 12 }} />
          <button className="btn" disabled={busy || !workerId.trim()}>
            {busy ? <span className="spinner" /> : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  // location step
  return (
    <div>
      <div className="card">
        <h2>📍 Share your location</h2>
        <p className="muted">
          We use your location only to find the nearest health facility for a patient.
          You can allow GPS, or type your district / PIN code instead. Your location is
          kept only for this session.
        </p>
        {geoMsg && <div className="notice">{geoMsg}</div>}
        {error && <div className="error">{error}</div>}
        <button className="btn" onClick={useBrowserLocation} disabled={busy}>
          Use my current location (GPS)
        </button>
      </div>

      <div className="card">
        <h2>Or enter manually</h2>
        <label htmlFor="dist">District</label>
        <input id="dist" type="text" value={district} placeholder="e.g. Mysuru"
          onChange={(e) => setDistrict(e.target.value)} />
        <label htmlFor="pin">PIN code</label>
        <input id="pin" type="text" value={pincode} placeholder="e.g. 570001"
          onChange={(e) => setPincode(e.target.value)} inputMode="numeric" />
        <div style={{ height: 12 }} />
        <div className="btn-row">
          <button className="btn secondary" onClick={skipLocation} disabled={busy}>Skip</button>
          <button className="btn" onClick={useManualLocation} disabled={busy}>
            {busy ? <span className="spinner" /> : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
