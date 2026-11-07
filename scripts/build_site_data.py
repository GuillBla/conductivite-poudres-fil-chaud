"""Génère site/data/results.json : résultats calculés par le package Python
(réanalyse des essais v1, sensibilités, fenêtres de validité) et valeurs de
référence utilisées pour tester le portage JavaScript du modèle.

    python scripts/build_site_data.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

from hotwire import analysis, model  # noqa: E402
from hotwire.config import load_setup  # noqa: E402

OUT = ROOT / "site" / "data"


def r(x, n=5):
    """Arrondi pour alléger le JSON."""
    if isinstance(x, (list, tuple, np.ndarray)):
        return [r(v, n) for v in x]
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return None
    return float(f"{float(x):.{n}g}")


def fit_dict(fr):
    return {
        "params": {k: r(v) for k, v in fr.params.items()},
        "std": {k: r(v, 3) for k, v in fr.std.items()},
        "rms": r(fr.rms, 3),
        "correlation": [[r(c, 3) for c in row] for row in fr.correlation],
        "names": fr.names,
        "curve": {"t": r(fr.t), "T": r(fr.model)},
    }


def essai(path, title):
    m = analysis.load_measurement(path)
    s = load_setup(None, power=float(m.metadata["power"]), length=float(m.metadata["length"]))
    t, T = m.heating_phase()
    sl = analysis.slope_method(t, T, s.q_lin)
    legacy_full = analysis.legacy_spreadsheet_k(
        *analysis.load_measurement(path, conversion="legacy").heating_phase(), s.power, s.length, t_min=t[t > 0].min())
    legacy_win = analysis.legacy_spreadsheet_k(t, T, s.power, s.length, sl.t_min, sl.t_max)
    line = analysis.fit_line_source(t, T, s.outer_radius, s.q_lin)
    full = analysis.fit_setup(t, T, s)
    energy = s.power * t.max()
    cap = s.rhocp_powder * np.pi * s.powder_radius**2 * s.length
    return {
        "title": title,
        "file": Path(path).name,
        "power": s.power,
        "length": s.length,
        "q": r(s.q_lin),
        "t": r(t),
        "T": r(T),
        "slope": {"k": r(sl.k), "k_std": r(sl.k_std, 3), "slope": r(sl.slope), "intercept": r(sl.intercept),
                  "t_min": sl.t_min, "t_max": sl.t_max, "r2": r(sl.r2), "n": sl.n},
        "legacy_k_full": r(legacy_full),
        "legacy_k_window": r(legacy_win),
        "line": fit_dict(line),
        "model": fit_dict(full),
        "energy_J": r(energy, 4),
        "capacity_J_per_K": r(cap, 3),
        "rise_without_losses_K": r(energy / cap, 3),
        "rise_measured_K": r(T.max() - T.min(), 3),
    }


def setup_dict(s):
    return {k: (v if isinstance(v, str) else float(v)) for k, v in s.__dict__.items()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    v1 = load_setup(ROOT / "config" / "montage.toml")
    rec = load_setup(ROOT / "config" / "montage_recommande.toml")

    sens = {}
    for name, s, dur in (("v1", v1, 3600), ("recommande", rec, 300)):
        times = np.geomspace(2, dur, 70)
        sens[name] = {
            "duration": dur,
            "t": r(times),
            "wire": {p: r(v, 4) for p, v in analysis.sensitivity(s.with_(sensor="wire"), times).items()},
            "outer": {p: r(v, 4) for p, v in analysis.sensitivity(s.with_(sensor="outer"), times).items()},
        }

    scan_starts = (1, 2, 5, 10, 20, 50, 100, 200, 500)
    scans = {name: [{"t_min": a, "t_max": b, "k": r(k), "error": r(e, 3)}
                    for a, b, k, e in analysis.slope_window_scan(s, scan_starts)]
             for name, s in (("v1", v1), ("recommande", rec))}

    # Valeurs de référence pour tests/js (comparaison Python <-> JavaScript)
    ref_cases = []
    for name, s, times, off in (
        ("v1_outer", v1, [10, 60, 300, 1200, 3600], None),
        ("recommande_wire", rec, [1, 10, 60, 300], None),
        ("recommande_cooling", rec.with_(sensor=0.004), [50, 100, 200, 400], 100.0),
    ):
        sim = model.simulate(s, times=times, heater_off_at=off)
        ref_cases.append({"name": name, "setup": setup_dict(s), "times": times, "heater_off_at": off,
                          "t_sensor": r(sim.t_sensor, 8), "t_wire": r(sim.t_wire, 8),
                          "t_surface": r(sim.t_surface, 8)})
    tt = np.linspace(1, 600, 600)
    temp = 20 + model.line_source_rise(1e-3, tt, 10.0, 0.25, 2e-7)
    ref_line = {"r": 1e-3, "q": 10.0, "k": 0.25, "alpha": 2e-7, "t": [1, 10, 100, 600],
                "dT": r(model.line_source_rise(1e-3, np.array([1, 10, 100, 600.0]), 10.0, 0.25, 2e-7), 10),
                "slope_k_10_600": r(analysis.slope_method(tt, temp, 10.0, 10, 600).k, 10)}

    data = {
        "generated_by": "scripts/build_site_data.py",
        "setups": {"v1": setup_dict(v1), "recommande": setup_dict(rec)},
        "essais": [essai(ROOT / "data" / "essai_1.csv", "Essai 1"),
                   essai(ROOT / "data" / "essai_2.csv", "Essai 2")],
        "sensitivity": sens,
        "window_scan": scans,
        "reference": {"simulate": ref_cases, "line_source": ref_line},
    }
    (OUT / "results.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for f in ("essai_1.csv", "essai_2.csv", "simulation_recommande.csv"):
        shutil.copy(ROOT / "data" / f, OUT / f)
    print(f"{OUT / 'results.json'} ({(OUT / 'results.json').stat().st_size / 1024:.0f} Ko)")


if __name__ == "__main__":
    main()
