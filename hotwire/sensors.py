"""Capteur de température PT100 et chaînes de mesure associées.

Ce module répond à deux questions :

1. Comment convertir une résistance PT100 en température (et inversement) ?
2. Quelle résolution peut-on espérer selon l'électronique utilisée
   (pont diviseur sur l'ADC 10 bits de l'Arduino, ou convertisseur MAX31865) ?
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Coefficients de Callendar–Van Dusen, norme IEC 60751 (valables pour T >= 0 °C ;
# le terme C n'intervient qu'en dessous de 0 °C et est négligé ici).
CVD_A = 3.9083e-3
CVD_B = -5.775e-7
PT100_R0 = 100.0

# Coefficient linéaire « historique » utilisé dans le tableur Protech.ods.
# La norme IEC 60751 donne alpha = 0.00385 /°C.
LEGACY_ALPHA = 0.00391


def pt100_resistance(temp_c, r0: float = PT100_R0):
    """Résistance (Ω) d'une PT100 à la température ``temp_c`` (°C), IEC 60751."""
    t = np.asarray(temp_c, dtype=float)
    return r0 * (1.0 + CVD_A * t + CVD_B * t * t)


def pt100_temperature(resistance, r0: float = PT100_R0):
    """Température (°C) d'une PT100 de résistance ``resistance`` (Ω).

    Inversion exacte du polynôme de Callendar–Van Dusen (T >= 0 °C).
    """
    r = np.asarray(resistance, dtype=float)
    return (-CVD_A + np.sqrt(CVD_A**2 - 4.0 * CVD_B * (1.0 - r / r0))) / (2.0 * CVD_B)


def pt100_temperature_linear(resistance, alpha: float = LEGACY_ALPHA, r0: float = PT100_R0):
    """Conversion linéaire T = (R/R0 - 1)/alpha, telle qu'utilisée dans le tableur."""
    r = np.asarray(resistance, dtype=float)
    return (r / r0 - 1.0) / alpha


# ---------------------------------------------------------------------------
# Chaînes de mesure
# ---------------------------------------------------------------------------


@dataclass
class DividerFrontEnd:
    """Pont diviseur alimenté sous ``vcc``, tension lue sur A0.

    * ``sensor_side="high"`` : Vcc — PT100 — A0 — R_ref — GND.  C'est la
      topologie du firmware d'origine (``R2 = R1 * (Vin/Vout - 1)``).
    * ``sensor_side="low"``  : Vcc — R_ref — A0 — PT100 — GND.  Indispensable
      avec la référence interne 1,1 V (la tension sur A0 reste < 1,1 V).

    ``vref`` est la référence de l'ADC : 5 V par défaut, ou 1,1 V avec
    ``analogReference(INTERNAL)``.
    """

    r_ref: float = 10_000.0
    vcc: float = 5.0
    vref: float = 5.0
    bits: int = 10
    oversampling: int = 1
    sensor_side: str = "high"

    @property
    def full_scale(self) -> int:
        return 2**self.bits

    def counts(self, resistance, noise_lsb: float = 0.0, rng: np.random.Generator | None = None):
        """Valeur ADC (éventuellement moyennée) pour une résistance donnée."""
        r = np.asarray(resistance, dtype=float)
        if self.sensor_side == "high":
            v = self.vcc * self.r_ref / (self.r_ref + r)
        else:
            v = self.vcc * r / (self.r_ref + r)
        ideal = v / self.vref * self.full_scale
        if self.oversampling <= 1 and noise_lsb == 0.0:
            return np.clip(np.floor(ideal), 0, self.full_scale - 1)
        rng = rng or np.random.default_rng()
        shape = (self.oversampling,) + np.shape(ideal)
        samples = np.floor(ideal + rng.normal(0.0, noise_lsb, size=shape))
        samples = np.clip(samples, 0, self.full_scale - 1)
        return samples.mean(axis=0)

    def resistance(self, counts):
        """Résistance reconstruite à partir de la valeur ADC (formule du firmware)."""
        c = np.asarray(counts, dtype=float)
        v = (c + 0.5) * self.vref / self.full_scale  # centre du pas de quantification
        if self.sensor_side == "high":
            return self.r_ref * (self.vcc / v - 1.0)
        return self.r_ref * v / (self.vcc - v)

    def resolution_ohm(self, resistance: float = 110.0) -> float:
        """Variation de résistance correspondant à 1 LSB, autour de ``resistance``.

        Avec ``oversampling = N`` (moyenne de N lectures en présence d'un bruit
        d'au moins 1 LSB), la résolution effective gagne environ un facteur √N.
        """
        dv_dr = self.vcc * self.r_ref / (self.r_ref + resistance) ** 2
        lsb = self.vref / self.full_scale
        return lsb / dv_dr / np.sqrt(max(self.oversampling, 1))

    def sensor_power_w(self, resistance: float = 110.0) -> float:
        """Puissance dissipée dans la PT100 (auto-échauffement)."""
        i = self.vcc / (self.r_ref + resistance)
        return i * i * resistance


@dataclass
class Max31865FrontEnd:
    """Convertisseur dédié MAX31865 (ADC 15 bits ratiométrique, R_ref = 430 Ω)."""

    r_ref: float = 430.0
    bits: int = 15

    def counts(self, resistance, noise_lsb: float = 0.5, rng: np.random.Generator | None = None):
        r = np.asarray(resistance, dtype=float)
        ideal = r / self.r_ref * 2**self.bits
        if noise_lsb:
            rng = rng or np.random.default_rng()
            ideal = ideal + rng.normal(0.0, noise_lsb, size=np.shape(ideal))
        return np.clip(np.floor(ideal), 0, 2**self.bits - 1)

    def resistance(self, counts):
        return np.asarray(counts, dtype=float) / 2**self.bits * self.r_ref

    def resolution_ohm(self, resistance: float = 110.0) -> float:
        return self.r_ref / 2**self.bits

    def sensor_power_w(self, resistance: float = 110.0) -> float:
        # Le MAX31865 polarise la sonde à ~ Vbias / (R_ref + R) avec Vbias ≈ 2 V.
        i = 2.0 / (self.r_ref + resistance)
        return i * i * resistance


def temperature_resolution(front_end, temp_c: float = 25.0) -> float:
    """Résolution en °C de la chaîne de mesure autour de ``temp_c``."""
    r = float(pt100_resistance(temp_c))
    dr_dt = PT100_R0 * (CVD_A + 2 * CVD_B * temp_c)
    return front_end.resolution_ohm(r) / dr_dt
