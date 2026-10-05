from fastapi.testclient import TestClient

from server.app import create_app
from server.geomesh import GeoMeshStore


def payload(expires=9_999_999_999_999):
    return {"client_id": "local-zone-1", "latitude": 12.9716, "longitude": 77.5946,
            "radius_m": 75, "category": "POTHOLE", "description": "Road damage", "expires_at_ms": expires}


def test_geomesh_create_nearby_confirm_deny_and_health():
    app = create_app(geomesh_store=GeoMeshStore())
    with TestClient(app) as client:
        created = client.post("/api/geomesh/geofences", json=payload())
        assert created.status_code == 201 and created.json()["confidence"] == 45
        nearby = client.get("/api/geomesh/geofences", params={"min_lat": 12.9, "max_lat": 13.0, "min_lon": 77.5, "max_lon": 77.7})
        assert [item["id"] for item in nearby.json()["geofences"]] == ["local-zone-1"]
        confirmed = client.post("/api/geomesh/geofences/local-zone-1/confirmation", json={"vote": "STILL_PRESENT"})
        assert confirmed.json()["confirmations"] == 1 and confirmed.json()["confidence"] > 45
        denied = client.post("/api/geomesh/geofences/local-zone-1/denial")
        assert denied.json()["denials"] == 1 and denied.json()["confidence"] < confirmed.json()["confidence"]
        assert client.get("/api/geomesh/health").json()["active_geofences"] == 1


def test_geomesh_rejects_expired_invalid_and_unknown_zones():
    app = create_app(geomesh_store=GeoMeshStore(clock=lambda: 1000))
    with TestClient(app) as client:
        assert client.post("/api/geomesh/geofences", json=payload(expires=999_999)).status_code == 422
        assert client.get("/api/geomesh/geofences", params={"min_lat": 5, "max_lat": 4, "min_lon": 1, "max_lon": 2}).status_code == 422
        assert client.post("/api/geomesh/geofences/missing/denial").status_code == 404
