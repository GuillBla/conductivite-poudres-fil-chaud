"""Chargement de la description du montage depuis un fichier TOML."""

from __future__ import annotations

import tomllib
from dataclasses import fields
from pathlib import Path

from .model import Setup

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "montage.toml"


def load_setup(path: str | Path | None = None, **overrides) -> Setup:
    """Construit un :class:`Setup` à partir d'un TOML (sections libres, clés =
    champs de Setup), puis applique ``overrides`` (valeurs non ``None``)."""
    values = {}
    p = Path(path) if path else DEFAULT_CONFIG
    if p.exists():
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        for section in data.values():
            if isinstance(section, dict):
                values.update(section)
    valid = {f.name for f in fields(Setup)}
    unknown = set(values) - valid
    if unknown:
        raise ValueError(f"Clés inconnues dans {p} : {sorted(unknown)}")
    values.update({k: v for k, v in overrides.items() if v is not None})
    return Setup(**values)
