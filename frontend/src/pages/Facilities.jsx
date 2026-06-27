import React, { useEffect, useState } from "react";
import { useLocation, Link } from "react-router-dom";
import { MapContainer, TileLayer, Marker, Popup, Circle } from "react-leaflet";
import L from "leaflet";
import iconUrl from "leaflet/dist/images/marker-icon.png";
import iconRetina from "leaflet/dist/images/marker-icon-2x.png";
import shadowUrl from "leaflet/dist/images/marker-shadow.png";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

// Fix Leaflet's default marker icon paths under a bundler.
const DefaultIcon = L.icon({
  iconUrl, iconRetinaUrl: iconRetina, shadowUrl,
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

const homeIcon = L.divIcon({
  className: "", html: "<div style='font-size:26px'>📍</div>", iconSize: [26, 26], iconAnchor: [13, 13],
});

export default function Facilities() {
  const { geo } = useApp();
  const location = useLocation();
  const [facilities, setFacilities] = useState(location.state?.facilities || []);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(!location.state?.facilities);
  const [error, setError] = useState("");

  useEffect(() => {
    if (location.state?.facilities) return;
    if (!geo?.lat) {
      setLoading(false);
      setNote("No location set. Sign in again and share your location to see nearby facilities.");
      return;
    }
    let alive = true;
    api
      .facilities(geo.lat, geo.lng, "emergency")
      .then((r) => {
        if (!alive) return;
        setFacilities(r.facilities || []);
        setNote(r.note || "");
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [geo, location.state]);

  const center = geo?.lat
    ? [geo.lat, geo.lng]
    : facilities[0]
    ? [facilities[0].lat, facilities[0].lng]
    : [20.5937, 78.9629]; // India fallback

  if (loading) return <div className="center-spin"><span className="spinner" /> Finding facilities…</div>;

  return (
    <div>
      <div className="card">
        <h1>Nearby facilities</h1>
        {error && <div className="error">{error}</div>}
        {note && <div className="notice">{note}</div>}
        {geo?.lat && (
          <div className="map-wrap">
            <MapContainer center={center} zoom={11} scrollWheelZoom={false}>
              <TileLayer
                attribution='&copy; OpenStreetMap'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <Marker position={center} icon={homeIcon}>
                <Popup>You are here</Popup>
              </Marker>
              <Circle center={center} radius={5000} pathOptions={{ color: "#0b6e4f", fillOpacity: 0.05 }} />
              {facilities.map((f, i) => (
                <Marker key={i} position={[f.lat, f.lng]}>
                  <Popup>
                    <b>{f.name}</b><br />
                    {f.type}{f.distance_km != null ? ` · ${f.distance_km} km` : ""}<br />
                    <a href={f.directions_url} target="_blank" rel="noreferrer">Directions</a>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          </div>
        )}
      </div>

      {facilities.map((f, i) => (
        <div className="facility" key={i}>
          <div>
            <div className="fname">{f.name}</div>
            <div className="ftype">{f.type}{f.distance_km != null ? ` · ${f.distance_km} km` : ""}</div>
          </div>
          <div className="fbtns">
            {f.phone && <a className="act call" href={`tel:${f.phone}`}>📞 Call</a>}
            <a className="act" href={f.directions_url} target="_blank" rel="noreferrer">🧭 Go</a>
          </div>
        </div>
      ))}

      <Link className="btn secondary" to="/triage"
        style={{ display: "block", textAlign: "center", textDecoration: "none", marginTop: 6 }}>
        Back to triage
      </Link>
    </div>
  );
}
