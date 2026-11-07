"""Modèle thermique du montage « fil chaud dans un tube de poudre ».

Deux niveaux de modélisation sont proposés :

* :func:`line_source_rise` — solution analytique de Carslaw & Jaeger pour une
  source linéique infinie, de puissance linéique constante ``q``, dans un
  milieu infini.  C'est la base théorique de la méthode du fil chaud.

* :func:`simulate` — simulation numérique (volumes finis, schéma implicite)
  de la conduction radiale dans le montage réel : fil chauffant + poudre +
  paroi du tube + échange convectif avec l'air ambiant.  Elle permet de
  vérifier dans quelles conditions la solution analytique s'applique, de
  dimensionner une expérience, et de générer des données synthétiques
  « comme si » on avait un Arduino branché.

Hypothèses : problème 1D radial (tube long devant son diamètre, pertes par
les extrémités négligées), propriétés constantes, contact parfait entre
couches, puissance de chauffe constante.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from scipy.linalg import solve_banded
from scipy.special import exp1

EULER_GAMMA = 0.5772156649015329

# Alliages de fil chauffant (valeurs à 20 °C, fiches fabricants).
# resistivity en Ω·m, rhocp = masse volumique × capacité thermique en J/m³/K.
WIRE_MATERIALS = {
    "kanthal_a1": {"label": "Kanthal A1 (FeCrAl)", "resistivity": 1.45e-6, "rhocp": 7100 * 460, "t_max": 1400},
    "nichrome": {"label": "Nichrome 80/20 (NiCr)", "resistivity": 1.09e-6, "rhocp": 8300 * 460, "t_max": 1200},
    "constantan": {"label": "Constantan (CuNi)", "resistivity": 0.49e-6, "rhocp": 8900 * 390, "t_max": 600},
}


@dataclass
class Setup:
    """Description complète d'une expérience (unités SI, températures en °C)."""

    # --- Géométrie -------------------------------------------------------
    wire_radius: float = 0.25e-3      # rayon du fil chauffant (m)
    powder_radius: float = 14.5e-3    # rayon intérieur du tube = épaisseur de poudre (m)
    tube_thickness: float = 1.5e-3    # épaisseur de la paroi du tube (m)
    length: float = 0.041             # hauteur de poudre chauffée (m)

    # --- Matériaux (rhocp = masse volumique x capacité thermique, J/m³/K) --
    k_powder: float = 0.20
    rhocp_powder: float = 1.2e6
    k_tube: float = 0.19              # PVC par défaut
    rhocp_tube: float = 1.9e6
    wire_material: str = "kanthal_a1"  # clé de WIRE_MATERIALS (sert au dimensionnement électrique)
    rhocp_wire: float = 3.27e6        # Kanthal A1 : 7100 kg/m³ × 460 J/kg/K

    # --- Conditions ------------------------------------------------------
    power: float = 3.77               # puissance électrique dans le fil (W)
    h_ext: float = 10.0               # coefficient d'échange extérieur (W/m²/K)
    t_ambient: float = 20.0           # température ambiante et initiale (°C)

    # --- Capteur ---------------------------------------------------------
    sensor: str | float = "outer"     # "outer" (paroi extérieure), "wire", ou un rayon en m

    @property
    def q_lin(self) -> float:
        """Puissance linéique (W/m)."""
        return self.power / self.length

    @property
    def outer_radius(self) -> float:
        return self.powder_radius + self.tube_thickness

    @property
    def alpha_powder(self) -> float:
        """Diffusivité thermique de la poudre (m²/s)."""
        return self.k_powder / self.rhocp_powder

    def with_(self, **kwargs) -> "Setup":
        return replace(self, **kwargs)


# ---------------------------------------------------------------------------
# Solution analytique
# ---------------------------------------------------------------------------


def line_source_rise(r, t, q_lin: float, k: float, alpha: float):
    """Élévation de température ΔT(r, t) autour d'une source linéique.

    ΔT = q / (4 π k) · E1( r² / (4 α t) )

    Pour t >> r²/(4α), E1(x) ≈ -γ - ln(x), d'où la loi logarithmique
    ΔT ≈ q/(4πk) · [ln(t) + ln(4α/r²) - γ] utilisée par la méthode de la pente.
    """
    t = np.asarray(t, dtype=float)
    out = np.zeros_like(t)
    pos = t > 0
    out[pos] = q_lin / (4 * np.pi * k) * exp1(r * r / (4 * alpha * t[pos]))
    return out


def log_regime_time(r: float, alpha: float, tolerance: float = 0.01) -> float:
    """Temps à partir duquel l'approximation logarithmique est valable.

    L'erreur relative sur la pente dΔT/d(ln t) vaut exp(-r²/(4αt)) - 1 ≈ -r²/(4αt),
    d'où t > r² / (4 α tolerance).
    """
    return r * r / (4 * alpha * tolerance)


# ---------------------------------------------------------------------------
# Simulation numérique
# ---------------------------------------------------------------------------


@dataclass
class Grid:
    faces: np.ndarray       # rayons des faces (m), faces[0] = 0
    centers: np.ndarray     # rayons des centres de mailles (m)
    k: np.ndarray           # conductivité de chaque maille
    capacity: np.ndarray    # capacité thermique par unité de longueur (J/m/K)
    conductance: np.ndarray  # conductance entre mailles i et i+1 (W/m/K)
    g_out: float            # conductance maille externe -> ambiance (W/m/K)
    r_wall: float           # résistance maille externe -> surface (m.K/W)
    r_conv: float           # résistance surface -> ambiance (m.K/W)


def build_grid(s: Setup, n_powder: int = 60, n_tube: int = 4) -> Grid:
    """Maillage radial : 1 maille pour le fil, maillage logarithmique dans la
    poudre (raffiné près du fil), maillage régulier dans la paroi."""
    f_powder = np.geomspace(s.wire_radius, s.powder_radius, n_powder + 1)
    f_tube = np.linspace(s.powder_radius, s.outer_radius, n_tube + 1)
    faces = np.concatenate([[0.0], f_powder, f_tube[1:]])

    centers = np.empty(len(faces) - 1)
    centers[0] = 0.0
    centers[1 : n_powder + 1] = np.sqrt(f_powder[:-1] * f_powder[1:])
    centers[n_powder + 1 :] = 0.5 * (f_tube[:-1] + f_tube[1:])

    k = np.concatenate([[np.inf], np.full(n_powder, s.k_powder), np.full(n_tube, s.k_tube)])
    rhocp = np.concatenate([[s.rhocp_wire], np.full(n_powder, s.rhocp_powder), np.full(n_tube, s.rhocp_tube)])
    capacity = rhocp * np.pi * (faces[1:] ** 2 - faces[:-1] ** 2)

    # Résistances en série de part et d'autre de chaque face interne.
    n = len(centers)
    conductance = np.empty(n - 1)
    for i in range(n - 1):
        rf = faces[i + 1]
        r_left = 0.0 if i == 0 else np.log(rf / centers[i]) / (2 * np.pi * k[i])
        r_right = np.log(centers[i + 1] / rf) / (2 * np.pi * k[i + 1])
        conductance[i] = 1.0 / (r_left + r_right)

    r_wall = np.log(s.outer_radius / centers[-1]) / (2 * np.pi * k[-1])
    r_conv = 1.0 / (2 * np.pi * s.outer_radius * s.h_ext) if s.h_ext > 0 else np.inf
    g_out = 1.0 / (r_wall + r_conv)
    return Grid(faces, centers, k, capacity, conductance, g_out, r_wall, r_conv)


@dataclass
class SimResult:
    time: np.ndarray            # s, depuis la mise en chauffe
    t_sensor: np.ndarray        # °C, au capteur choisi dans Setup.sensor
    t_wire: np.ndarray          # °C
    t_surface: np.ndarray       # °C, paroi extérieure du tube
    setup: Setup
    grid: Grid = field(repr=False)
    profiles: np.ndarray | None = field(default=None, repr=False)  # (n_temps, n_mailles)


def _output_times(duration: float, n_out: int) -> np.ndarray:
    return np.linspace(0.0, duration, n_out + 1)


def simulate(
    s: Setup,
    times=None,
    duration: float = 3600.0,
    n_out: int = 360,
    max_dt: float = 5.0,
    heater_off_at: float | None = None,
    n_powder: int = 60,
    n_tube: int = 4,
    keep_profiles: bool = False,
) -> SimResult:
    """Simule la réponse du montage à un échelon de puissance à t = 0.

    ``times`` : instants de sortie (s) ; par défaut ``n_out`` points réguliers
    sur ``duration``.  Le pas interne est adaptatif (petit au début, ≤ max_dt).
    ``heater_off_at`` : instant d'arrêt du chauffage (phase de refroidissement).
    """
    g = build_grid(s, n_powder, n_tube)
    times = _output_times(duration, n_out) if times is None else np.asarray(times, dtype=float)
    if np.any(np.diff(times) < 0):
        raise ValueError("Les instants de sortie doivent être croissants.")

    n = len(g.centers)
    theta = np.zeros(n)  # élévation de température par rapport à l'ambiance
    diag_cond = np.zeros(n)
    diag_cond[:-1] += g.conductance
    diag_cond[1:] += g.conductance
    diag_cond[-1] += g.g_out

    def step(theta, dt, q):
        ab = np.zeros((3, n))
        ab[0, 1:] = -g.conductance
        ab[1, :] = g.capacity / dt + diag_cond
        ab[2, :-1] = -g.conductance
        rhs = g.capacity / dt * theta
        rhs[0] += q
        return solve_banded((1, 1), ab, rhs)

    out_wire = np.empty(len(times))
    out_surf = np.empty(len(times))
    out_sensor = np.empty(len(times))
    profiles = np.empty((len(times), n)) if keep_profiles else None

    sensor_r = None if s.sensor in ("outer", "wire") else float(s.sensor)
    surf_ratio = g.r_conv / (g.r_wall + g.r_conv) if np.isfinite(g.r_conv) else 1.0

    def record(j, theta):
        out_wire[j] = theta[0]
        out_surf[j] = theta[-1] * surf_ratio
        if s.sensor == "wire":
            out_sensor[j] = out_wire[j]
        elif s.sensor == "outer":
            out_sensor[j] = out_surf[j]
        else:
            r_nodes = np.concatenate([[s.wire_radius], g.centers[1:], [s.outer_radius]])
            th_nodes = np.concatenate([[theta[0]], theta[1:], [out_surf[j]]])
            out_sensor[j] = np.interp(np.log(sensor_r), np.log(r_nodes), th_nodes)
        if profiles is not None:
            profiles[j] = theta

    t_now = 0.0
    for j, t_target in enumerate(times):
        while t_now < t_target - 1e-12:
            # pas adaptatif : ~5 % du temps écoulé, borné, et arrêt exact aux évènements
            dt = min(max_dt, max(0.05 * t_now, 0.01), t_target - t_now)
            if heater_off_at is not None and t_now < heater_off_at < t_now + dt:
                dt = heater_off_at - t_now
            heating = heater_off_at is None or t_now < heater_off_at
            theta = step(theta, dt, s.q_lin if heating else 0.0)
            t_now += dt
        record(j, theta)

    amb = s.t_ambient
    return SimResult(
        time=times,
        t_sensor=out_sensor + amb,
        t_wire=out_wire + amb,
        t_surface=out_surf + amb,
        setup=s,
        grid=g,
        profiles=None if profiles is None else profiles + amb,
    )


def wire_electrical(s: Setup) -> dict:
    """Résistance du fil chauffé et tension/courant nécessaires pour ``s.power``."""
    mat = WIRE_MATERIALS[s.wire_material]
    resistance = mat["resistivity"] * s.length / (np.pi * s.wire_radius**2)
    current = np.sqrt(s.power / resistance)
    return {
        "material": mat["label"],
        "ohm_per_m": mat["resistivity"] / (np.pi * s.wire_radius**2),
        "resistance": resistance,
        "current": current,
        "voltage": current * resistance,
    }


def wire_diameter_from_measurement(voltage: float, current: float, length: float, material: str = "kanthal_a1") -> float:
    """Diamètre de fil (m) cohérent avec U, I mesurés aux bornes d'une longueur ``length``."""
    rho = WIRE_MATERIALS[material]["resistivity"]
    area = rho * length * current / voltage
    return 2 * np.sqrt(area / np.pi)


def steady_state(s: Setup) -> dict:
    """Températures en régime permanent (élévations au-dessus de l'ambiance, K)."""
    q = s.q_lin
    r_powder = np.log(s.powder_radius / s.wire_radius) / (2 * np.pi * s.k_powder)
    r_tube = np.log(s.outer_radius / s.powder_radius) / (2 * np.pi * s.k_tube)
    r_conv = 1.0 / (2 * np.pi * s.outer_radius * s.h_ext)
    return {
        "surface": q * r_conv,
        "inner_wall": q * (r_conv + r_tube),
        "wire": q * (r_conv + r_tube + r_powder),
    }


def time_constant(s: Setup) -> float:
    """Ordre de grandeur du temps de mise en régime global (s) :
    capacité totale x résistance totale."""
    c = (
        s.rhocp_powder * np.pi * (s.powder_radius**2 - s.wire_radius**2)
        + s.rhocp_tube * np.pi * (s.outer_radius**2 - s.powder_radius**2)
    )
    ss = steady_state(s)
    return c * ss["wire"] / s.q_lin
