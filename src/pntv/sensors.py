"""Sensor models driven by a truth trajectory: GNSS fixes and dead-reckoning inputs, plus GNSS threats.

Dead reckoning uses what a ship actually carries: a speed log (speed through the water) and a gyrocompass
(heading). Both measure motion relative to the water, so an unknown current makes pure dead reckoning drift,
which is why the filter estimates the current.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SCENARIOS = ("nominal", "outage", "jamming", "spoofing")


@dataclass
class SensorConfig:
    gnss_sigma_m: float = 2.5          # per-axis white noise
    gnss_bias_sigma_m: float = 1.0     # slowly varying error (multipath, atmosphere): first-order Gauss-Markov
    gnss_bias_tau_s: float = 300.0
    jam_sigma_m: float = 25.0          # degraded noise while jammed; the receiver reports it
    speed_noise_ms: float = 0.05
    speed_scale_sigma: float = 0.01    # per-run speed log scale factor error
    heading_noise_deg: float = 0.2
    heading_bias_sigma_deg: float = 0.5
    current_max_ms: float = 0.5        # per-run water current, uniform magnitude, random direction
    dr_rate_hz: int = 10


@dataclass
class Event:
    kind: str = "nominal"              # nominal | outage | jamming | spoofing
    start_s: float = 600.0
    duration_s: float = 300.0
    spoof_rate_ms: float = 0.5         # drag-off speed of the spoofed position
    spoof_dir_rad: float = 0.0

    def active(self, t: float) -> bool:
        return self.kind != "nominal" and self.start_s <= t < self.start_s + self.duration_s


@dataclass
class Measurements:
    t_dr: np.ndarray                   # dead-reckoning sample times (s)
    speed: np.ndarray                  # speed log, m/s through water
    heading: np.ndarray                # gyrocompass heading, rad
    t_gnss: np.ndarray                 # 1 Hz
    gnss: np.ndarray                   # (n, 2) east/north fix, NaN when no fix (outage)
    gnss_sigma: np.ndarray             # receiver-reported 1-sigma per axis


def simulate(truth: dict[str, np.ndarray], event: Event, rng: np.random.Generator,
             cfg: SensorConfig | None = None) -> Measurements:
    cfg = cfg or SensorConfig()
    t = truth["t"]
    cur = rng.uniform(0, cfg.current_max_ms) * np.array([np.sin(a := rng.uniform(0, 2 * np.pi)), np.cos(a)])

    # dead reckoning at dr_rate_hz: velocity through the water = velocity over ground - current
    t_dr = np.arange(t[0], t[-1], 1.0 / cfg.dr_rate_hz)
    vw_e = np.interp(t_dr, t, truth["v_east"]) - cur[0]
    vw_n = np.interp(t_dr, t, truth["v_north"]) - cur[1]
    scale = 1 + rng.normal(0, cfg.speed_scale_sigma)
    speed = np.hypot(vw_e, vw_n) * scale + rng.normal(0, cfg.speed_noise_ms, t_dr.size)
    hb = np.radians(rng.normal(0, cfg.heading_bias_sigma_deg))
    heading = np.arctan2(vw_e, vw_n) + hb + np.radians(rng.normal(0, cfg.heading_noise_deg, t_dr.size))

    # GNSS at 1 Hz: truth + Gauss-Markov bias + white noise, then the event
    n = t.size
    phi = np.exp(-1.0 / cfg.gnss_bias_tau_s)
    bias = np.zeros((n, 2))
    bias[0] = rng.normal(0, cfg.gnss_bias_sigma_m, 2)
    drive = rng.normal(0, cfg.gnss_bias_sigma_m * np.sqrt(1 - phi**2), (n, 2))
    for i in range(1, n):
        bias[i] = phi * bias[i - 1] + drive[i]
    sigma = np.full(n, cfg.gnss_sigma_m)
    gnss = np.column_stack([truth["east"], truth["north"]]) + bias + rng.normal(0, 1, (n, 2)) * cfg.gnss_sigma_m
    on = np.array([event.active(x) for x in t])
    if event.kind == "outage":
        gnss[on] = np.nan
    elif event.kind == "jamming":
        gnss[on] += rng.normal(0, cfg.jam_sigma_m, (on.sum(), 2))
        sigma[on] = np.hypot(cfg.gnss_sigma_m, cfg.jam_sigma_m)
    elif event.kind == "spoofing":  # reported accuracy stays nominal: the receiver is fooled
        d = event.spoof_rate_ms * (t[on] - event.start_s)
        gnss[on] += np.column_stack([d * np.sin(event.spoof_dir_rad), d * np.cos(event.spoof_dir_rad)])
    return Measurements(t_dr, speed, heading, t, gnss, sigma)
