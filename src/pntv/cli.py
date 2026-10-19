"""pntv: extract AIS tracks and run requirements verification."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from .ais import extract_segments, load_segments, save_segments, truth_trajectory
from .run import run_scenario
from .sensors import Event
from .verify import evaluate, load_requirements, monte_carlo, pick_tracks, plot_example, write_matrix

TRACKS = Path("data/tracks/san_diego_2023-06-15.json")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="pntv", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="extract San Diego vessel segments from a NOAA AIS daily zip")
    ex.add_argument("zip", type=Path)
    ex.add_argument("--out", type=Path, default=TRACKS)
    v = sub.add_parser("verify", help="run the Monte Carlo and write the verification matrix")
    v.add_argument("--requirements", type=Path, default=Path("requirements.yaml"))
    v.add_argument("--tracks", type=Path, default=TRACKS)
    v.add_argument("--n-tracks", type=int, default=20)
    v.add_argument("--seeds", type=int, default=6)
    v.add_argument("--out", type=Path, default=Path("results"))
    a = p.parse_args(argv)

    if a.cmd == "extract":
        segs = extract_segments(a.zip)
        save_segments(segs, a.out)
        print(f"{len(segs)} segments -> {a.out}")
        return
    spec = load_requirements(a.requirements)
    tracks = pick_tracks(load_segments(a.tracks), a.n_tracks, 1800.0)
    t0 = time.time()
    result = monte_carlo(tracks, a.seeds, spec["scenario_defaults"])
    rows = evaluate(spec, result["metrics"])
    write_matrix(rows, result, spec, a.out)
    truth = truth_trajectory(tracks[0])
    keep = truth["t"] < 1800
    truth = {k: x[keep] for k, x in truth.items()}
    ev = Event(kind="spoofing", spoof_rate_ms=1.0, spoof_dir_rad=0.8)
    plot_example(truth, run_scenario(truth, ev, seed=42), ev, a.out / "spoofing_example.png")
    for r in rows:
        print(f"{r['id']}  {r['result']:4}  {r['metric']} = {r['measured']:g} (req {r['threshold']})")
    print(f"{result['runs']['total_runs']} runs in {time.time() - t0:.0f} s -> {a.out}/verification_matrix.md")


if __name__ == "__main__":
    main()
