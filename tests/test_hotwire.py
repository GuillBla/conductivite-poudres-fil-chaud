"""Tests : modèle physique, capteurs, méthodes d'analyse et chaîne complète
(Arduino virtuel -> acquisition -> analyse)."""

from pathlib import Path

import numpy as np
import pytest

from hotwire import analysis, model, sensors
from hotwire.acquisition import record
from hotwire.virtual import VirtualArduino


# --- capteurs ---------------------------------------------------------------

def test_pt100_roundtrip():
    t = np.linspace(0, 300, 31)
    assert np.allclose(sensors.pt100_temperature(sensors.pt100_resistance(t)), t, atol=1e-9)


def test_pt100_reference_points():
    # Table IEC 60751 : 100 °C -> 138.51 Ω
    assert sensors.pt100_resistance(0) == pytest.approx(100.0)
    assert sensors.pt100_resistance(100) == pytest.approx(138.5055, abs=1e-3)


def test_legacy_divider_resolution_is_useless():
    fe = sensors.DividerFrontEnd(r_ref=10_000, vref=5.0)
    assert sensors.temperature_resolution(fe) > 20  # > 20 °C par pas d'ADC


@pytest.mark.parametrize("side", ["high", "low"])
def test_divider_roundtrip(side):
    fe = sensors.DividerFrontEnd(r_ref=1000, vref=5.0, sensor_side=side)
    r = 110.0
    assert fe.resistance(fe.counts(r)) == pytest.approx(r, abs=2 * fe.resolution_ohm(r))


def test_max31865_resolution():
    assert sensors.temperature_resolution(sensors.Max31865FrontEnd()) < 0.05


# --- modèle -----------------------------------------------------------------

def test_numerical_model_matches_line_source():
    # tube très grand => milieu quasi infini
    s = model.Setup(powder_radius=0.3, wire_radius=0.05e-3, h_ext=1e3, sensor=0.01)
    t = np.array([200.0, 600.0, 1800.0])
    sim = model.simulate(s, times=t, n_powder=120)
    ana = model.line_source_rise(0.01, t, s.q_lin, s.k_powder, s.alpha_powder)
    assert np.allclose(sim.t_sensor - s.t_ambient, ana, rtol=0.01)


def test_energy_balance_steady_state():
    s = model.Setup(power=0.5)
    sim = model.simulate(s, times=[2e5], max_dt=200)
    ss = model.steady_state(s)
    assert sim.t_wire[-1] - s.t_ambient == pytest.approx(ss["wire"], rel=0.01)
    assert sim.t_surface[-1] - s.t_ambient == pytest.approx(ss["surface"], rel=0.01)


def test_cooling_returns_to_ambient():
    s = model.Setup(power=0.5)
    sim = model.simulate(s, times=[300, 1e5], heater_off_at=300, max_dt=100)
    assert sim.t_wire[-1] == pytest.approx(s.t_ambient, abs=0.01)


# --- analyse ----------------------------------------------------------------

def test_slope_method_on_exact_line_source():
    t = np.linspace(1, 600, 600)
    q, k, a = 10.0, 0.25, 2e-7
    temp = 20 + model.line_source_rise(1e-4, t, q, k, a)
    r = analysis.slope_method(t, temp, q, 10, 600)
    assert r.k == pytest.approx(k, rel=1e-3)


def test_legacy_spreadsheet_bias_is_ln10():
    t = np.linspace(1, 600, 600)
    temp = 20 + model.line_source_rise(1e-4, t, 10.0, 0.25, 2e-7)
    k_ok = analysis.slope_method(t, temp, 10.0, 10, 600).k
    k_old = analysis.legacy_spreadsheet_k(t, temp, 10.0 * 0.04, 0.04, 10, 600)
    assert k_ok / k_old == pytest.approx(np.log(10), rel=1e-6)


def test_fit_line_source_recovers_k_and_alpha():
    t = np.linspace(5, 1200, 240)
    r, q, k, a = 5e-3, 10.0, 0.3, 2.5e-7
    rng = np.random.default_rng(1)
    temp = 21 + model.line_source_rise(r, t, q, k, a) + rng.normal(0, 0.01, t.size)
    fit = analysis.fit_line_source(t, temp, r, q)
    assert fit.params["k"] == pytest.approx(k, rel=0.02)
    assert fit.params["alpha"] == pytest.approx(a, rel=0.05)


def test_fit_setup_recovers_parameters_from_wire_sensor():
    true = model.Setup(sensor="wire", power=0.3, k_powder=0.15, rhocp_powder=1.0e6, h_ext=8.0)
    t = np.linspace(2, 900, 150)
    temp = model.simulate(true, times=t).t_sensor
    guess = true.with_(k_powder=0.3, rhocp_powder=1.5e6, h_ext=15.0)
    fit = analysis.fit_setup(t, temp, guess, free=("k_powder", "rhocp_powder", "h_ext", "t_ambient"))
    assert fit.params["k_powder"] == pytest.approx(0.15, rel=0.01)


# --- chaîne complète sans matériel --------------------------------------------

def test_virtual_arduino_end_to_end(tmp_path):
    s = model.Setup(sensor="wire", power=0.15, wire_radius=0.05e-3, powder_radius=0.04, k_powder=0.18)
    va = VirtualArduino(s, front_end="max31865", period_s=1.0, baseline_s=20, heat_s=300, seed=3)
    out = tmp_path / "run.csv"
    n = record(va, out, echo=False)
    assert n == 321
    m = analysis.load_measurement(out)
    t, temp = m.heating_phase()
    assert t[0] == 0
    r = analysis.slope_method(t, temp, s.q_lin, 10, 300)
    assert r.k == pytest.approx(0.18, rel=0.05)


def test_load_legacy_data():
    m = analysis.load_measurement(Path(__file__).parent.parent / "data" / "essai_2.csv", conversion="legacy")
    assert m.metadata["power"] == "3.77"
    assert m.temperature[0] == pytest.approx(18.67007673, abs=1e-6)  # valeur du tableur


def test_kanthal_wire_electrical():
    s = model.Setup(wire_radius=0.05e-3, length=0.2, power=0.8, wire_material="kanthal_a1")
    el = model.wire_electrical(s)
    assert el["ohm_per_m"] == pytest.approx(184.6, rel=1e-3)
    assert el["voltage"] * el["current"] == pytest.approx(0.8)
    d = model.wire_diameter_from_measurement(el["voltage"], el["current"], 0.2)
    assert d == pytest.approx(0.1e-3)
