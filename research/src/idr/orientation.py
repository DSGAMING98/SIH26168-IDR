"""Android device-orientation transforms used by the raw DR baseline.

The navigation frame is local ENU: +X East, +Y North, +Z Up. Android's
orientation convention reports azimuth about -device-Z (clockwise from North
when level), pitch about device-X, and roll about device-Y, in degrees in the
IO-VNBD export. The corresponding device-to-ENU rotation is
Rz(-azimuth) @ Rx(-pitch) @ Ry(roll).
"""

from __future__ import annotations

from typing import Any

import numpy as np


def android_device_to_enu_matrix(
    azimuth_deg: Any,
    pitch_deg: Any,
    roll_deg: Any,
) -> np.ndarray:
    """Return device-to-local-ENU rotation matrices for Android Euler angles."""

    azimuth, pitch, roll = np.broadcast_arrays(
        np.asarray(azimuth_deg, dtype=float),
        np.asarray(pitch_deg, dtype=float),
        np.asarray(roll_deg, dtype=float),
    )
    if not (
        np.all(np.isfinite(azimuth))
        and np.all(np.isfinite(pitch))
        and np.all(np.isfinite(roll))
    ):
        raise ValueError("Orientation angles must be finite.")

    azimuth = np.radians(azimuth)
    pitch = np.radians(pitch)
    roll = np.radians(roll)
    ca, sa = np.cos(azimuth), np.sin(azimuth)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)

    matrix = np.empty(azimuth.shape + (3, 3), dtype=float)
    matrix[..., 0, 0] = ca * cr - sa * sp * sr
    matrix[..., 0, 1] = sa * cp
    matrix[..., 0, 2] = ca * sr + sa * sp * cr
    matrix[..., 1, 0] = -sa * cr - ca * sp * sr
    matrix[..., 1, 1] = ca * cp
    matrix[..., 1, 2] = -sa * sr + ca * sp * cr
    matrix[..., 2, 0] = -cp * sr
    matrix[..., 2, 1] = -sp
    matrix[..., 2, 2] = cp * cr
    return matrix


def rotate_device_to_enu(
    vectors_device: Any,
    azimuth_deg: Any,
    pitch_deg: Any,
    roll_deg: Any,
) -> np.ndarray:
    """Rotate one or more three-axis device vectors into local ENU."""

    vectors = np.asarray(vectors_device, dtype=float)
    if vectors.shape == (3,):
        vectors = vectors.reshape(1, 3)
        scalar = True
    else:
        scalar = False
    if vectors.ndim != 2 or vectors.shape[1] != 3:
        raise ValueError("Device vectors must have shape (3,) or (n, 3).")
    if not np.all(np.isfinite(vectors)):
        raise ValueError("Device vectors must be finite.")
    matrices = android_device_to_enu_matrix(azimuth_deg, pitch_deg, roll_deg)
    if matrices.shape == (3, 3):
        matrices = np.broadcast_to(matrices, (len(vectors), 3, 3))
    if matrices.shape != (len(vectors), 3, 3):
        raise ValueError("There must be one orientation per device vector.")
    rotated = np.einsum("nij,nj->ni", matrices, vectors)
    return rotated[0] if scalar else rotated
