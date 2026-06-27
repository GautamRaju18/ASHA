import React, { Suspense, createContext, useContext, useEffect, useState } from "react";
import { Routes, Route, Navigate, Link, useNavigate, useLocation } from "react-router-dom";
import { session as sessionStore } from "./api.js";
import Login from "./pages/Login.jsx";
import Triage from "./pages/Triage.jsx";
import Result from "./pages/Result.jsx";
import History from "./pages/History.jsx";

const Facilities = React.lazy(() => import("./pages/Facilities.jsx")); // lazy-load map chunk

// --- App-wide context: session + geolocation ---
const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

function TopBar() {
  const { sess, geo, logout } = useApp();
  if (!sess) return null;
  return (
    <header className="topbar">
      <div>
        <div className="brand">🩺 ASHA Sahayak</div>
        <div className="loc">
          {geo?.label
            ? `📍 ${geo.label}`
            : geo?.lat
            ? `📍 ${geo.lat.toFixed(2)}, ${geo.lng.toFixed(2)}`
            : "📍 location not set"}
        </div>
      </div>
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <Link to="/triage">New</Link>
        <Link to="/history">History</Link>
        <button className="link" onClick={logout}>Sign out</button>
      </div>
    </header>
  );
}

function OfflineBanner() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  if (online) return null;
  return <div className="offline">⚠ No internet connection. Triage needs a live connection.</div>;
}

function Protected({ children }) {
  const { sess } = useApp();
  if (!sess) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  const [sess, setSess] = useState(() => sessionStore.get());
  const [geo, setGeo] = useState(() => sessionStore.get()?.geo || null);
  const navigate = useNavigate();
  const location = useLocation();

  const onLogin = (s, g) => {
    const full = { ...s, geo: g || null };
    sessionStore.set(full);
    setSess(full);
    setGeo(g || null);
    navigate("/triage");
  };

  const updateGeo = (g) => {
    setGeo(g);
    const cur = sessionStore.get() || sess;
    if (cur) sessionStore.set({ ...cur, geo: g });
  };

  const logout = () => {
    sessionStore.clear();
    setSess(null);
    setGeo(null);
    navigate("/");
  };

  const ctx = { sess, geo, onLogin, updateGeo, logout };

  return (
    <AppCtx.Provider value={ctx}>
      <div className="app">
        <OfflineBanner />
        <TopBar />
        <main className="content">
          <Routes>
            <Route path="/" element={sess && location.pathname === "/" ? <Navigate to="/triage" replace /> : <Login />} />
            <Route path="/triage" element={<Protected><Triage /></Protected>} />
            <Route path="/result/:caseId" element={<Protected><Result /></Protected>} />
            <Route
              path="/facilities"
              element={
                <Protected>
                  <Suspense fallback={<div className="center-spin"><span className="spinner" /> Loading map…</div>}>
                    <Facilities />
                  </Suspense>
                </Protected>
              }
            />
            <Route path="/history" element={<Protected><History /></Protected>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <div className="footer-note">
          Decision support for trained health workers — not a diagnosis. When in doubt, refer.
        </div>
      </div>
    </AppCtx.Provider>
  );
}
