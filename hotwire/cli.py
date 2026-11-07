"""Interface en ligne de commande : ``python -m hotwire <commande> ...``

Commandes :
    simulate   génère une expérience virtuelle (CSV au format du firmware)
    analyze    calcule la conductivité à partir d'un CSV
    acquire    enregistre les trames d'un Arduino (ou de l'Arduino virtuel)
    design     aide au dimensionnement : sensibilités, résolution, températures
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from . import analysis, model
from .config import load_setup
from .sensors import DividerFrontEnd, Max31865FrontEnd, temperature_resolution


def _setup_from_args(a, **extra):
    sensor = getattr(a, "sensor", None)
    if sensor not in (None, "outer", "wire"):
        sensor = float(sensor)
    return load_setup(
        a.config,
        power=getattr(a, "power", None),
        length=getattr(a, "length", None),
        k_powder=getattr(a, "k", None),
        rhocp_powder=getattr(a, "rhocp", None),
        h_ext=getattr(a, "h", None),
        sensor=sensor,
        **extra,
    )


def _plt():
    import matplotlib

    if not getattr(_plt, "interactive", False):
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _finish(fig, path: str | None, show: bool):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=130, bbox_inches="tight")
        print(f"Figure : {path}")
    if show:
        _plt().show()


# ---------------------------------------------------------------------------


def cmd_simulate(a):
    from .virtual import VirtualArduino
    from .acquisition import record

    s = _setup_from_args(a)
    va = VirtualArduino(s, front_end=a.frontend, period_s=a.period, baseline_s=a.baseline,
                        heat_s=a.duration, total_s=a.baseline + a.duration + a.cooling,
                        noise_lsb=a.noise, seed=a.seed)
    n = record(va, a.out, start_heating=False, echo=False,
               notes=f"k_powder={s.k_powder} rhocp_powder={s.rhocp_powder} h_ext={s.h_ext} "
                     f"power={s.power} length={s.length} sensor={s.sensor}")
    print(f"{n} trames simulées -> {a.out}")
    ss = model.steady_state(s)
    print(f"q = {s.q_lin:.1f} W/m ; régime permanent : fil +{ss['wire']:.0f} K, paroi +{ss['surface']:.1f} K")

    if a.plot or a.show:
        plt = _plt()
        sim = model.simulate(s, duration=a.duration + a.cooling, heater_off_at=a.duration, n_out=600)
        m = analysis.load_measurement(a.out)
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot(sim.time, sim.t_wire, label="fil (simulé)", color="#c0392b")
        ax.plot(sim.time, sim.t_surface, label="paroi extérieure (simulée)", color="#2c7fb8")
        ax.plot(m.time, m.temperature, ".", ms=3, color="k", label=f"capteur mesuré ({a.frontend})")
        ax.set_xlabel("temps depuis la mise en chauffe (s)")
        ax.set_ylabel("température (°C)")
        ax.set_title(f"Simulation — k = {s.k_powder} W/m/K, P = {s.power} W")
        ax.grid(alpha=0.3)
        ax.legend()
        _finish(fig, a.plot, a.show)


def cmd_analyze(a):
    m = analysis.load_measurement(a.file, conversion="legacy" if a.legacy_conversion else "iec")
    s = _setup_from_args(a)
    if "power" in m.metadata and a.power is None:
        s = s.with_(power=float(m.metadata["power"]))
    if "length" in m.metadata and a.length is None:
        s = s.with_(length=float(m.metadata["length"]))
    t, T = m.heating_phase()
    print(f"Fichier : {a.file} ({len(t)} points en phase de chauffe, {t.min():g}–{t.max():g} s)")
    print(f"P = {s.power} W, L = {s.length} m -> q = {s.q_lin:.2f} W/m\n")
    methods = ["slope", "line", "model"] if a.method == "all" else [a.method]
    results = {}

    if "slope" in methods:
        r = analysis.slope_method(t, T, s.q_lin, a.t_min, a.t_max)
        results["slope"] = r
        print("[1] Méthode de la pente (T vs ln t)")
        print("   ", r)
        k_old = analysis.legacy_spreadsheet_k(t, T, s.power, s.length, r.t_min, r.t_max)
        print(f"    (calcul du tableur d'origine, avec log10 : k = {k_old:.4g} W/m/K — sous-estimé d'un facteur 2,303)\n")

    radius = a.radius if a.radius is not None else (
        s.outer_radius if s.sensor == "outer" else s.wire_radius if s.sensor == "wire" else float(s.sensor))
    if "line" in methods and radius < 5 * s.wire_radius:
        print("[2] Ajustement E1 ignoré : capteur sur le fil (α n'est pas identifiable à r ≈ 0).\n")
        methods.remove("line")
    if "line" in methods:
        r = analysis.fit_line_source(t, T, radius, s.q_lin, t_min=a.t_min or 0.0, t_max=a.t_max)
        results["line"] = r
        print(f"[2] Ajustement source linéique E1 (capteur à r = {radius * 1000:.2f} mm, milieu infini)")
        print(r, "\n")

    if "model" in methods:
        t_base = m.baseline_temperature()
        if a.free:
            free = tuple(a.free.split(","))
        else:
            # h n'influence le capteur sur le fil que si la chaleur atteint la paroi
            free = ("k_powder", "rhocp_powder") if s.sensor == "wire" else ("k_powder", "rhocp_powder", "h_ext")
            if t_base is None:
                free += ("t_ambient",)
        if t_base is not None:
            s = s.with_(t_ambient=t_base)
            print(f"    T ambiante = {t_base:.3f} °C (moyenne de la ligne de base)")
        print(f"[3] Problème inverse, modèle complet (paramètres libres : {', '.join(free)}) ...")
        r = analysis.fit_setup(t, T, s, free=free, t_min=a.t_min or 0.0, t_max=a.t_max)
        results["model"] = r
        print(r)
        corr = np.abs(r.correlation - np.eye(len(free)))
        if corr.max() > 0.95:
            print("    /!\\ corrélations > 0,95 : ces paramètres sont mal séparés par cette mesure ;"
                  " les incertitudes linéarisées sont à prendre avec prudence.")
        print()

    if a.plot or a.show:
        plt = _plt()
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        ax = axes[0]
        ax.plot(t, T, ".", ms=4, color="k", label="mesure")
        if "line" in results:
            ax.plot(results["line"].t, results["line"].model, label="ajustement E1", color="#e67e22")
        if "model" in results:
            ax.plot(results["model"].t, results["model"].model, label="modèle complet", color="#27ae60")
        ax.set_xlabel("temps (s)")
        ax.set_ylabel("température (°C)")
        ax.grid(alpha=0.3)
        ax.legend()
        ax = axes[1]
        pos = t > 0
        ax.semilogx(t[pos], T[pos], ".", ms=4, color="k", label="mesure")
        if "slope" in results:
            r = results["slope"]
            tt = np.geomspace(r.t_min, r.t_max, 50)
            ax.semilogx(tt, r.intercept + r.slope * np.log(tt), color="#c0392b", lw=2,
                        label=f"pente : k = {r.k:.3g} W/m/K")
            ax.axvspan(r.t_min, r.t_max, color="#c0392b", alpha=0.07)
        ax.set_xlabel("temps (s, échelle log)")
        ax.set_ylabel("température (°C)")
        ax.grid(alpha=0.3, which="both")
        ax.legend()
        fig.suptitle(Path(a.file).name)
        _finish(fig, a.plot, a.show)


def cmd_acquire(a):
    from .acquisition import list_ports, open_serial, record

    if a.list_ports:
        ports = list_ports()
        print("\n".join(ports) if ports else "Aucun port série détecté.")
        return
    if a.simulate:
        from .virtual import VirtualArduino

        s = _setup_from_args(a)
        src = VirtualArduino(s, front_end=a.frontend, period_s=a.period, baseline_s=a.baseline,
                             heat_s=a.duration, speed=a.speed)
        print(f"Arduino virtuel (temps accéléré x{a.speed}) — Ctrl+C pour arrêter")
    else:
        if not a.port:
            sys.exit("Préciser --port (ex. COM3 ou /dev/ttyACM0), --list-ports ou --simulate")
        src = open_serial(a.port, a.baud)
        print(f"Port {a.port} ouvert à {a.baud} bauds — Ctrl+C pour arrêter")
    n = record(src, a.out, start_heating=not a.no_start, max_seconds=a.baseline + a.duration + a.cooling)
    src.close()
    print(f"{n} trames enregistrées dans {a.out}")


def cmd_design(a):
    s = _setup_from_args(a)
    ss = model.steady_state(s)
    print(f"Montage : fil Ø{2e3 * s.wire_radius:.2f} mm, poudre Ø{2e3 * s.powder_radius:.1f} mm, "
          f"L = {s.length * 1e3:.0f} mm, P = {s.power} W (q = {s.q_lin:.1f} W/m)")
    print(f"Poudre supposée : k = {s.k_powder} W/m/K, ρc = {s.rhocp_powder:.3g} J/m³/K "
          f"(α = {s.alpha_powder:.3g} m²/s)\n")
    t_reach = s.powder_radius**2 / (4 * s.alpha_powder)
    print(f"Temps caractéristique de diffusion jusqu'à la paroi r²/4α : {t_reach:.0f} s")
    print(f"Temps de mise en régime global (capacité × résistance) : {model.time_constant(s):.0f} s")
    print(f"Régime permanent : fil +{ss['wire']:.0f} K, paroi intérieure +{ss['inner_wall']:.1f} K, "
          f"surface +{ss['surface']:.1f} K")
    if s.t_ambient + ss["wire"] > 150:
        print("  /!\\ le fil dépasserait 150 °C en régime permanent : réduire la puissance ou la durée.")
    p_rec = 4 * np.pi * s.k_powder * 1.0  # pente de 1 K par unité de ln(t)
    print(f"Puissance linéique donnant une pente de ~1 K/ln(t) au fil : {p_rec:.1f} W/m "
          f"(soit P ≈ {p_rec * s.length:.2f} W)\n")

    print("Résolution des chaînes de mesure PT100 (à 25 °C) :")
    for name, fe in [("pont 10 kΩ / réf 5 V (montage d'origine)", DividerFrontEnd(10_000, vref=5.0)),
                     ("pont 1 kΩ / réf 1,1 V / 64 lectures", DividerFrontEnd(1_000, vref=1.1, oversampling=64, sensor_side="low")),
                     ("MAX31865 (15 bits)", Max31865FrontEnd())]:
        print(f"   {name:42s} {temperature_resolution(fe):8.3f} °C"
              f"   (auto-échauffement {fe.sensor_power_w() * 1e3:.2f} mW)")
    print()

    times = np.geomspace(5, a.duration, 80)
    sens = {}
    for where in ("wire", "outer"):
        sens[where] = analysis.sensitivity(s.with_(sensor=where), times)
    print("Justesse de la méthode de la pente avec un capteur sur le fil (simulation sans bruit) :")
    for t0, t1, k_est, err in analysis.slope_window_scan(s):
        flag = "  <- OK" if abs(err) < 0.02 else ""
        print(f"   fenêtre {t0:5g}–{t1:<6g} s : k = {k_est:.4f} W/m/K  (erreur {err:+6.1%}){flag}")
    print("   (erreur aux temps courts : rayon et capacité thermique du fil ;"
          " aux temps longs : la chaleur atteint la paroi du tube)\n")

    print("Sensibilité à k (variation de T pour +100 % de k), en fin d'essai :")
    for where, label in (("wire", "capteur sur le fil"), ("outer", "capteur sur la paroi")):
        print(f"   {label:22s} X_k = {sens[where]['k_powder'][-1]:+7.2f} K,"
              f"  X_ρc = {sens[where]['rhocp_powder'][-1]:+7.2f} K,  X_h = {sens[where]['h_ext'][-1]:+7.2f} K")

    if a.plot or a.show:
        plt = _plt()
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
        names = {"k_powder": "k poudre", "rhocp_powder": "ρc poudre", "h_ext": "h extérieur"}
        colors = {"k_powder": "#c0392b", "rhocp_powder": "#2c7fb8", "h_ext": "#7f8c8d"}
        for ax, (where, title) in zip(axes, (("wire", "Capteur sur le fil"), ("outer", "Capteur sur la paroi du tube"))):
            for p, v in sens[where].items():
                ax.semilogx(times, v, label=names[p], color=colors[p], lw=2)
            ax.axhline(0, color="k", lw=0.8)
            ax.set_title(title)
            ax.set_xlabel("temps (s)")
            ax.grid(alpha=0.3, which="both")
        axes[0].set_ylabel("sensibilité réduite p·∂T/∂p (K)")
        axes[0].legend()
        fig.suptitle("Ce que « voit » chaque capteur quand un paramètre varie de 100 %")
        _finish(fig, a.plot, a.show)


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hotwire", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, physics=True):
        sp.add_argument("--config", help="fichier TOML du montage (défaut : config/montage.toml)")
        sp.add_argument("--power", type=float, help="puissance de chauffe (W)")
        sp.add_argument("--length", type=float, help="longueur chauffée / hauteur de poudre (m)")
        sp.add_argument("--sensor", help="position du capteur : outer, wire ou rayon en m")
        if physics:
            sp.add_argument("--k", type=float, help="conductivité de la poudre (W/m/K)")
            sp.add_argument("--rhocp", type=float, help="ρ·c de la poudre (J/m³/K)")
            sp.add_argument("--h", type=float, help="coefficient d'échange extérieur (W/m²/K)")
        sp.add_argument("--plot", help="enregistre la figure (PNG/SVG/PDF)")
        sp.add_argument("--show", action="store_true", help="affiche la figure à l'écran")

    sp = sub.add_parser("simulate", help="génère une expérience virtuelle")
    common(sp)
    sp.add_argument("--duration", type=float, default=3600, help="durée de chauffe (s)")
    sp.add_argument("--baseline", type=float, default=60, help="ligne de base avant chauffe (s)")
    sp.add_argument("--cooling", type=float, default=0, help="durée de refroidissement enregistrée (s)")
    sp.add_argument("--period", type=float, default=10, help="période d'échantillonnage (s)")
    sp.add_argument("--frontend", default="max31865", choices=["max31865", "divider", "divider-legacy"])
    sp.add_argument("--noise", type=float, default=0.7, help="bruit de l'ADC (LSB)")
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--out", default="data/simulation.csv")
    sp.set_defaults(func=cmd_simulate)

    sp = sub.add_parser("analyze", help="calcule la conductivité à partir d'un CSV")
    common(sp)
    sp.add_argument("file")
    sp.add_argument("--method", default="slope", choices=["slope", "line", "model", "all"])
    sp.add_argument("--t-min", type=float, help="début de la fenêtre d'ajustement (s)")
    sp.add_argument("--t-max", type=float, help="fin de la fenêtre d'ajustement (s)")
    sp.add_argument("--radius", type=float, help="distance capteur–fil pour --method line (m)")
    sp.add_argument("--free", help="paramètres ajustés par --method model, séparés par des virgules "
                                   "(défaut : k_powder,rhocp_powder[,h_ext][,t_ambient] selon le capteur)")
    sp.add_argument("--legacy-conversion", action="store_true",
                    help="convertit R en T avec le coefficient linéaire 0.00391 du tableur")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("acquire", help="enregistre les trames d'un Arduino")
    common(sp)
    sp.add_argument("--port", help="port série (COM3, /dev/ttyACM0, ...)")
    sp.add_argument("--baud", type=int, default=115200)
    sp.add_argument("--list-ports", action="store_true")
    sp.add_argument("--simulate", action="store_true", help="utilise l'Arduino virtuel")
    sp.add_argument("--speed", type=float, default=60.0, help="accélération du temps en simulation")
    sp.add_argument("--frontend", default="max31865", choices=["max31865", "divider", "divider-legacy"])
    sp.add_argument("--period", type=float, default=10)
    sp.add_argument("--baseline", type=float, default=60)
    sp.add_argument("--duration", type=float, default=3600)
    sp.add_argument("--cooling", type=float, default=0)
    sp.add_argument("--no-start", action="store_true", help="n'envoie pas la commande de démarrage")
    sp.add_argument("--out", default="data/acquisition.csv")
    sp.set_defaults(func=cmd_acquire)

    sp = sub.add_parser("design", help="aide au dimensionnement de l'expérience")
    common(sp)
    sp.add_argument("--duration", type=float, default=3600)
    sp.set_defaults(func=cmd_design)
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    a = build_parser().parse_args(argv)
    if getattr(a, "show", False):
        _plt.interactive = True
    a.func(a)


if __name__ == "__main__":
    main()
