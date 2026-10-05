"""Small self-hostable GeoMesh backend; receives zones, never vehicle routes."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import threading
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES = Literal["ROAD_BLOCK", "ACCIDENT", "CONSTRUCTION", "FLOODING", "POTHOLE",
    "DANGEROUS_ROAD", "PARKING_RESTRICTION", "EMERGENCY_ZONE", "TUNNEL_GNSS_DEGRADED", "CUSTOM_WARNING"]

class GeoFenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str | None = Field(default=None, max_length=64)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: float = Field(ge=20, le=1000)
    category: CATEGORIES
    description: str = Field(max_length=160)
    expires_at_ms: int = Field(gt=0)

class GeoMeshVote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vote: Literal["STILL_PRESENT", "NO_LONGER_PRESENT", "NOT_SURE"]

class GeoMeshStore:
    def __init__(self, path: str = ":memory:", clock=time.time):
        self.clock, self.lock = clock, threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS geofences (
            id TEXT PRIMARY KEY, latitude REAL NOT NULL, longitude REAL NOT NULL, radius_m REAL NOT NULL,
            category TEXT NOT NULL, description TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL, last_verified_at_ms INTEGER, confirmations INTEGER NOT NULL DEFAULT 0,
            denials INTEGER NOT NULL DEFAULT 0, confidence INTEGER NOT NULL DEFAULT 45)""")
        self.db.commit()

    def create(self, item: GeoFenceCreate) -> dict:
        now = int(self.clock() * 1000); zone_id = item.client_id or uuid.uuid4().hex
        if item.expires_at_ms <= now: raise ValueError("expiry_must_be_future")
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO geofences VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (zone_id, item.latitude, item.longitude, item.radius_m, item.category, item.description,
                 now, item.expires_at_ms, None, 0, 0, 45)); self.db.commit()
        return self.get(zone_id)

    def get(self, zone_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM geofences WHERE id=?", (zone_id,)).fetchone()
        return dict(row) if row else None

    def nearby(self, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> list[dict]:
        now = int(self.clock() * 1000)
        rows = self.db.execute("SELECT * FROM geofences WHERE expires_at_ms>? AND latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? ORDER BY confidence DESC LIMIT 500",
            (now, min_lat, max_lat, min_lon, max_lon)).fetchall()
        return [dict(row) for row in rows]

    def vote(self, zone_id: str, vote: str) -> dict | None:
        zone = self.get(zone_id)
        if not zone: return None
        now = int(self.clock() * 1000); confirmations = zone["confirmations"]; denials = zone["denials"]
        if vote == "STILL_PRESENT": confirmations += 1
        if vote == "NO_LONGER_PRESENT": denials += 1
        age_days = max(0, now - zone["created_at_ms"]) // 86_400_000
        confidence = max(0, min(100, 45 + min(confirmations, 6) * 8 - min(denials, 5) * 12 - age_days * 3 + (8 if vote == "STILL_PRESENT" else 0)))
        with self.lock:
            self.db.execute("UPDATE geofences SET confirmations=?, denials=?, confidence=?, last_verified_at_ms=? WHERE id=?",
                (confirmations, denials, confidence, now if vote != "NOT_SURE" else zone["last_verified_at_ms"], zone_id)); self.db.commit()
        return self.get(zone_id)

    def health(self) -> dict:
        now = int(self.clock() * 1000)
        active = self.db.execute("SELECT COUNT(*) FROM geofences WHERE expires_at_ms>?", (now,)).fetchone()[0]
        return {"status": "ok", "storage": "sqlite", "active_geofences": active,
                "server_time": datetime.now(timezone.utc).isoformat()}
