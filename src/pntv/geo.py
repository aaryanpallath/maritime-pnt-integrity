"""Local east-north (ENU) coordinates around a reference point.

An equirectangular projection is accurate to well under 0.1% over the ~50 km extent of a harbor approach,
which is far below the GNSS and dead-reckoning errors studied here.
"""

from __future__ import annotations

import math

import numpy as np

EARTH_RADIUS_M = 6_371_008.8
KNOT_MS = 0.514444


def to_enu(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    east = np.radians(lon - lon0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    north = np.radians(lat - lat0) * EARTH_RADIUS_M
    return east, north


def course_to_velocity(speed_ms: np.ndarray, course_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Course over ground is measured clockwise from north: east = sin, north = cos."""
    c = np.radians(course_deg)
    return speed_ms * np.sin(c), speed_ms * np.cos(c)
