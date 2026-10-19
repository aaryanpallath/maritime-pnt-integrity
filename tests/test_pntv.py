import math

import numpy as np
import pytest

from pntv.ais import Segment, truth_trajectory
from pntv.ekf import chi2_quantile
from pntv.geo import KNOT_MS, course_to_velocity
from pntv.run import run_scenario
from pntv.sensors import Event
from pntv.verify import evaluate, load_requirements, write_matrix


def straight_segment(minutes=30, speed_kn=10.0, course=45.0) -> Segment:
    """Fixes once a minute along a straight line, like 1-minute AIS."""
    t = [60.0 * i for i in range(minutes + 1)]
    v = speed_kn * KNOT_MS
    lat0, lon0 = 32.7, -117.2
    lat = [lat0 + math.degrees(v * x * math.cos(math.radians(course)) / 6_371_008.8) for x in t]
    lon = [lon0 + math.degrees(v * x * math.sin(math.radians(course)) / (6_371_008.8 * math.cos(math.radians(lat0))))
           for x in t]
    return Segment("1", "70", t, lat, lon, [speed_kn] * len(t), [course] * len(t))


@pytest.fixture(scope="module")
def truth():
    return truth_trajectory(straight_segment())


def test_course_convention():
    e, n = course_to_velocity(np.array([1.0, 1.0]), np.array([0.0, 90.0]))
    assert np.allclose(e, [0, 1], atol=1e-12) and np.allclose(n, [1, 0], atol=1e-12)


def test_truth_passes_through_fixes_with_reported_velocity(truth):
    speed = np.hypot(truth["v_east"], truth["v_north"])
    assert np.allclose(speed, 10 * KNOT_MS, rtol=1e-3)
    assert truth["t"][1] - truth["t"][0] == 1.0


def test_chi2_quantile_matches_tables():
    assert chi2_quantile(0.999, 2) == pytest.approx(13.816, rel=0.01)
    assert chi2_quantile(0.99, 40) == pytest.approx(63.691, rel=0.01)


def test_nominal_accuracy_and_no_alarm(truth):
    r = run_scenario(truth, Event("nominal"), seed=3)
    assert np.percentile(r["err"][60:], 95) < 5
    assert r["alarms_raised_at"] == []


def test_outage_holds_position_on_dead_reckoning(truth):
    r = run_scenario(truth, Event("outage", start_s=600, duration_s=300), seed=4)
    on = (r["t"] >= 600) & (r["t"] < 900)
    assert np.isnan(r["gnss"][on]).all()
    assert r["err"][on].max() < 50 and r["alarms_raised_at"] == []


@pytest.mark.parametrize("rate", [0.5, 2.0])
def test_spoof_is_detected_and_contained(truth, rate):
    ev = Event("spoofing", start_s=600, duration_s=300, spoof_rate_ms=rate, spoof_dir_rad=1.0)
    r = run_scenario(truth, ev, seed=5)
    first = r["alarms_raised_at"][0]
    assert 600 <= first <= 660
    on = (r["t"] >= 600) & (r["t"] < 900)
    raw = np.hypot(r["gnss"][on, 0] - truth["east"][on], r["gnss"][on, 1] - truth["north"][on])
    assert raw.max() > 100 and r["err"][on].max() < 30   # rollback keeps the spoof out of the estimate
    assert not r["alarm"][-1]                             # GNSS trusted again after the spoof stops


def test_requirements_spec_and_matrix(tmp_path):
    spec = load_requirements("requirements.yaml")
    assert len(spec["requirements"]) == 8
    metrics = {r["metric"]: 0.0 for r in spec["requirements"]}
    metrics["spoof_detection_rate"] = 0.5   # below the 0.95 requirement
    rows = evaluate(spec, metrics)
    assert {r["id"]: r["result"] for r in rows}["PNT-004"] == "FAIL"
    assert sum(r["result"] == "PASS" for r in rows) == 7
    write_matrix(rows, {"metrics": metrics, "runs": {"total_runs": 1, "tracks": 1, "seeds_per_track": 1,
                                                     "scenarios": ["nominal"], "nominal_hours": 0.5,
                                                     "spoof_runs": 1, "spoof_rates_ms": [0.5]}}, spec, tmp_path)
    md = (tmp_path / "verification_matrix.md").read_text()
    assert "7 of 8 requirements pass" in md and "| PNT-004 |" in md


def test_requirements_loader_rejects_bad_specs(tmp_path):
    bad = tmp_path / "r.yaml"
    bad.write_text("system: x\nversion: 1\nrequirements:\n"
                   "  - {id: A, title: t, text: t, metric: m, method: Test, threshold: {op: '=~', value: 1}}\n")
    with pytest.raises(ValueError):
        load_requirements(bad)
