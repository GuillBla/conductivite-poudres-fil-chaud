"""Enregistrement des trames série en CSV (remplace le sketch Processing).

Différences avec ``legacy/RetrieveRandCreateCsv.pde`` :
* chaque trame est écrite et vidée sur le disque immédiatement (aucune perte
  si on interrompt l'acquisition) ;
* le temps enregistré est celui de l'Arduino (``millis()``), pas l'horloge du PC ;
* les lignes mal formées sont ignorées au lieu de corrompre le fichier ;
* fonctionne à l'identique avec l'Arduino virtuel (``--simulate``).
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

from .virtual import CSV_HEADER


def list_ports() -> list[str]:
    from serial.tools import list_ports as lp  # pyserial

    return [f"{p.device}  {p.description}" for p in lp.comports()]


def open_serial(port: str, baud: int = 115200, timeout: float = 5.0):
    try:
        import serial
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("pyserial est requis : pip install pyserial") from exc
    ser = serial.Serial(port, baud, timeout=timeout)
    # L'ouverture du port redémarre la plupart des cartes Arduino (signal DTR) :
    # on attend la fin du bootloader avant d'envoyer des commandes.
    time.sleep(2.5)
    ser.reset_input_buffer()
    return ser


def record(source, out_path: str | Path, start_heating: bool = True, max_lines: int | None = None,
           max_seconds: float | None = None, echo: bool = True, notes: str = "") -> int:
    """Lit ``source`` (port série ou :class:`~hotwire.virtual.VirtualArduino`)
    et écrit un CSV.  Retourne le nombre de trames enregistrées.

    ``start_heating`` envoie la commande ``S`` au firmware (ligne de base puis
    mise en chauffe automatique).  Ctrl+C arrête proprement l'enregistrement
    (et envoie ``X`` pour couper la chauffe).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_cols = len(CSV_HEADER.split(","))
    n = 0
    if start_heating:
        source.write(b"S\n")
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"# acquisition={dt.datetime.now().isoformat(timespec='seconds')} {notes}\n")
        header_written = False
        t_first = None
        try:
            while True:
                raw = source.readline()
                if not raw:
                    if getattr(source, "at_end", False):  # fin de l'Arduino virtuel
                        break
                    continue  # timeout série : on attend
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                if line.startswith("#"):
                    f.write(line + "\n")
                    if echo:
                        print(line)
                    continue
                if line == CSV_HEADER:
                    if not header_written:
                        f.write(line + "\n")
                        header_written = True
                    continue
                parts = line.split(",")
                if len(parts) != n_cols:
                    print(f"[ignorée] {line}", file=sys.stderr)
                    continue
                try:
                    values = [float(p) for p in parts]
                except ValueError:
                    print(f"[ignorée] {line}", file=sys.stderr)
                    continue
                if not header_written:
                    f.write(CSV_HEADER + "\n")
                    header_written = True
                f.write(line + "\n")
                f.flush()
                n += 1
                if echo:
                    t_s, heater, _, r, temp = values
                    print(f"t={t_s / 1000:8.1f} s  chauffe={int(heater)}  R={r:8.3f} Ω  T={temp:7.3f} °C")
                if max_lines and n >= max_lines:
                    break
                t_first = values[0] if t_first is None else t_first
                if max_seconds and (values[0] - t_first) / 1000 >= max_seconds:
                    break
        except KeyboardInterrupt:
            print("\nArrêt demandé.")
        finally:
            try:
                source.write(b"X\n")
            except Exception:
                pass
    return n
