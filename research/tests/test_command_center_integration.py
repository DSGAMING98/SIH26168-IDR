"""Protect the completed estimator boundary and explicitly labelled protocol demo."""
import hashlib
from pathlib import Path

from server.demo import frame, STATES

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android/app/src/main/java/org/sih26168/idrlogger"


def test_frozen_gru_is_unchanged():
    assert hashlib.sha256((ROOT / "models/phase5/io_vnbd_s1/velocity_gru.pt").read_bytes()).hexdigest() == "fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec"


def test_telemetry_observer_has_no_engine_input_channel():
    client = (JAVA / "telemetry/TelemetryClient.kt").read_text(encoding="utf-8")
    transport = (JAVA / "telemetry/OkHttpTelemetryTransport.kt").read_text(encoding="utf-8")
    projection = (JAVA / "telemetry/TelemetryMessage.kt").read_text(encoding="utf-8")
    assert "AtomicReference<Pending?>" in client and "producerSessionId" in client
    assert "override fun onMessage" not in transport
    assert "LiveIdrSample" not in projection and "PhysicalGnssFix" not in projection
    assert '"mode" to "LIVE"' in projection


def test_service_only_publishes_completed_engine_navigation():
    service = (JAVA / "service/SensorLoggingService.kt").read_text(encoding="utf-8")
    assert "AndroidNavigationAdapter(idrEngine::process)" in service
    adapter = (JAVA / "engine/ExternalSensorAdapter.kt").read_text(encoding="utf-8")
    assert "fun accept(sample: LiveIdrSample): NavigationState = sink.accept(sample)" in adapter
    assert service.index("navigationInput.accept(sample)") < service.index("telemetryClient?.publish(navigation")
    assert "val producerSessionId = telemetrySessionId" in service
    assert "TelemetrySerializer" not in service


def test_demo_is_explicit_and_has_no_fabricated_physical_diagnostics():
    for index in (0, 25, 50, 75, 100, 125):
        packet = frame(index, "test-demo", 30)
        assert packet.mode == "DEMO" and packet.recording is False
        assert packet.estimated_position.latitude is None
        assert packet.gnss_observability.satellites_visible is None
        assert packet.gnss_observability.physical_callback_count is None
        assert packet.sensors.runtime_hz is None
        assert packet.device.battery_percent is None
        assert packet.engine.avg_ms is None
    assert tuple(frame(i, "test-demo", 30).navigation.localization_state for i in (0, 25, 50, 75, 100, 125)) == STATES


def test_cleartext_is_host_scoped_and_never_global():
    manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert "NAVGHOST_LAN_HOST" in build
    assert '<base-config cleartextTrafficPermitted="false"' in build
