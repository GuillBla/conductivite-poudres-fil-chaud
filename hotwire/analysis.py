"""Extraction de la conductivité thermique à partir d'une mesure T(t).

Trois méthodes, de la plus simple à la plus complète :

1. :func:`slope_method` — méthode classique du fil chaud : en régime
   logarithmique, ΔT = q/(4πk)·ln(t) + cste, donc k = q / (4π · pente).
   Valable si la température est mesurée sur (ou très près) du fil, dans un
   milieu « infini » (la chaleur n'a pas encore atteint la paroi).

2. :func:`fit_line_source` — ajustement de la solution exacte E1 à un rayon r
   donné : estime à la fois k et la diffusivité α.  Utile quand le capteur
   est à distance connue du fil.

3. :func:`fit_setup` — problème inverse avec le simulateur numérique complet
   (poudre + tube + convection) : estime k, ρc et h simultanément, avec les
   incertitudes et corrélations entre paramètres.  C'est la seule méthode
   rigoureuse quand le capteur est sur la paroi extérieure du tube.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.special import exp1

from .model import Setup, simulate
from .sensors import pt100_temperature, pt100_temperature_linear


# ---------------------------------------------------------------------------
# Lecture des données
# ---------------------------------------------------------------------------


@dataclass
class Measurement:
    time: np.ndarray            # s, t = 0 à la mise en chauffe
    temperature: np.ndarray     # °C
    resistance: np.ndarray | None = None
    metadata: dict = field(default_factory=dict)
    source: str = ""
    heating_end: float | None = None  # s, fin de la chauffe si la colonne heater existe

    def heating_phase(self) -> tuple[np.ndarray, np.ndarray]:
        """(t, T) restreints à la phase de chauffe (t >= 0 et chauffe active)."""
        m = self.time >= 0
        if self.heating_end is not None:
            m &= self.time <= self.heating_end
        return self.time[m], self.temperature[m]

    def baseline_temperature(self) -> float | None:
        """Température moyenne avant la mise en chauffe (None si pas de ligne de base)."""
        m = self.time < 0
        return float(self.temperature[m].mean()) if m.sum() >= 3 else None


def _parse_metadata(comment_lines: list[str]) -> dict:
    meta = {}
    for line in comment_lines:
        for token in line.lstrip("#").split():
            if "=" in token:
                key, _, value = token.partition("=")
                meta[key.strip()] = value.strip().rstrip(",")
    return meta


def load_measurement(path: str | Path, conversion: str = "iec") -> Measurement:
    """Lit un CSV produit par le firmware, l'outil d'acquisition ou le simulateur.

    Colonnes reconnues (en-tête obligatoire, lignes ``#`` = commentaires) :
    ``time_s`` ou ``time_ms`` ; ``temperature_c`` et/ou ``resistance_ohm`` ;
    ``heater`` (0/1, optionnel : l'origine des temps est alors placée au
    premier échantillon chauffé).

    ``conversion`` : ``"iec"`` (Callendar–Van Dusen) ou ``"legacy"`` (linéaire
    à 0.00391, comme dans le tableur d'origine) pour passer de R à T.
    """
    text = Path(path).read_text(encoding="utf-8")
    comments = [l for l in text.splitlines() if l.startswith("#")]
    body = "\n".join(l for l in text.splitlines() if l.strip() and not l.startswith("#"))
    rows = list(csv.DictReader(io.StringIO(body)))
    if not rows:
        raise ValueError(f"{path} : aucune donnée")
    cols = {c.strip(): c for c in rows[0].keys()}

    def col(name):
        return np.array([float(r[cols[name]]) for r in rows])

    if "time_s" in cols:
        t = col("time_s")
    elif "time_ms" in cols:
        t = col("time_ms") / 1000.0
    else:
        raise ValueError("Colonne de temps manquante (time_s ou time_ms)")

    res = col("resistance_ohm") if "resistance_ohm" in cols else None
    if res is not None and (conversion == "legacy" or "temperature_c" not in cols):
        temp = pt100_temperature(res) if conversion == "iec" else pt100_temperature_linear(res)
    elif "temperature_c" in cols:
        temp = col("temperature_c")
    else:
        raise ValueError("Colonne temperature_c ou resistance_ohm manquante")

    heating_end = None
    if "heater" in cols:
        heater = col("heater")
        on = np.flatnonzero(heater > 0.5)
        if len(on):
            t = t - t[on[0]]
            off = np.flatnonzero((heater < 0.5) & (np.arange(len(t)) > on[0]))
            if len(off):
                heating_end = float(t[off[0]])

    return Measurement(t, np.asarray(temp, float), res, _parse_metadata(comments), str(path), heating_end)


# ---------------------------------------------------------------------------
# 1. Méthode de la pente
# ---------------------------------------------------------------------------


@dataclass
class SlopeResult:
    k: float            # conductivité (W/m/K)
    k_std: float        # écart-type statistique sur k
    slope: float        # dT/d(ln t) (K)
    slope_std: float
    intercept: float
    t_min: float
    t_max: float
    r2: float
    n: int

    def __str__(self) -> str:
        return (
            f"k = {self.k:.4g} ± {self.k_std:.2g} W/m/K "
            f"(pente {self.slope:.4g} K/ln(s), fenêtre {self.t_min:g}–{self.t_max:g} s, "
            f"{self.n} points, R² = {self.r2:.5f})"
        )


def slope_method(t, temp, q_lin: float, t_min: float | None = None, t_max: float | None = None) -> SlopeResult:
    """Régression linéaire de T en fonction de ln(t) sur [t_min, t_max].

    Par défaut la fenêtre couvre de t_end/5 à t_end (fin de courbe, où le
    régime logarithmique est le mieux établi).
    """
    t = np.asarray(t, float)
    temp = np.asarray(temp, float)
    t_end = t.max()
    t_min = t_end / 5 if t_min is None else t_min
    t_max = t_end if t_max is None else t_max
    m = (t > 0) & (t >= t_min) & (t <= t_max)
    if m.sum() < 3:
        raise ValueError("Pas assez de points dans la fenêtre d'ajustement")
    x, y = np.log(t[m]), temp[m]
    A = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    dof = max(len(x) - 2, 1)
    s2 = resid @ resid / dof
    cov = s2 * np.linalg.inv(A.T @ A)
    slope, intercept = coef
    slope_std = float(np.sqrt(cov[0, 0]))
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / ss_tot if ss_tot > 0 else 1.0
    k = q_lin / (4 * np.pi * slope)
    return SlopeResult(k, abs(k) * slope_std / abs(slope), slope, slope_std, intercept,
                       float(t[m].min()), float(t[m].max()), float(r2), int(m.sum()))


def legacy_spreadsheet_k(t, temp, power: float, length: float, t_min=None, t_max=None) -> float:
    """Reproduit le calcul du tableur d'origine : pente de T vs log10(t)
    et k = P / (4π · pente · h).  Biaisé d'un facteur ln(10) ≈ 2,303."""
    res = slope_method(t, temp, power / length, t_min, t_max)
    slope_log10 = res.slope * np.log(10)
    return power / (4 * np.pi * slope_log10 * length)


# ---------------------------------------------------------------------------
# 2. Ajustement de la solution exacte (source linéique, milieu infini)
# ---------------------------------------------------------------------------


@dataclass
class FitResult:
    params: dict            # valeurs estimées
    std: dict               # écarts-types
    correlation: np.ndarray
    names: list
    rms: float              # résidu RMS (K)
    t: np.ndarray = field(repr=False)
    model: np.ndarray = field(repr=False)
    setup: Setup | None = field(default=None, repr=False)

    def __str__(self) -> str:
        lines = [f"{n:>14s} = {self.params[n]:.5g} ± {self.std[n]:.2g}" for n in self.names]
        lines.append(f"{'résidu RMS':>14s} = {self.rms:.3g} K")
        if len(self.names) > 1:
            lines.append("corrélations :")
            for i, a in enumerate(self.names):
                lines.append(" " * 16 + " ".join(f"{self.correlation[i, j]:+.2f}" for j in range(len(self.names))) + f"  {a}")
        return "\n".join(lines)


def _covariance(res, n_points: int):
    J = res.jac
    dof = max(n_points - J.shape[1], 1)
    s2 = 2 * res.cost / dof
    JTJ = J.T @ J
    if not np.all(np.isfinite(JTJ)) or np.linalg.cond(JTJ) > 1e14:
        # problème mal conditionné : incertitudes non définies
        return np.full(JTJ.shape, np.nan)
    return np.linalg.inv(JTJ) * s2


def _pack(names, x, logscale, cov):
    params, std = {}, {}
    sd = np.sqrt(np.abs(np.diag(cov)))
    for i, n in enumerate(names):
        if logscale[i]:
            params[n] = float(np.exp(x[i]))
            std[n] = float(params[n] * sd[i])  # propagation au 1er ordre
        else:
            params[n] = float(x[i])
            std[n] = float(sd[i])
    d = np.sqrt(np.abs(np.diag(cov)))
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = cov / np.outer(d, d)
    return params, std, corr


def fit_line_source(t, temp, r: float, q_lin: float, k0: float = 0.3, alpha0: float = 2e-7,
                    t_min: float = 0.0, t_max: float | None = None) -> FitResult:
    """Ajuste T(t) = T0 + q/(4πk)·E1(r²/(4αt)) ; paramètres k, α, T0."""
    t = np.asarray(t, float)
    temp = np.asarray(temp, float)
    t_max = t.max() if t_max is None else t_max
    m = (t > 0) & (t >= t_min) & (t <= t_max)
    tm, ym = t[m], temp[m]

    def model(x, tt):
        k, a, T0 = np.exp(x[0]), np.exp(x[1]), x[2]
        return T0 + q_lin / (4 * np.pi * k) * exp1(r * r / (4 * a * tt))

    x0 = np.array([np.log(k0), np.log(alpha0), temp[0]])
    res = least_squares(lambda x: model(x, tm) - ym, x0, x_scale="jac")
    names = ["k", "alpha", "T0"]
    cov = _covariance(res, len(tm))
    params, std, corr = _pack(names, res.x, [True, True, False], cov)
    rms = float(np.sqrt(np.mean(res.fun**2)))
    return FitResult(params, std, corr, names, rms, t, model(res.x, np.where(t > 0, t, np.nan)))


# ---------------------------------------------------------------------------
# 3. Problème inverse avec le simulateur complet
# ---------------------------------------------------------------------------

_POSITIVE = {"k_powder", "rhocp_powder", "h_ext", "k_tube", "rhocp_tube", "power"}


def fit_setup(t, temp, setup: Setup, free=("k_powder", "rhocp_powder", "h_ext", "t_ambient"),
              t_min: float = 0.0, t_max: float | None = None, n_powder: int = 40) -> FitResult:
    """Ajuste les paramètres ``free`` du :class:`Setup` pour reproduire T(t).

    Les paramètres positifs sont ajustés en échelle logarithmique.  Les
    incertitudes sont issues de la jacobienne (approximation linéaire) ; une
    corrélation proche de ±1 signale des paramètres non identifiables
    séparément avec cette mesure.
    """
    t = np.asarray(t, float)
    temp = np.asarray(temp, float)
    t_max = t.max() if t_max is None else t_max
    m = (t >= t_min) & (t <= t_max) & (t >= 0)
    tm, ym = t[m], temp[m]
    names = list(free)
    logscale = [n in _POSITIVE for n in names]

    def to_setup(x):
        vals = {n: (np.exp(v) if lg else v) for n, v, lg in zip(names, x, logscale)}
        return setup.with_(**vals)

    def model(x, tt):
        return simulate(to_setup(x), times=tt, n_powder=n_powder).t_sensor

    x0 = np.array([np.log(getattr(setup, n)) if lg else getattr(setup, n) for n, lg in zip(names, logscale)])
    if "t_ambient" in names:
        x0[names.index("t_ambient")] = temp[np.argmin(t)]
    lo = np.where(logscale, x0 - 7.0, x0 - 50.0)   # facteur e^7 ≈ 1000 autour de la valeur initiale
    hi = np.where(logscale, x0 + 7.0, x0 + 50.0)
    res = least_squares(lambda x: model(x, tm) - ym, x0, x_scale="jac", diff_step=1e-4, bounds=(lo, hi))
    cov = _covariance(res, len(tm))
    params, std, corr = _pack(names, res.x, logscale, cov)
    rms = float(np.sqrt(np.mean(res.fun**2)))
    fitted = to_setup(res.x)
    t_plot = t[t >= 0]
    return FitResult(params, std, corr, names, rms, t_plot, model(res.x, t_plot), fitted)


# ---------------------------------------------------------------------------
# Étude de sensibilité (conception d'expérience)
# ---------------------------------------------------------------------------


def sensitivity(setup: Setup, times, params=("k_powder", "rhocp_powder", "h_ext"), rel_step: float = 0.01) -> dict:
    """Coefficients de sensibilité réduits X_p(t) = p · ∂T_capteur/∂p (en K).

    Interprétation : X_p est la variation de température mesurée pour une
    variation relative de 100 % du paramètre p (au premier ordre).  Si deux
    courbes X_p(t) sont proportionnelles, les paramètres correspondants ne
    peuvent pas être estimés séparément ; si X_k est petit devant le bruit de
    mesure, la conductivité n'est pas mesurable avec ce capteur.
    """
    times = np.asarray(times, float)
    out = {}
    for p in params:
        v = getattr(setup, p)
        up = simulate(setup.with_(**{p: v * (1 + rel_step)}), times=times).t_sensor
        dn = simulate(setup.with_(**{p: v * (1 - rel_step)}), times=times).t_sensor
        out[p] = (up - dn) / (2 * rel_step)
    return out


def slope_window_scan(setup: Setup, t_starts=(1, 2, 5, 10, 20, 50, 100, 200, 500), ratio: float = 10.0) -> list:
    """Erreur de la méthode de la pente, capteur sur le fil, pour des fenêtres
    [t, ratio·t] — données simulées sans bruit avec le montage ``setup``.

    Retourne une liste de tuples (t_min, t_max, k_estimé, erreur relative).
    Permet de choisir la durée d'essai et la fenêtre d'analyse.
    """
    s = setup.with_(sensor="wire")
    t_end = max(t_starts) * ratio
    times = np.unique(np.concatenate([np.geomspace(0.2, t_end, 400)]))
    sim = simulate(s, times=times, max_dt=min(1.0, t_end / 400))
    out = []
    for t0 in t_starts:
        r = slope_method(times, sim.t_sensor, s.q_lin, t0, t0 * ratio)
        out.append((t0, t0 * ratio, r.k, r.k / s.k_powder - 1))
    return out
