"""
Facility finder.
Primary source = Google Places API (New) when GOOGLE_MAPS_API_KEY is set
(richer names/phones); falls back to the free OpenStreetMap Overpass API.
Never invents a facility: if both return nothing, it returns an empty list plus
a note pointing to the district helpline / 108 ambulance.
"""
from __future__ import annotations

import math
from typing import Optional

import httpx

from app.config import (
    GOOGLE_MAPS_API_KEY,
    GOOGLE_PLACES_URL,
    OVERPASS_URL,
    NOMINATIM_URL,
    FACILITY_RADIUS_M,
    FACILITY_N,
    EMERGENCY_HELPLINE,
)

# Map triage urgency -> preferred OSM facility tags (higher tier for emergencies).
_EMERGENCY_TAGS = ["hospital"]
_ROUTINE_TAGS = ["clinic", "doctors", "hospital"]

# Google Places (New) included types per urgency.
_GOOGLE_EMERGENCY_TYPES = ["hospital"]
_GOOGLE_ROUTINE_TYPES = ["hospital", "doctor", "medical_lab", "pharmacy"]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def directions_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"


def _classify(tags: dict) -> str:
    amenity = tags.get("amenity", "")
    name = (tags.get("name", "") + " " + tags.get("name:en", "")).lower()
    if "community health" in name or "chc" in name:
        return "Community Health Centre (CHC)"
    if "primary health" in name or "phc" in name:
        return "Primary Health Centre (PHC)"
    if "sub" in name and "cent" in name:
        return "Sub-centre"
    if "district" in name and "hospital" in name:
        return "District Hospital"
    return {
        "hospital": "Hospital",
        "clinic": "Clinic",
        "doctors": "Doctor / clinic",
    }.get(amenity, amenity or "Health facility")


def _classify_google(name: str, primary: str) -> str:
    n = name.lower()
    if "community health" in n or "chc" in n:
        return "Community Health Centre (CHC)"
    if "primary health" in n or "phc" in n:
        return "Primary Health Centre (PHC)"
    if "sub" in n and "cent" in n:
        return "Sub-centre"
    if "district" in n and "hospital" in n:
        return "District Hospital"
    return {
        "hospital": "Hospital",
        "doctor": "Doctor / clinic",
        "medical_lab": "Diagnostic lab",
        "pharmacy": "Pharmacy",
    }.get(primary, "Health facility")


def _google_places_nearby(lat: float, lng: float, types: list[str], radius: int) -> list[dict]:
    """Google Places API (New) Nearby Search. Returns [] if the key is unset."""
    if not GOOGLE_MAPS_API_KEY:
        return []
    body = {
        "includedTypes": types,
        "maxResultCount": 20,
        # Default POPULARITY ranking surfaces real, established hospitals; DISTANCE
        # ranking tends to surface junk pins dropped at the exact search point. We
        # sort the popular results by our own haversine distance afterwards.
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius),
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ("places.displayName,places.location,places.primaryType,"
                             "places.nationalPhoneNumber,places.internationalPhoneNumber"),
    }
    r = httpx.post(GOOGLE_PLACES_URL, json=body, headers=headers, timeout=25)
    r.raise_for_status()
    out = []
    for p in r.json().get("places", []):
        loc = p.get("location", {})
        if "latitude" not in loc or "longitude" not in loc:
            continue
        name = (p.get("displayName", {}) or {}).get("text", "Unnamed facility")
        out.append({
            "name": name,
            "type": _classify_google(name, p.get("primaryType", "")),
            "lat": float(loc["latitude"]),
            "lng": float(loc["longitude"]),
            "phone": p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber"),
        })
    return out


def _overpass_query(lat: float, lng: float, tags: list[str], radius: int) -> list[dict]:
    selectors = "".join(
        f'node["amenity"="{t}"](around:{radius},{lat},{lng});'
        f'way["amenity"="{t}"](around:{radius},{lat},{lng});'
        for t in tags
    )
    q = f"[out:json][timeout:25];({selectors});out center tags;"
    r = httpx.post(OVERPASS_URL, data={"data": q},
                   headers={"User-Agent": "ASHA-Sahayak/1.0"}, timeout=30)
    r.raise_for_status()
    elements = r.json().get("elements", [])
    out = []
    for el in elements:
        t = el.get("tags", {})
        flat = el.get("lat") or (el.get("center") or {}).get("lat")
        flng = el.get("lon") or (el.get("center") or {}).get("lon")
        if flat is None or flng is None:
            continue
        out.append({
            "name": t.get("name") or t.get("name:en") or "Unnamed facility",
            "type": _classify(t),
            "lat": float(flat),
            "lng": float(flng),
            "phone": t.get("phone") or t.get("contact:phone"),
        })
    return out


def find_facilities(lat: Optional[float], lng: Optional[float], urgency_tag: str,
                    n: int = FACILITY_N) -> tuple[list[dict], Optional[str]]:
    """Return (facilities, note). Note is set when nothing usable was found."""
    helpline_note = (
        f"No coordinates available. Call the district health helpline or the "
        f"{EMERGENCY_HELPLINE} ambulance for transport."
    )
    if lat is None or lng is None:
        return [], helpline_note

    found: list[dict] = []
    source = None
    last_err = None

    # 1) Google Places (New) — preferred when a key is configured.
    if GOOGLE_MAPS_API_KEY:
        gtypes = _GOOGLE_EMERGENCY_TYPES if urgency_tag == "emergency" else _GOOGLE_ROUTINE_TYPES
        try:
            found = _google_places_nearby(lat, lng, gtypes, FACILITY_RADIUS_M)
            source = "google"
        except Exception as e:
            last_err = e  # fall through to OSM

    # 2) OpenStreetMap Overpass — free fallback.
    if not found:
        tags = _EMERGENCY_TAGS if urgency_tag == "emergency" else _ROUTINE_TAGS
        try:
            found = _overpass_query(lat, lng, tags, FACILITY_RADIUS_M)
            source = "osm"
        except Exception as e:
            last_err = e

    if not found:
        if last_err is not None:
            return [], (f"Could not reach the facility service "
                        f"({last_err.__class__.__name__}). Use the {EMERGENCY_HELPLINE} "
                        f"ambulance line or your known PHC/CHC.")
        return [], (f"No facilities found within {FACILITY_RADIUS_M // 1000} km. "
                    f"Call the district health helpline or {EMERGENCY_HELPLINE}.")

    for f in found:
        f["distance_km"] = round(haversine_km(lat, lng, f["lat"], f["lng"]), 1)
        f["directions_url"] = directions_url(f["lat"], f["lng"])
        f["source"] = source
    found.sort(key=lambda x: x["distance_km"])
    return found[:n], None


def reverse_geocode(lat: float, lng: float) -> Optional[str]:
    """Best-effort district/area label for display. Never blocks the flow."""
    try:
        r = httpx.get(
            f"{NOMINATIM_URL}/reverse",
            params={"lat": lat, "lon": lng, "format": "json", "zoom": 10},
            headers={"User-Agent": "ASHA-Sahayak/1.0"},
            timeout=10,
        )
        r.raise_for_status()
        a = r.json().get("address", {})
        parts = [a.get("state_district") or a.get("county"), a.get("state")]
        return ", ".join(p for p in parts if p) or None
    except Exception:
        return None


def geocode_district(district: Optional[str], pincode: Optional[str]) -> Optional[tuple[float, float]]:
    """Manual fallback: turn a typed district/PIN into coordinates."""
    query = pincode or district
    if not query:
        return None
    try:
        r = httpx.get(
            f"{NOMINATIM_URL}/search",
            params={"q": f"{query}, India", "format": "json", "limit": 1},
            headers={"User-Agent": "ASHA-Sahayak/1.0"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None
    return None
