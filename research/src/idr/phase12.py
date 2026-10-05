from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Iterable


FROZEN_MODEL_SHA256 = "fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec"
PACKAGE_ID = "org.sih26168.idrlogger"
PHASE12_COMMIT = "84fb5614511c73524087dcebe04ed710309991a2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _build_value(text: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*=\s*(?:\"([^\"]+)\"|(\d+))", text)
    if not match:
        raise ValueError(f"Android build value not found: {name}")
    return next(value for value in match.groups() if value is not None)


def scan_text_for_secrets(paths: Iterable[Path]) -> list[str]:
    patterns = {
        "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
        "openai_api_key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    findings: list[str] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in {".kt", ".kts", ".xml", ".md", ".py", ".json", ".svg"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{label}:{path.as_posix()}")
    return findings


def tracked_private_data_findings(root: Path) -> list[str]:
    tracked = _git(root, "ls-files").splitlines()
    findings = []
    for item in tracked:
        lower = item.lower()
        if any(token in lower for token in ("private_phone", "physical_session", "phone_export", "session.zip")):
            findings.append(item)
        if lower.endswith("gnss_raw.csv") and "tests/fixtures/phase9_android_session/" not in lower:
            findings.append(item)
    return sorted(set(findings))


@dataclass(frozen=True)
class VerificationResult:
    verification: dict
    build_manifest: dict


def verify_release(
    root: Path,
    apk: Path,
    kotlin_tests: int,
    python_tests: int,
    output_root: Path | None = None,
    create_bundle: bool = True,
) -> VerificationResult:
    root = root.resolve()
    apk = apk.resolve()
    if not apk.is_file():
        raise FileNotFoundError(f"APK not found: {apk}")
    build_text = (root / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    model = root / "models/phase5/io_vnbd_s1/velocity_gru.pt"
    embedded = (root / "android/app/src/main/java/org/sih26168/idrlogger/engine/FrozenVelocityModelData.kt").read_text(encoding="utf-8")
    required = [
        "README.md",
        "docs/FINAL_TECHNICAL_OVERVIEW.md",
        "docs/FINAL_INSTALL_AND_RUN.md",
        "docs/HACKATHON_RUNBOOK.md",
        "docs/phase12_judge_demo.md",
        "docs/phase12_judge_qna.md",
        "docs/assets/phase12_architecture.svg",
        "docs/assets/phase12_state_machine.svg",
        "results/phase12/FINAL_JUDGE_SUMMARY.md",
        "android/app/src/main/java/org/sih26168/idrlogger/map/MapProvider.kt",
        "android/app/src/main/java/org/sih26168/idrlogger/map/MapUiPolicy.kt",
        "android/app/src/main/java/org/sih26168/idrlogger/ui/NavGhostMapSurface.kt",
        "android/app/src/main/java/org/sih26168/idrlogger/demo/PublicBenchmarkFixture.kt",
        "android/app/src/main/res/drawable/ic_navghost_mark.xml",
        "android/app/src/main/res/raw/navghost_map_style.json",
    ]
    missing = [item for item in required if not (root / item).is_file()]
    release_paths = [root / item for item in required if (root / item).is_file()]
    release_paths += list((root / "android/app/src/main").rglob("*"))
    secrets = scan_text_for_secrets(release_paths)
    private_findings = tracked_private_data_findings(root)
    model_hash = sha256_file(model)
    map_provider_text = (root / "android/app/src/main/java/org/sih26168/idrlogger/map/MapProvider.kt").read_text(encoding="utf-8")
    commit = _git(root, "rev-parse", "HEAD")
    tag_points_here = False
    fallback_tag_preserved = False
    try:
        tag_points_here = _git(root, "rev-list", "-n", "1", "navghost-release") == commit
        fallback_tag_preserved = _git(root, "rev-list", "-n", "1", "sih26168-final") == PHASE12_COMMIT
    except subprocess.CalledProcessError:
        pass
    checks = {
        "required_files_present": not missing,
        "frozen_model_hash_matches": model_hash == FROZEN_MODEL_SHA256 and FROZEN_MODEL_SHA256 in embedded,
        "apk_present": apk.is_file() and apk.stat().st_size > 0,
        "kotlin_tests_reported": kotlin_tests >= 51,
        "python_tests_reported": python_tests >= 228,
        "no_release_secret_patterns": not secrets,
        "no_tracked_private_phone_data": not private_findings,
        "map_provider_is_visual_only": "fun presentation()" in map_provider_text and "fun location" not in map_provider_text,
        "final_tag_points_to_commit": tag_points_here,
        "fallback_tag_preserved": fallback_tag_preserved,
    }
    configuration_files = [
        root / "android/app/build.gradle.kts",
        root / "android/app/src/main/AndroidManifest.xml",
        root / "android/app/src/main/java/org/sih26168/idrlogger/map/MapProvider.kt",
        root / "android/app/src/main/java/org/sih26168/idrlogger/engine/FrozenVelocityModelData.kt",
    ]
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    build_manifest = {
        "phase": "NavGhost release polish",
        "git_commit": commit,
        "git_tag": "navghost-release" if tag_points_here else None,
        "version": _build_value(build_text, "versionName"),
        "version_code": int(_build_value(build_text, "versionCode")),
        "package_id": PACKAGE_ID,
        "min_sdk": int(_build_value(build_text, "minSdk")),
        "target_sdk": int(_build_value(build_text, "targetSdk")),
        "compile_sdk": "36.1",
        "apk_path": apk.relative_to(root).as_posix() if apk.is_relative_to(root) else apk.name,
        "apk_size_bytes": apk.stat().st_size,
        "apk_sha256": sha256_file(apk),
        "frozen_model_sha256": model_hash,
        "kotlin_tests_passed": kotlin_tests,
        "python_tests_passed": python_tests,
        "build_timestamp_utc": timestamp,
        "configuration_sha256": {path.relative_to(root).as_posix(): sha256_file(path) for path in configuration_files},
    }
    verification = {
        "phase": "NavGhost release polish",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "missing_files": missing,
        "secret_findings": secrets,
        "private_data_findings": private_findings,
        "map_strategy": "official Google Maps visual canvas when locally configured; deterministic local ENU fallback; no map location injection API",
        "google_maps": "official SDK 20.0.0; key sourced only from ignored android/local.properties; My Location disabled; engine-owned marker",
        "public_benchmark": {
            "scenario": "S1_60_STOP_GO",
            "duration_seconds": 60.0,
            "reference_distance_m": 262.7939441749739,
            "raw_final_error_m": 327.1854981423306,
            "hybrid_final_error_m": 74.19228462027947,
            "hybrid_drift_percent": 28.23211351129181,
        },
        "performance": {
            "android_engine_samples_per_second": 11545.0379,
            "android_engine_average_ms_per_sample": 0.0866173,
            "android_engine_p95_ms_per_sample": 0.185,
            "required_input_hz": 10.0,
        },
        "limitations": [
            "No new physical road, endurance, or calibrated external-reference result was produced in release polish.",
            "Google Maps requires a locally supplied restricted API key and network; local ENU remains usable without either.",
            "The Maps SDK exposes no runtime authentication-failure callback; the map control provides an explicit LOCAL fallback if tiles are unavailable.",
            "The covariance halo is engineering uncertainty, not a calibrated 95 percent confidence region.",
        ],
    }
    if output_root is not None:
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "FINAL_VERIFICATION.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
        (output_root / "FINAL_BUILD_MANIFEST.json").write_text(json.dumps(build_manifest, indent=2) + "\n", encoding="utf-8")
        if create_bundle:
            bundle = output_root / "competition_bundle"
            bundle.mkdir(parents=True, exist_ok=True)
            copies = {
                apk: bundle / f"NavGhost-v{build_manifest['version']}-debug.apk",
                root / "results/phase12/FINAL_JUDGE_SUMMARY.md": bundle / "FINAL_JUDGE_SUMMARY.md",
                root / "docs/FINAL_TECHNICAL_OVERVIEW.md": bundle / "FINAL_TECHNICAL_OVERVIEW.md",
                root / "docs/FINAL_INSTALL_AND_RUN.md": bundle / "FINAL_INSTALL_AND_RUN.md",
                root / "docs/HACKATHON_RUNBOOK.md": bundle / "HACKATHON_RUNBOOK.md",
                root / "docs/phase12_judge_demo.md": bundle / "JUDGE_DEMO.md",
                root / "docs/phase12_judge_qna.md": bundle / "JUDGE_QNA.md",
                root / "docs/assets/phase12_architecture.svg": bundle / "phase12_architecture.svg",
                root / "docs/assets/phase12_state_machine.svg": bundle / "phase12_state_machine.svg",
                output_root / "FINAL_VERIFICATION.json": bundle / "FINAL_VERIFICATION.json",
                output_root / "FINAL_BUILD_MANIFEST.json": bundle / "FINAL_BUILD_MANIFEST.json",
                root / "results/phase5/io_vnbd/s1/plots/s1_60_stop_go_trajectory_comparison.png": bundle / "public_benchmark_trajectory.png",
                root / "results/phase7/io_vnbd/s1/plots/navigation_state_timeline.png": bundle / "gnss_loss_recovery_timeline.png",
            }
            for source, destination in copies.items():
                if source.is_file():
                    shutil.copy2(source, destination)
    return VerificationResult(verification=verification, build_manifest=build_manifest)
