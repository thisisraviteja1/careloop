from dataclasses import replace
from datetime import timedelta

import app.baseline.model as baseline_model
import app.detection.detector as detector
from scripts import evaluate as ev

SETTING = ev.Setting(ev.PERSONAS[0], "medium", 15)


def test_same_code_path_as_production() -> None:
    assert ev.compute_baseline is baseline_model.compute_baseline
    assert ev.evaluate is detector.evaluate


def test_deterministic_for_a_fixed_seed() -> None:
    assert ev.run_all(ev.SEED) == ev.run_all(ev.SEED)
    assert ev.simulate(SETTING) == ev.simulate(SETTING)
    assert ev.simulate(SETTING, seed=1) != ev.simulate(SETTING, seed=2)


def test_no_future_data_leakage() -> None:
    history = ev.simulate(SETTING)
    day = history.judged[10]
    before = ev.careloop_alert(history, day)
    # rewrite every later day: the decision for `day` must not change
    future = {d: (None if d > day else m) for d, m in history.first.items()}
    future |= {d: 300 for d in history.first if d > day + timedelta(days=1)}
    assert ev.careloop_alert(replace(history, first=future), day) == before


def test_incident_days_and_judged_days_are_shared_by_all_methods() -> None:
    results = ev.run_setting(SETTING)
    assert {r.normal_days for r in results} == {ev.DAYS - ev.WARMUP_DAYS - ev.INCIDENTS}
    assert {r.incidents for r in results} == {ev.INCIDENTS}
    assert [r.method for r in results][0] == "CareLoop baseline"


def test_timer_logic() -> None:
    history = ev.simulate(SETTING)
    incident = sorted(history.incidents)[0]
    assert ev.timer_alert(history, incident, 480) == 480
    normal = next(d for d in history.judged if history.first[d] is not None)
    early = replace(history, first=history.first | {normal: 400})
    assert ev.timer_alert(early, normal, 480) is None
