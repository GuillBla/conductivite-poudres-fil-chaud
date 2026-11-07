"""« Arduino virtuel » : émule le firmware ``firmware/hotwire_logger`` sans matériel.

La température vraie au capteur est calculée par le simulateur physique,
convertie en résistance PT100, puis en valeur ADC par la chaîne de mesure
choisie (quantification + bruit), et enfin reconvertie exactement comme le
ferait le firmware.  Les trames produites ont le même format que celles
du vrai Arduino : on peut donc tester toute la chaîne d'acquisition et
d'analyse sur un PC.

L'objet expose ``readline()`` / ``write()`` comme ``serial.Serial`` (pyserial),
ce qui permet de le substituer au port série dans :mod:`hotwire.acquisition`.
"""

from __future__ import annotations

import time

import numpy as np

from .model import Setup, simulate
from .sensors import DividerFrontEnd, Max31865FrontEnd, pt100_resistance, pt100_temperature

FIRMWARE_VERSION = "2.0"
CSV_HEADER = "time_ms,heater,raw,resistance_ohm,temperature_c"


def make_front_end(name: str):
    """Chaînes de mesure prédéfinies (cf. docs/materiel.md)."""
    name = name.lower()
    if name == "max31865":
        return Max31865FrontEnd()
    if name == "divider-legacy":   # montage d'origine : 10 kΩ, référence 5 V
        return DividerFrontEnd(r_ref=10_000, vref=5.0, oversampling=1)
    if name == "divider":          # pont amélioré : 1 kΩ, référence interne 1,1 V, 64 lectures
        return DividerFrontEnd(r_ref=1_000, vref=1.1, oversampling=64, sensor_side="low")
    raise ValueError(f"Chaîne de mesure inconnue : {name}")


class VirtualArduino:
    """Émule le firmware : ligne d'en-tête, ligne de colonnes, puis une trame
    toutes les ``period_s`` secondes (simulées).

    Séquence : ``baseline_s`` secondes sans chauffe, puis chauffe pendant
    ``heat_s`` secondes, puis refroidissement jusqu'à ``total_s``.
    ``speed`` : facteur d'accélération du temps (``None`` = aussi vite que possible).
    """

    def __init__(self, setup: Setup, front_end: str = "max31865", period_s: float = 10.0,
                 baseline_s: float = 60.0, heat_s: float = 3600.0, total_s: float | None = None,
                 noise_lsb: float = 0.7, speed: float | None = None, seed: int | None = 0):
        self.setup = setup
        self.front_end_name = front_end
        self.fe = make_front_end(front_end)
        self.period_s = period_s
        self.baseline_s = baseline_s
        self.heat_s = heat_s
        self.total_s = baseline_s + heat_s if total_s is None else total_s
        self.noise_lsb = noise_lsb
        self.speed = speed
        self.rng = np.random.default_rng(seed)
        self._lines = self._generate()
        self._index = 0
        self._t_start = None

    # --- pré-calcul de la physique -------------------------------------
    def _generate(self):
        s = self.setup
        t_abs = np.arange(0.0, self.total_s + 1e-9, self.period_s)
        t_heat = t_abs - self.baseline_s
        heated = t_heat >= 0
        sim = simulate(s, times=t_heat[heated], heater_off_at=self.heat_s)
        temp_true = np.full_like(t_abs, s.t_ambient)
        temp_true[heated] = sim.t_sensor
        r_true = pt100_resistance(temp_true)
        raw = self.fe.counts(r_true, noise_lsb=self.noise_lsb, rng=self.rng)
        r_meas = self.fe.resistance(raw)
        temp_meas = pt100_temperature(r_meas)
        heater = heated & (t_heat < self.heat_s)

        lines = [
            f"# hotwire_logger v{FIRMWARE_VERSION} frontend={self.front_end_name} "
            f"period_ms={int(self.period_s * 1000)} simulated=1",
            CSV_HEADER,
        ]
        for i in range(len(t_abs)):
            lines.append(
                f"{int(round(t_abs[i] * 1000))},{int(heater[i])},{raw[i]:.2f},{r_meas[i]:.3f},{temp_meas[i]:.3f}"
            )
        self._times = np.concatenate([[0.0, 0.0], t_abs])
        return lines

    # --- interface type pyserial ----------------------------------------
    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = self.readline()
        if not line:
            raise StopIteration
        return line.decode().rstrip("\n")

    @property
    def at_end(self) -> bool:
        return self._index >= len(self._lines)

    def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        if self.speed:
            if self._t_start is None:
                self._t_start = time.monotonic()
            due = self._t_start + self._times[self._index] / self.speed
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        line = self._lines[self._index]
        self._index += 1
        return (line + "\n").encode()

    def write(self, data: bytes) -> int:  # commandes ignorées (séquence pré-programmée)
        return len(data)

    def reset_input_buffer(self):
        pass

    def close(self):
        pass
