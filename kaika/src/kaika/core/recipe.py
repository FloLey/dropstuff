"""Recipe model — the creative lever.

A recipe is a YAML file that fully defines the visual identity of a render:
audio->fluid mapping, palette, per-section prompts, diffusion parameters.
One track + two recipes = two radically different clips.

All fields have defaults so a partial YAML is valid; unknown section labels
fall back to ``prompts.default`` and ``base`` is always prefixed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields, is_dataclass
from pathlib import Path
from typing import Dict, List, get_type_hints, get_origin, get_args

import os

import yaml


def _find_recipes_dir() -> Path:
    """Locate recipes for both editable (repo) and wheel (packaged) installs."""
    env = os.environ.get("KAIKA_RECIPES")
    candidates = [Path(env)] if env else []
    pkg = Path(__file__).resolve().parents[1]          # .../kaika
    candidates += [pkg / "recipes",                    # packaged (wheel)
                   Path(__file__).resolve().parents[3] / "recipes"]  # repo (dev)
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[-1]


RECIPES_DIR = _find_recipes_dir()


@dataclass
class Splat:
    radius: float = 0.08
    force: float = 6000.0
    placement: str = "scatter"      # "anchored" | "scatter"
    max_per_beat: int = 4
    lifetime_s: float = 0.5         # how long a spawned source lives, then dies
    emit: float = 0.2               # peak dye emission while alive
    drift: float = 0.4              # how strongly the source is carried by the flow
    speed: float = 1.5              # self-propulsion along its direction (cells/frame)


@dataclass
class Vorticity:
    min: float = 8.0
    max: float = 38.0
    driver: str = "rms"


@dataclass
class FluidConfig:
    resolution: int = 256           # simulation grid (square)
    render_resolution: int = 512    # output frame size
    dissipation: float = 0.90       # density decay: dye clears ~1s after a source dies
    velocity_dissipation: float = 0.96   # velocity decay per step (bounds energy)
    viscosity: float = 0.0
    lookahead_s: float = 8.0
    splats: Dict[str, Splat] = field(default_factory=lambda: {
        "low": Splat(radius=0.10, force=9000.0, placement="anchored",
                     lifetime_s=0.8, emit=0.22, drift=0.7, speed=1.3),
        "high": Splat(radius=0.03, force=3500.0, placement="scatter",
                      max_per_beat=5, lifetime_s=0.3, emit=0.11, drift=0.3, speed=2.6),
    })
    vorticity: Vorticity = field(default_factory=Vorticity)
    # Gentle, RMS-driven ambient stirring so calm passages drift and loud ones
    # churn (the fluid "stretches" when quiet). Colour is NOT injected here.
    ambient_strength: float = 1.6       # curl-noise stirring amplitude (cells/frame)
    ambient_scale: float = 2.6          # spatial frequency of the noise
    ambient_speed: float = 0.16         # temporal evolution per frame
    # Rendering (HDR -> filmic), so the frame is beautiful on its own.
    exposure: float = 1.9
    bloom: float = 0.65
    background: float = 0.04
    palette: List[str] = field(default_factory=lambda: [
        "#B84A74", "#34808A", "#E0A458", "#6C4A8C", "#3FA39B", "#D98A5E"])


@dataclass
class DiffusionConfig:
    model: str = "wan-2.2-vace"
    backend: str = "local"          # "local" (no-GPU fallback) | "comfyui"
    strength: float = 0.5
    control: List[str] = field(default_factory=lambda: ["depth", "flow"])
    chunk_s: float = 5.0
    overlap_frames: int = 24


@dataclass
class PostConfig:
    fps: int = 24
    upscale: bool = False
    interpolate: bool = False
    aspect: str = "square"          # "square" | "wide"


@dataclass
class Recipe:
    name: str = "default"
    seed: int = 0
    fluid: FluidConfig = field(default_factory=FluidConfig)
    diffusion: DiffusionConfig = field(default_factory=DiffusionConfig)
    post: PostConfig = field(default_factory=PostConfig)
    prompts: Dict[str, str] = field(default_factory=lambda: {
        "base": "abstract organic motion, soft light",
        "default": "botanical organic forms, abstract motion",
    })

    def prompt_for(self, label: str) -> str:
        """Effective prompt for a section: ``base`` is always prefixed; an
        unknown label falls back to ``default``."""
        base = self.prompts.get("base", "").strip()
        body = self.prompts.get(label) or self.prompts.get("default", "")
        return f"{base}, {body}".strip(", ").strip() if base else body

    def to_dict(self) -> dict:
        return asdict(self)

    def to_yaml(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(self.to_dict(), sort_keys=False,
                                              allow_unicode=True))


def _deep_merge(base: dict, over: dict) -> dict:
    """Recursively overlay ``over`` onto ``base`` (override wins; None skipped)."""
    out = dict(base)
    for k, v in (over or {}).items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _coerce(ftype, val):
    """Rebuild nested dataclasses / dicts-of-dataclasses from plain data."""
    if is_dataclass(ftype) and isinstance(val, dict):
        return _build(ftype, val)
    if get_origin(ftype) is dict and isinstance(val, dict):
        args = get_args(ftype)
        if len(args) == 2 and is_dataclass(args[1]):
            return {k: (_build(args[1], v) if isinstance(v, dict) else v)
                    for k, v in val.items()}
    return val


def _build(cls, data: dict):
    """Generic dataclass builder: recurse into any nested dataclass field.

    Adding a new nested config requires no change here — type hints drive it.
    Expects ``data`` to be a full dict (use ``_deep_merge`` onto defaults first).
    """
    hints = get_type_hints(cls)
    kwargs = {f.name: _coerce(hints.get(f.name, object), data[f.name])
              for f in fields(cls) if f.name in data and data[f.name] is not None}
    return cls(**kwargs)


def _merge(default, data):
    """Overlay ``data`` onto a default dataclass instance (deep), rebuilding it."""
    return _build(type(default), _deep_merge(asdict(default), data or {}))


def from_dict(d: dict) -> Recipe:
    return _build(Recipe, _deep_merge(asdict(Recipe()), d or {}))


def load_recipe(name_or_path: str | Path) -> Recipe:
    """Load a recipe by file path or by bare name (looked up in ``recipes/``)."""
    p = Path(name_or_path)
    if not p.exists() and p.suffix == "":
        p = RECIPES_DIR / f"{name_or_path}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"recipe not found: {name_or_path}")
    return from_dict(yaml.safe_load(p.read_text()))
