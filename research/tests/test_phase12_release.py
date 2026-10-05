from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from idr.phase12 import FROZEN_MODEL_SHA256, scan_text_for_secrets, sha256_file, tracked_private_data_findings


ROOT = Path(__file__).resolve().parents[1]


def test_phase12_frozen_model_hash_is_unchanged() -> None:
    assert sha256_file(ROOT / "models/phase5/io_vnbd_s1/velocity_gru.pt") == FROZEN_MODEL_SHA256


def test_phase12_final_public_artifacts_exist() -> None:
    required = (
        "docs/FINAL_TECHNICAL_OVERVIEW.md",
        "docs/FINAL_INSTALL_AND_RUN.md",
        "docs/HACKATHON_RUNBOOK.md",
        "docs/phase12_judge_demo.md",
        "docs/phase12_judge_qna.md",
        "docs/assets/phase12_architecture.svg",
        "docs/assets/phase12_state_machine.svg",
        "results/phase12/FINAL_JUDGE_SUMMARY.md",
    )
    assert all((ROOT / item).is_file() for item in required)


def test_phase12_release_surface_contains_no_secret_patterns() -> None:
    paths = list((ROOT / "android/app/src/main").rglob("*")) + list((ROOT / "docs").glob("FINAL*"))
    assert scan_text_for_secrets(paths) == []


def test_phase12_private_phone_data_is_not_tracked() -> None:
    assert tracked_private_data_findings(ROOT) == []


def test_phase12_android_build_identity_and_optional_map_networking() -> None:
    build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    # Product expansion increments the release identity; estimator checks stay unchanged.
    assert 'versionName = "2.4.0"' in build
    assert "versionCode = 41" in build
    assert 'applicationId = "org.sih26168.idrlogger"' in build
    assert "android.permission.INTERNET" in manifest
    assert 'com.google.android.gms:play-services-maps:20.0.0' in build
    assert 'com.google.android.gms:play-services-maps3d:0.2.2' in build
    assert 'org.maplibre.gl:android-sdk:13.4.1' in build
    assert 'manifestPlaceholders["MAPS_API_KEY"]' in build
    assert 'android:value="${MAPS_API_KEY}"' in manifest
    assert 'manifestPlaceholders["MAPS3D_API_KEY"]' in build
    assert 'android:value="${MAPS3D_API_KEY}"' in manifest
    # mdpi allows Android to scale the 3D marker correctly on high-density phones.
    marker = ROOT / "android/app/src/main/res/drawable-mdpi/navghost_vehicle_arrow_3d.png"
    assert marker.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    activity = (ROOT / "android/app/src/main/java/org/sih26168/idrlogger/ui/MainActivity.kt").read_text(encoding="utf-8")
    assert "onSaveInstanceState" in activity
    assert "demoController.pause()" in activity
    assert "setOnApplyWindowInsetsListener" in activity
    subprocess.run([sys.executable, str(ROOT / "tools/run_final_verification.py"), "--help"], cwd=ROOT, check=True, capture_output=True, text=True)


def test_phase12_map_and_public_reference_are_isolated_by_api_shape() -> None:
    provider = (ROOT / "android/app/src/main/java/org/sih26168/idrlogger/map/MapProvider.kt").read_text(encoding="utf-8")
    replay = (ROOT / "android/app/src/main/java/org/sih26168/idrlogger/demo/PublicBenchmarkFixture.kt").read_text(encoding="utf-8")
    assert "fun presentation()" in provider
    assert "fun location" not in provider
    assert "EngineMarkerPolicy.from" not in provider
    assert "never passed" in replay
