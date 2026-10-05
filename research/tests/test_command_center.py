"""Protocol/security/lifecycle tests using synthetic estimates, never private traces."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from server.app import create_app, guarded_send
from server.schema import Telemetry
from server.state import Hub, Limits, RejectedTelemetry

FIXTURE = Path(__file__).parent / "fixtures" / "telemetry_v1.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def app():
    return create_app()


def increment(payload, sequence, state=None):
    data = deepcopy(payload)
    data["sequence"] = sequence
    data["timestamp_ns"] = str(int(data["timestamp_ns"]) + sequence * 100000000)
    if state:
        data["navigation"]["localization_state"] = state
    return data


def test_versioned_shared_fixture_preserves_timestamp_precision(payload):
    model = Telemetry.model_validate_json(json.dumps(payload))
    assert model.model_dump(mode="json") == payload
    assert model.timestamp_ns == "12345678901234567"


def test_nullable_measurements_remain_unavailable(payload):
    for section in ("estimated_position", "motion", "sensors", "gnss_observability", "engine", "device"):
        payload[section] = {key: None for key in payload[section]}
    model = Telemetry.model_validate(payload)
    assert model.gnss_observability.satellites_visible is None
    assert model.estimated_position.latitude is None
    assert model.device.battery_percent is None


@pytest.mark.parametrize("field", ["raw_gnss", "physical_location", "vbox", "google_maps_api_key", "filesystem_path"])
def test_gnss_blackout_telemetry_rejects_hidden_reference_and_secret_fields(payload, field):
    payload["navigation"]["localization_state"] = "IDR_ACTIVE"
    payload["navigation"]["gnss_state"] = "SIMULATED_BLACKOUT"
    payload[field] = {"latitude": 11.1, "longitude": 22.2}
    with pytest.raises(ValidationError):
        Telemetry.model_validate(payload)


@pytest.mark.parametrize("field", ["altitude", "bearing", "raw_speed_mps", "physical_latitude"])
def test_nested_estimate_allowlist_rejects_raw_gnss_fields(payload, field):
    payload["estimated_position"][field] = 99.0
    with pytest.raises(ValidationError):
        Telemetry.model_validate(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1.0, 4000.0, "15.0", True])
def test_nonfinite_out_of_range_and_wrong_type_rejected(payload, value):
    payload["motion"]["speed_kmh"] = value
    with pytest.raises(ValidationError):
        Telemetry.model_validate_json(json.dumps(payload))


def test_unknown_version_and_unpaired_position_rejected(payload):
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        Telemetry.model_validate(payload)
    payload["schema_version"] = 1
    payload["estimated_position"]["longitude"] = None
    with pytest.raises(ValidationError):
        Telemetry.model_validate(payload)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_schema_version_is_an_exact_json_integer(payload, version):
    payload["schema_version"] = version
    with pytest.raises(ValidationError):
        Telemetry.model_validate_json(json.dumps(payload))


def test_invalid_calendar_timestamp_rejected(payload):
    payload["wall_time_utc"] = "2026-99-99T12:00:00Z"
    with pytest.raises(ValidationError):
        Telemetry.model_validate(payload)


def test_hub_history_and_transitions_are_bounded(payload):
    hub = Hub(replace(Limits(), history_points=3, history_events=2))
    for seq in range(8):
        hub.accept(Telemetry.model_validate(increment(payload, seq, "GNSS_ACTIVE" if seq < 5 else "IDR_ACTIVE")), "phone")
    session = hub.sessions[payload["session_id"]]
    assert len(session.history) == 3
    assert [x["sequence"] for x in session.history] == [5, 6, 7]
    assert [x["state"] for x in session.timeline] == ["GNSS_ACTIVE", "IDR_ACTIVE"]
    assert len(session.events) == 2  # No event for every telemetry frame.


def test_out_of_order_frames_do_not_change_estimate(payload):
    hub = Hub()
    hub.accept(Telemetry.model_validate(increment(payload, 2)), "phone")
    with pytest.raises(RejectedTelemetry, match="out_of_order"):
        hub.accept(Telemetry.model_validate(increment(payload, 1)), "phone")
    future = increment(payload, 3)
    future["timestamp_ns"] = "1"
    with pytest.raises(RejectedTelemetry, match="out_of_order"):
        hub.accept(Telemetry.model_validate(future), "phone")
    assert hub.sessions[payload["session_id"]].last_sequence == 2


def test_session_ownership_and_reconnect(payload):
    hub = Hub()
    hub.accept(Telemetry.model_validate(payload), "phone-a")
    with pytest.raises(RejectedTelemetry, match="session_owned"):
        hub.accept(Telemetry.model_validate(increment(payload, 1)), "phone-b")
    hub.disconnect("phone-a")
    hub.accept(Telemetry.model_validate(increment(payload, 1)), "phone-b")
    hub.disconnect("phone-a")  # An old disconnect cannot take down a new owner.
    assert hub.sessions[payload["session_id"]].owner == "phone-b"


def test_stale_offline_and_ttl_cleanup(payload):
    now = [0.0]
    hub = Hub(clock=lambda: now[0])
    session = hub.accept(Telemetry.model_validate(payload), "phone")
    assert hub.connection_status(session) == "CONNECTED"
    now[0] = 4
    assert hub.connection_status(session) == "STALE"
    hub.disconnect("phone")
    assert hub.connection_status(session) == "OFFLINE"
    now[0] = 601
    assert hub.cleanup() == [payload["session_id"]]
    assert not hub.sessions


def test_session_limit_evicts_only_offline_sessions(payload):
    hub = Hub(replace(Limits(), max_sessions=1))
    hub.accept(Telemetry.model_validate(payload), "phone")
    payload["session_id"] = "other"
    with pytest.raises(RejectedTelemetry, match="session_limit"):
        hub.accept(Telemetry.model_validate(payload), "other")
    hub.disconnect("phone")
    hub.accept(Telemetry.model_validate(payload), "other")
    assert list(hub.sessions) == ["other"]


def test_slow_viewer_latest_state_coalescing_is_bounded(payload):
    hub = Hub(replace(Limits(), max_viewers=1))
    queue = hub.subscribe()
    for seq in range(100):
        hub.accept(Telemetry.model_validate(increment(payload, seq)), "phone")
    assert queue.qsize() == 1
    assert queue.get_nowait()["session"]["latest"]["sequence"] == 99
    assert hub.coalesced == 100
    with pytest.raises(RejectedTelemetry, match="viewer_limit"):
        hub.subscribe()


def test_slow_socket_send_has_deadline():
    class SlowSocket:
        async def send_json(self, _):
            await asyncio.sleep(10)
    async def run():
        with pytest.raises(asyncio.TimeoutError):
            await guarded_send(SlowSocket(), {}, 0.001)
    asyncio.run(run())


def test_http_dashboard_assets_health_and_privacy_headers(app):
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "COMMAND CENTER" in response.text
        assert "geolocation=()" in response.headers["permissions-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/api/status").json()["storage"] == "memory_only"
        for path in ("dashboard.js", "dashboard.css", "vendor/leaflet.js", "vendor/leaflet.css"):
            assert client.get("/static/" + path).status_code == 200


def test_phone_to_multiple_viewers_and_disconnect_cleanup(app, payload):
    with TestClient(app) as client:
        with client.websocket_connect("/ws/dashboard") as first, client.websocket_connect("/ws/dashboard") as second:
            assert first.receive_json()["type"] == "snapshot"
            assert second.receive_json()["type"] == "snapshot"
            with client.websocket_connect("/ws/telemetry") as phone:
                phone.send_json(payload)
                assert phone.receive_json() == {"type": "accepted", "sequence": 0}
                for viewer in (first, second):
                    packet = viewer.receive_json()
                    assert packet["session"]["latest"] == payload
                assert client.get("/api/status").json()["connected_phones"] == 1
            # Process the explicit disconnect notification before checking status.
            assert first.receive_json()["sessions"][0]["connection"] == "OFFLINE"
            assert client.get("/api/status").json()["connected_phones"] == 0
        # TestClient delivers the disconnect asynchronously to the application task.
        # Verify prompt cleanup without making the assertion depend on thread scheduling.
        deadline = time.monotonic() + 1.0
        while app.state.hub.viewers and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not app.state.hub.viewers
    assert not app.state.hub.sessions  # Lifespan does not persist telemetry.


def test_malformed_frame_unknown_version_and_invalid_field_are_recoverable(app, payload):
    with TestClient(app) as client, client.websocket_connect("/ws/telemetry") as phone:
        phone.send_text("not json")
        assert phone.receive_json()["code"] == "invalid_telemetry"
        invalid = deepcopy(payload)
        invalid["schema_version"] = 99
        phone.send_json(invalid)
        assert phone.receive_json()["code"] == "invalid_telemetry"
        invalid = deepcopy(payload)
        invalid["google_maps_api_key"] = "SYNTHETIC_SECRET_MUST_NOT_BE_ECHOED"
        phone.send_json(invalid)
        error = phone.receive_json()
        assert "SYNTHETIC_SECRET" not in json.dumps(error)
        phone.send_json(payload)
        assert phone.receive_json()["type"] == "accepted"
        assert app.state.hub.rejected == 3


def test_persistent_invalid_sender_is_closed_after_five_errors(app):
    with TestClient(app) as client, client.websocket_connect("/ws/telemetry") as phone:
        for _ in range(5):
            phone.send_text("{}")
            assert phone.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as closed:
            phone.receive_json()
        assert closed.value.code == 1008


def test_oversized_frame_is_closed_without_broadcast(app):
    with TestClient(app) as client, client.websocket_connect("/ws/telemetry") as phone:
        phone.send_text(" " * 16385)
        with pytest.raises(WebSocketDisconnect) as closed:
            phone.receive_json()
        assert closed.value.code == 1009
        assert app.state.hub.accepted == 0


def test_session_switch_and_duplicate_sequence_rejected(app, payload):
    with TestClient(app) as client, client.websocket_connect("/ws/telemetry") as phone:
        phone.send_json(payload)
        phone.receive_json()
        phone.send_json(payload)
        assert phone.receive_json()["code"] == "out_of_order"
        payload["session_id"] = "different-session"
        phone.send_json(payload)
        assert phone.receive_json()["code"] == "session_changed"


@pytest.mark.parametrize("origin", ["https://malicious.example", "null", "http://testserver/extra", "http://[bad-ipv6"])
def test_cross_origin_websocket_rejected(app, origin):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/dashboard", headers={"origin": origin}):
                pass


def test_same_origin_dashboard_and_no_phone_control_endpoint(app):
    with TestClient(app) as client, client.websocket_connect("/ws/dashboard", headers={"origin":"http://testserver"}) as viewer:
        assert viewer.receive_json()["type"] == "snapshot"
        viewer.send_json({"command": "change_engine"})
        with pytest.raises(WebSocketDisconnect) as closed:
            viewer.receive_json()
        assert closed.value.code == 1008


def test_dashboard_has_no_browser_location_or_external_script_dependency():
    static = Path(__file__).parents[1] / "server" / "static"
    js = (static / "dashboard.js").read_text(encoding="utf-8")
    html = (static / "index.html").read_text(encoding="utf-8")
    assert "navigator.geolocation" not in js
    assert "getCurrentPosition" not in js
    assert "watchPosition" not in js
    assert 'src="https://' not in html
    assert "MAX_POINTS = 600" in js
    assert "textContent" in js


def test_server_has_no_localization_engine_dependency():
    server = Path(__file__).parents[1] / "server"
    for name in ("app.py", "state.py", "schema.py"):
        source = (server / name).read_text(encoding="utf-8")
        assert "from idr" not in source
        assert "import torch" not in source
