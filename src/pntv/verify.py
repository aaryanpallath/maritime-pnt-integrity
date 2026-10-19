"""Requirements verification: Monte Carlo over real tracks, metrics, and a requirements verification matrix."""

from __future__ import annotations

import csv
import json
import platform
from datetime import date
from pathlib import Path

import numpy as np
import yaml

from .ais import Segment, truth_trajectory
from .run import run_scenario
from .sensors import SCENARIOS, Event

OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, ">": lambda a, b: a > b}
SPOOF_RATES = (0.5, 1.0, 2.0)
CONVERGENCE_S = 60.0


def load_requirements(path: str | Path) -> dict:
    spec = yaml.safe_load(Path(path).read_text())
    ids = [r["id"] for r in spec["requirements"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate requirement ids")
    for r in spec["requirements"]:
        if r["threshold"]["op"] not in OPS:
            raise ValueError(f"{r['id']}: unknown operator {r['threshold']['op']}")
    return spec


def pick_tracks(segments: list[Segment], n: int, duration_s: float) -> list[Segment]:
    """Longest segment per vessel, so no vessel is counted twice."""
    best: dict[str, Segment] = {}
    for s in segments:
        if s.duration_s >= duration_s and (s.mmsi not in best or s.duration_s > best[s.mmsi].duration_s):
            best[s.mmsi] = s
    return sorted(best.values(), key=lambda s: s.mmsi)[:n]


def monte_carlo(tracks: list[Segment], seeds: int, defaults: dict, duration_s: float = 1800.0) -> dict:
    start, length = defaults["event_start_s"], defaults["event_duration_s"]
    pools: dict[str, list] = {"nominal": [], "outage": [], "jamming": [], "spoofing": []}
    detect, tta, false_alarms, nominal_hours, step_ms = [], [], 0, 0.0, []
    for ti, seg in enumerate(tracks):
        truth = truth_trajectory(seg)
        keep = truth["t"] < duration_s
        truth = {k: v[keep] for k, v in truth.items()}
        for s in range(seeds):
            seed = 1000 * ti + s
            rng = np.random.default_rng(seed + 7)
            for kind in SCENARIOS:
                ev = Event(kind=kind, start_s=start, duration_s=length,
                           spoof_rate_ms=SPOOF_RATES[s % len(SPOOF_RATES)], spoof_dir_rad=rng.uniform(0, 2 * np.pi))
                r = run_scenario(truth, ev, seed)
                t, err = r["t"], r["err"]
                on = (t >= start) & (t < start + length)
                step_ms.append(r["step_ms"])
                if kind == "nominal":
                    pools["nominal"].append(err[t >= CONVERGENCE_S])
                    false_alarms += len(r["alarms_raised_at"])
                    nominal_hours += (t[-1] - t[0]) / 3600
                else:
                    pools[kind].append(err[on])
                if kind == "spoofing":
                    hits = [a for a in r["alarms_raised_at"] if start <= a < start + length]
                    detect.append(bool(hits))
                    if hits:
                        tta.append(hits[0] - start)
    p95 = {k: float(np.percentile(np.concatenate(v), 95)) for k, v in pools.items()}
    steps = np.concatenate(step_ms)
    return {
        "metrics": {
            "nominal_p95_error_m": p95["nominal"],
            "outage_p95_error_m": p95["outage"],
            "jamming_p95_error_m": p95["jamming"],
            "spoof_detection_rate": float(np.mean(detect)),
            "spoof_p95_time_to_alert_s": float(np.percentile(tta, 95)) if tta else float("inf"),
            "spoof_p95_error_m": p95["spoofing"],
            "false_alarms_per_10h": false_alarms / nominal_hours * 10,
            "update_time_p99_ms": float(np.percentile(steps, 99)),
        },
        "runs": {"tracks": len(tracks), "seeds_per_track": seeds, "scenarios": list(SCENARIOS),
                 "total_runs": len(tracks) * seeds * len(SCENARIOS), "spoof_runs": len(detect),
                 "spoofs_detected": int(np.sum(detect)), "nominal_hours": round(nominal_hours, 2),
                 "false_alarms": false_alarms, "spoof_rates_ms": list(SPOOF_RATES), "track_duration_s": duration_s,
                 "machine": f"{platform.machine()} / {platform.processor() or platform.system()} / "
                            f"Python {platform.python_version()}"},
    }


def evaluate(spec: dict, metrics: dict) -> list[dict]:
    rows = []
    for r in spec["requirements"]:
        value = metrics[r["metric"]]
        op, limit = r["threshold"]["op"], r["threshold"]["value"]
        rows.append({"id": r["id"], "title": r["title"], "text": r["text"], "method": r["method"],
                     "metric": r["metric"], "threshold": f"{op} {limit}", "measured": round(value, 4),
                     "result": "PASS" if OPS[op](value, limit) else "FAIL"})
    return rows


def write_matrix(rows: list[dict], result: dict, spec: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps({**result, "requirements": rows}, indent=2) + "\n")
    with open(out / "verification_matrix.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    runs = result["runs"]
    passed = sum(r["result"] == "PASS" for r in rows)
    lines = [f"# Requirements Verification Matrix — {spec['system']} v{spec['version']}", "",
             f"Generated {date.today().isoformat()} by `pntv verify`. {passed} of {len(rows)} requirements pass.", "",
             f"Evidence: {runs['total_runs']} Monte Carlo runs ({runs['tracks']} real vessel tracks off San Diego x "
             f"{runs['seeds_per_track']} seeds x {len(runs['scenarios'])} scenarios), "
             f"{runs['nominal_hours']} h of nominal operation, {runs['spoof_runs']} spoofing attacks at "
             f"{', '.join(str(x) for x in runs['spoof_rates_ms'])} m/s.", "",
             "| ID | Requirement | Method | Threshold | Measured | Result |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | **{r['title']}.** {r['text']} | {r['method']} | {r['threshold']} | "
                     f"{r['measured']:g} | {r['result']} |")
    (out / "verification_matrix.md").write_text("\n".join(lines) + "\n")


def plot_example(truth: dict, r: dict, event: Event, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.8))
    a.plot(truth["east"], truth["north"], "k-", lw=2, label="truth (AIS)")
    a.plot(r["gnss"][:, 0], r["gnss"][:, 1], ".", ms=2, color="tab:red", alpha=0.5, label="GNSS fixes (spoofed)")
    a.plot(r["est"][:, 0], r["est"][:, 1], "-", color="tab:blue", lw=1.2, label="filter estimate")
    a.set(xlabel="east (m)", ylabel="north (m)", title="Track with GNSS drag-off spoof")
    a.axis("equal")
    a.legend(loc="best", fontsize=8)
    t = r["t"]
    b.plot(t, r["err"], color="tab:blue", label="filter error")
    spoof_err = np.hypot(r["gnss"][:, 0] - truth["east"], r["gnss"][:, 1] - truth["north"])
    b.plot(t, spoof_err, color="tab:red", alpha=0.4, label="raw GNSS error")
    b.axvspan(event.start_s, event.start_s + event.duration_s, color="tab:red", alpha=0.08, label="spoof active")
    b.fill_between(t, 0, 1, where=r["alarm"], transform=b.get_xaxis_transform(), color="tab:orange", alpha=0.25,
                   label="integrity alarm")
    b.set(xlabel="time (s)", ylabel="horizontal error (m)", yscale="log", title="Error and integrity alarm")
    b.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
