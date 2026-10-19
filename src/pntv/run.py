"""Run one scenario over one truth trajectory and record errors, alarms and timing."""

from __future__ import annotations

import time

import numpy as np

from .ekf import NavFilter
from .sensors import Event, Measurements, SensorConfig, simulate


def run_scenario(truth: dict[str, np.ndarray], event: Event, seed: int, cfg: SensorConfig | None = None,
                 filter_kwargs: dict | None = None) -> dict:
    cfg = cfg or SensorConfig()
    rng = np.random.default_rng(seed)
    m: Measurements = simulate(truth, event, rng, cfg)
    first = np.flatnonzero(~np.isnan(m.gnss[:, 0]))[0]
    f = NavFilter(m.gnss[first, 0], m.gnss[first, 1], **(filter_kwargs or {}))
    sub = cfg.dr_rate_hz
    dt = 1.0 / cfg.dr_rate_hz
    n = m.t_gnss.size
    est = np.zeros((n, 2))
    alarm = np.zeros(n, dtype=bool)
    raised_at: list[float] = []
    step_ms = []
    for i in range(n):
        t0 = time.perf_counter()
        if i > 0:
            for j in range((i - 1) * sub, min(i * sub, m.t_dr.size)):
                f.predict(dt, m.speed[j], m.heading[j])
        if not np.isnan(m.gnss[i, 0]):
            r = f.update(m.gnss[i], m.gnss_sigma[i])
            if r["alarm_raised"]:
                raised_at.append(float(m.t_gnss[i]))
        step_ms.append((time.perf_counter() - t0) * 1000)
        est[i] = f.x[:2]
        alarm[i] = f.alarm
    err = np.hypot(est[:, 0] - truth["east"], est[:, 1] - truth["north"])
    return {"t": m.t_gnss, "err": err, "est": est, "gnss": m.gnss, "alarm": alarm, "alarms_raised_at": raised_at,
            "step_ms": np.asarray(step_ms)}
