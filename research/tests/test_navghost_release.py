from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android/app/src/main"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_navghost_is_primary_visible_product_identity() -> None:
    assert "NavGhost" in _read("android/app/src/main/res/values/strings.xml")
    activity = _read("android/app/src/main/java/org/sih26168/idrlogger/ui/MainActivity.kt")
    assert 'label("NAVGHOST"' in activity
    assert "NAVIGATION BEYOND GNSS" in activity
    assert "ABOUT NAVGHOST" in activity


def test_official_maps_sdk_uses_local_untracked_key_placeholder() -> None:
    build = _read("android/app/build.gradle.kts")
    manifest = _read("android/app/src/main/AndroidManifest.xml")
    ignore = _read(".gitignore")
    assert 'getProperty("MAPS_API_KEY")' in build
    assert 'com.google.android.gms:play-services-maps:20.0.0' in build
    assert 'android:value="${MAPS_API_KEY}"' in manifest
    assert "/android/local.properties" in ignore


def test_map_cannot_become_a_location_source() -> None:
    surface = _read("android/app/src/main/java/org/sih26168/idrlogger/ui/NavGhostMapSurface.kt")
    provider = _read("android/app/src/main/java/org/sih26168/idrlogger/map/MapProvider.kt")
    assert "isMyLocationEnabled = false" in surface
    assert "isMyLocationButtonEnabled = false" in surface
    assert "FusedLocationProvider" not in surface
    assert "fun location" not in provider
    assert "EngineMarkerPolicy.from(snapshot)" in surface


def test_local_fallback_and_premium_controls_are_present() -> None:
    surface = _read("android/app/src/main/java/org/sih26168/idrlogger/ui/NavGhostMapSurface.kt")
    activity = _read("android/app/src/main/java/org/sih26168/idrlogger/ui/MainActivity.kt")
    assert "LOCAL MAP" in surface
    assert "hasValidatedNetwork" in surface
    assert "RECENTER" in activity
    assert "MAP_TYPE_SATELLITE" in surface
    assert "SHOW_ALL" in activity
    assert "performHapticFeedback" in activity


def test_navghost_launcher_and_splash_resources_exist() -> None:
    required = (
        "android/app/src/main/res/drawable/ic_navghost_mark.xml",
        "android/app/src/main/res/drawable/ic_navghost_marker.xml",
        "android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml",
        "android/app/src/main/res/mipmap-anydpi-v33/ic_launcher.xml",
    )
    assert all((ROOT / path).is_file() for path in required)
    assert "ic_navghost_mark" in _read("android/app/src/main/res/drawable/launch_background.xml")
    assert "ic_navghost_mark" in _read("android/app/src/main/res/values-v31/styles.xml")


def test_hackathon_polish_preserves_renderer_and_scopes_storage() -> None:
    activity = _read("android/app/src/main/java/org/sih26168/idrlogger/ui/MainActivity.kt")
    google3d = _read("android/app/src/main/java/org/sih26168/idrlogger/ui/Google3dMapSurface.kt")
    storage = _read("android/app/src/main/java/org/sih26168/idrlogger/ui/AppStorageAudit.kt")
    assert "VisualTheme.SYSTEM" in activity
    assert "SIMULATED GNSS BLACKOUT" in activity
    assert "initialMapMode: Int = Map3DMode.HYBRID" in google3d
    assert "Map3DView(context, initialMapMode)" in google3d
    assert 'File(context.cacheDir, "navghost")' in storage
    assert 'File(context.filesDir, "recordings")' in storage
    assert "deleteOwned(it, root)" in storage


def test_maps_20_legacy_renderer_compatibility_is_optional() -> None:
    manifest = _read("android/app/src/main/AndroidManifest.xml")
    assert '<uses-library android:name="org.apache.http.legacy" android:required="false" />' in manifest
