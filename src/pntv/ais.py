"""Real vessel trajectories from NOAA/BOEM AIS data (MarineCadastre.gov).

`extract_segments` scans one daily AIS file for vessels underway in a bounding box and keeps continuous
segments. `truth_trajectory` turns a segment's ~1-minute fixes into a 1 Hz ground-truth path with cubic
Hermite interpolation, using each fix's speed and course as the tangent, so the path between fixes is
smooth and consistent with the reported motion.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .geo import KNOT_MS, course_to_velocity, to_enu

SAN_DIEGO_BOX = {"lat": (32.4, 33.0), "lon": (-117.6, -117.0)}


@dataclass
class Segment:
    mmsi: str
    vessel_type: str
    t: list[float]        # seconds since segment start
    lat: list[float]
    lon: list[float]
    sog_kn: list[float]
    cog_deg: list[float]

    @property
    def duration_s(self) -> float:
        return self.t[-1] - self.t[0]


def extract_segments(zip_path: str | Path, box: dict = SAN_DIEGO_BOX, min_speed_kn: float = 3.0,
                     max_gap_s: float = 180.0, min_duration_s: float = 1500.0) -> list[Segment]:
    by_vessel: dict[str, list[tuple]] = {}
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        for row in csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8", newline="")):
            try:
                lat, lon = float(row["LAT"]), float(row["LON"])
                sog, cog = float(row["SOG"]), float(row["COG"])
            except ValueError:
                continue
            if not (box["lat"][0] <= lat <= box["lat"][1] and box["lon"][0] <= lon <= box["lon"][1]):
                continue
            if sog < min_speed_kn or not 0 <= cog < 360:
                continue
            ts = datetime.fromisoformat(row["BaseDateTime"]).timestamp()
            by_vessel.setdefault(row["MMSI"], []).append((ts, lat, lon, sog, cog, row["VesselType"]))
    segments = []
    for mmsi, pts in by_vessel.items():
        pts.sort()
        run = [pts[0]]
        for p in pts[1:] + [None]:
            if p is not None and p[0] - run[-1][0] <= max_gap_s and p[0] > run[-1][0]:
                run.append(p)
                continue
            if len(run) >= 3 and run[-1][0] - run[0][0] >= min_duration_s:
                t0 = run[0][0]
                segments.append(Segment(mmsi, run[0][5], [r[0] - t0 for r in run], [r[1] for r in run],
                                        [r[2] for r in run], [r[3] for r in run], [r[4] for r in run]))
            run = [p] if p is not None else []
    return sorted(segments, key=lambda s: -s.duration_s)


def save_segments(segments: list[Segment], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps([s.__dict__ for s in segments]) + "\n")


def load_segments(path: str | Path) -> list[Segment]:
    return [Segment(**d) for d in json.loads(Path(path).read_text())]


def truth_trajectory(seg: Segment, rate_hz: float = 1.0) -> dict[str, np.ndarray]:
    """1 Hz truth: time, east/north position (m) and east/north velocity (m/s) in a local frame."""
    t = np.asarray(seg.t, dtype=float)
    e, n = to_enu(np.asarray(seg.lat), np.asarray(seg.lon), seg.lat[0], seg.lon[0])
    ve, vn = course_to_velocity(np.asarray(seg.sog_kn) * KNOT_MS, np.asarray(seg.cog_deg))
    tt = np.arange(0.0, t[-1], 1.0 / rate_hz)
    k = np.clip(np.searchsorted(t, tt, side="right") - 1, 0, len(t) - 2)
    h = t[k + 1] - t[k]
    s = (tt - t[k]) / h
    h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
    d00, d10, d01, d11 = 6 * s**2 - 6 * s, 3 * s**2 - 4 * s + 1, -6 * s**2 + 6 * s, 3 * s**2 - 2 * s

    def herm(p, v):
        pos = h00 * p[k] + h10 * h * v[k] + h01 * p[k + 1] + h11 * h * v[k + 1]
        vel = (d00 * p[k] + d10 * h * v[k] + d01 * p[k + 1] + d11 * h * v[k + 1]) / h
        return pos, vel

    pe, ve_t = herm(e, ve)
    pn, vn_t = herm(n, vn)
    return {"t": tt, "east": pe, "north": pn, "v_east": ve_t, "v_north": vn_t}
