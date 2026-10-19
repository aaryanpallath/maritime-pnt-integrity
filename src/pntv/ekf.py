"""Navigation filter and GNSS integrity monitor.

State: [east, north, current_east, current_north]. Prediction integrates dead reckoning (speed log and
gyrocompass) plus the estimated current; GNSS fixes update position, and through the correlations the filter
learns the current, so it can hold position through a GNSS outage.

Integrity: each fix's normalized innovation squared (NIS) is chi-square with 2 degrees of freedom when GNSS
is healthy. A single implausible fix is rejected. A slow spoof passes each single-fix test, so a sliding-window
sum of NIS is also tested. When it fails, GNSS is declared untrusted and the filter rolls back to its state
from before the window began, replays dead reckoning from there (so spoofed fixes absorbed before detection,
which would otherwise corrupt the current estimate, are discarded), and coasts until a full window of fixes
is consistent again.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np


def chi2_quantile(p: float, dof: int) -> float:
    """Exact for 2 degrees of freedom (an exponential distribution); Wilson-Hilferty approximation otherwise,
    which is within about 1% for the 60-dof window test used here."""
    if dof == 2:
        return -2.0 * math.log(1.0 - p)
    z = math.sqrt(2) * _erfinv(2 * p - 1)
    a = 2.0 / (9.0 * dof)
    return dof * (1 - a + z * math.sqrt(a)) ** 3


def _erfinv(y: float) -> float:
    a = 0.147
    ln = math.log(1 - y * y)
    t = 2 / (math.pi * a) + ln / 2
    x = math.copysign(math.sqrt(math.sqrt(t * t - ln / a) - t), y)
    for _ in range(2):  # Newton polish
        x -= (math.erf(x) - y) / (2 / math.sqrt(math.pi) * math.exp(-x * x))
    return x


class NavFilter:
    def __init__(self, east: float, north: float, pos_sigma: float = 5.0, current_sigma: float = 0.5,
                 speed_sigma: float = 0.08, heading_sigma_rad: float = math.radians(0.6),
                 current_walk: float = 0.002, window: int = 30, p_fix: float = 0.999, p_window: float = 0.99999):
        self.x = np.array([east, north, 0.0, 0.0])
        self.P = np.diag([pos_sigma**2] * 2 + [current_sigma**2] * 2)
        self.speed_sigma, self.heading_sigma, self.current_walk = speed_sigma, heading_sigma_rad, current_walk
        self.fix_gate = chi2_quantile(p_fix, 2)
        self.window = window
        self.window_gate = chi2_quantile(p_window, 2 * window)
        self.nis: deque[float] = deque(maxlen=window)
        self.alarm = False
        # one entry per GNSS epoch in the window: the prior (x, P) before that fix, and the dead-reckoning
        # inputs applied after it, so the window can be replayed without its fixes
        self.epochs: deque[dict] = deque(maxlen=window)
        self.rollbacks = 0

    def predict(self, dt: float, speed: float, heading: float) -> None:
        if self.epochs:
            self.epochs[-1]["dr"].append((dt, speed, heading))
        self._predict(dt, speed, heading)

    def _predict(self, dt: float, speed: float, heading: float) -> None:
        s, c = math.sin(heading), math.cos(heading)
        self.x[0] += (speed * s + self.x[2]) * dt
        self.x[1] += (speed * c + self.x[3]) * dt
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        # velocity uncertainty from the speed log (along track) and heading (cross track)
        J = np.array([[s, speed * c], [c, -speed * s]])
        Qv = J @ np.diag([self.speed_sigma**2, self.heading_sigma**2]) @ J.T
        Q = np.zeros((4, 4))
        Q[:2, :2] = Qv * dt * dt
        Q[2:, 2:] = np.eye(2) * self.current_walk**2 * dt
        self.P = F @ self.P @ F.T + Q

    def update(self, z: np.ndarray, sigma: float) -> dict:
        """Test a GNSS fix and use it only if GNSS is currently trusted. Returns what happened."""
        self.epochs.append({"x": self.x.copy(), "P": self.P.copy(), "dr": []})
        nu = z - self.x[:2]
        S = self.P[:2, :2] + np.eye(2) * sigma**2
        Sinv = np.linalg.inv(S)
        nis = float(nu @ Sinv @ nu)
        self.nis.append(min(nis, 4 * self.fix_gate))  # cap one outlier's weight in the window
        window_fail = len(self.nis) == self.window and sum(self.nis) > self.window_gate
        raised = window_fail and not self.alarm
        if raised:
            self._rollback()
            nu = z - self.x[:2]
            S = self.P[:2, :2] + np.eye(2) * sigma**2
            Sinv = np.linalg.inv(S)
        if window_fail:
            self.alarm = True
        elif self.alarm and len(self.nis) == self.window and max(self.nis) < self.fix_gate:
            self.alarm = False  # a full window of consistent fixes: trust GNSS again
        used = not self.alarm and nis < self.fix_gate
        if used:
            K = self.P[:, :2] @ Sinv
            self.x = self.x + K @ nu
            self.P = (np.eye(4) - K[:, :2] @ np.eye(2, 4)) @ self.P
        return {"nis": nis, "used": used, "alarm": self.alarm, "alarm_raised": raised}

    def _rollback(self) -> None:
        """Restore the prior from the start of the window and replay dead reckoning without its fixes."""
        first = self.epochs[0]
        self.x, self.P = first["x"].copy(), first["P"].copy()
        for e in self.epochs:
            for dt, speed, heading in e["dr"]:
                self._predict(dt, speed, heading)
        self.rollbacks += 1
