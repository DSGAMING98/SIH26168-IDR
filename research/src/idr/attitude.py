"""Runtime-safe attitude and circular-angle helpers for classical DR.

IO-VNBD S1 does not behave like an unmodified Android device frame: the
paper's mounting diagram makes phone +X the intended direction of travel,
while measured gravity is almost +Z.  Phase 4 therefore derives tilt and a
horizontal vehicle basis directly from gravity and treats exported azimuth as
an app-provided yaw cue that needs a pre-blackout course offset.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .orientation import android_device_to_enu_matrix


STANDARD_GRAVITY_MPS2 = 9.80665


def wrap_degrees(angle_deg: Any) -> np.ndarray:
    """Wrap angles to the half-open interval [0, 360)."""

    angle = np.asarray(angle_deg, dtype=float)
    if not np.all(np.isfinite(angle)):
        raise ValueError("Angles must be finite.")
    return np.mod(angle, 360.0)


def signed_angle_difference_deg(target_deg: Any, source_deg: Any) -> np.ndarray:
    """Return the shortest signed rotation from source to target."""

    target, source = np.broadcast_arrays(
        np.asarray(target_deg, dtype=float), np.asarray(source_deg, dtype=float)
    )
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(source)):
        raise ValueError("Angles must be finite.")
    return (target - source + 180.0) % 360.0 - 180.0


def circular_mean_deg(angles_deg: Any) -> tuple[float, float, float]:
    """Return circular mean, circular standard deviation, and resultant length."""

    angles = np.asarray(angles_deg, dtype=float)
    if angles.ndim != 1 or angles.size == 0 or not np.all(np.isfinite(angles)):
        raise ValueError("Circular mean requires a finite one-dimensional sample.")
    radians = np.radians(angles)
    sine = float(np.mean(np.sin(radians)))
    cosine = float(np.mean(np.cos(radians)))
    resultant = float(np.hypot(sine, cosine))
    mean = float(wrap_degrees(np.degrees(np.arctan2(sine, cosine))))
    dispersion = float(
        np.degrees(np.sqrt(max(0.0, -2.0 * np.log(max(resultant, 1e-15)))))
    )
    return mean, dispersion, resultant


def circular_median_deg(angles_deg: Any) -> float:
    """Return the observed angle minimizing summed absolute circular distance."""

    angles = np.asarray(angles_deg, dtype=float)
    if angles.ndim != 1 or angles.size == 0 or not np.all(np.isfinite(angles)):
        raise ValueError("Circular median requires a finite one-dimensional sample.")
    cost = np.sum(
        np.abs(signed_angle_difference_deg(angles[:, None], angles[None, :])), axis=1
    )
    return float(wrap_degrees(angles[int(np.argmin(cost))]))


def gravity_roll_pitch_deg(gravity_device_mps2: Any) -> tuple[np.ndarray, np.ndarray]:
    """Infer gravity-relative roll and pitch without using exported Euler tilt.

    The returned convention is zero when gravity is device +Z, roll increases
    toward +Y, and pitch increases for gravity toward -X.
    """

    gravity = np.asarray(gravity_device_mps2, dtype=float)
    scalar = gravity.shape == (3,)
    if scalar:
        gravity = gravity.reshape(1, 3)
    if gravity.ndim != 2 or gravity.shape[1] != 3:
        raise ValueError("Gravity vectors must have shape (3,) or (n, 3).")
    norm = np.linalg.norm(gravity, axis=1)
    if not np.all(np.isfinite(gravity)) or np.any(norm < 1e-6):
        raise ValueError("Gravity vectors must be finite and non-zero.")
    roll = np.degrees(np.arctan2(gravity[:, 1], gravity[:, 2]))
    pitch = np.degrees(
        np.arctan2(-gravity[:, 0], np.hypot(gravity[:, 1], gravity[:, 2]))
    )
    if scalar:
        return roll[0], pitch[0]
    return roll, pitch


def gravity_vehicle_basis(gravity_device_mps2: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build orthonormal forward, left, and up axes in device coordinates.

    The documented mounted-phone +X axis is projected into the gravity-defined
    horizontal plane.  ``left = up x forward`` preserves a right-handed
    forward/left/up vehicle convention.
    """

    gravity = np.asarray(gravity_device_mps2, dtype=float)
    scalar = gravity.shape == (3,)
    if scalar:
        gravity = gravity.reshape(1, 3)
    if gravity.ndim != 2 or gravity.shape[1] != 3:
        raise ValueError("Gravity vectors must have shape (3,) or (n, 3).")
    gravity_norm = np.linalg.norm(gravity, axis=1)
    if not np.all(np.isfinite(gravity)) or np.any(gravity_norm < 1e-6):
        raise ValueError("Gravity vectors must be finite and non-zero.")
    up = gravity / gravity_norm[:, None]
    device_x = np.broadcast_to(np.array([1.0, 0.0, 0.0]), gravity.shape)
    forward = device_x - np.sum(device_x * up, axis=1)[:, None] * up
    forward_norm = np.linalg.norm(forward, axis=1)
    if np.any(forward_norm < 0.1):
        raise ValueError("Device +X is too close to vertical for vehicle alignment.")
    forward = forward / forward_norm[:, None]
    left = np.cross(up, forward)
    left = left / np.linalg.norm(left, axis=1)[:, None]
    if scalar:
        return forward[0], left[0], up[0]
    return forward, left, up


def gravity_euler_diagnostics(
    gravity_device_mps2: Any,
    azimuth_deg: Any,
    pitch_deg: Any,
    roll_deg: Any,
) -> dict[str, np.ndarray]:
    """Compare measured-gravity attitude with the frozen Phase 3 Euler model."""

    gravity = np.asarray(gravity_device_mps2, dtype=float)
    if gravity.ndim != 2 or gravity.shape[1] != 3:
        raise ValueError("Gravity diagnostics require shape (n, 3).")
    magnitude = np.linalg.norm(gravity, axis=1)
    if np.any(magnitude < 1e-6) or not np.all(np.isfinite(gravity)):
        raise ValueError("Gravity vectors must be finite and non-zero.")
    measured_up = gravity / magnitude[:, None]
    device_z = np.array([0.0, 0.0, 1.0])
    gravity_tilt = np.degrees(
        np.arccos(np.clip(measured_up @ device_z, -1.0, 1.0))
    )
    matrices = android_device_to_enu_matrix(azimuth_deg, pitch_deg, roll_deg)
    if matrices.shape == (3, 3):
        matrices = matrices.reshape(1, 3, 3)
    nav_up = np.array([0.0, 0.0, 1.0])
    euler_expected_up_device = np.einsum("nji,j->ni", matrices, nav_up)
    euler_tilt = np.degrees(
        np.arccos(np.clip(euler_expected_up_device @ device_z, -1.0, 1.0))
    )
    disagreement = np.degrees(
        np.arccos(
            np.clip(np.sum(measured_up * euler_expected_up_device, axis=1), -1.0, 1.0)
        )
    )
    return {
        "gravity_magnitude_mps2": magnitude,
        "gravity_tilt_deg": gravity_tilt,
        "euler_implied_tilt_deg": euler_tilt,
        "gravity_euler_disagreement_deg": disagreement,
    }
