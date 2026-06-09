"""Recipe model — the creative lever.

A recipe is a YAML file that fully defines the visual identity of a render:
audio->fluid mapping, palette, per-section prompts, diffusion parameters.
One track + two recipes = two radically different clips.

All fields have defaults so a partial YAML is valid; unknown section labels
fall back to ``prompts.default`` and ``base`` is always prefixed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List

import yaml

RECIPES_DIR = Path(__file__).resolve().parents[3] / "recipes"


@dataclass
class Splat:
    radius: float = 0.08
    force: float = 6000.0
    placement: str = "scatter"      # "anchored" | "scatter"
    max_per_beat: int = 4


@dataclass
class Vorticity:
    min: float = 8.0
    max: float = 38.0
    driver: str = "rms"


@dataclass
class FluidConfig:
    resolution: int = 256           # simulation grid (square)
    render_resolution: int = 512    # output frame size
    dissipation: float = 0.99       # density decay per step
    viscosity: float = 0.0
    lookahead_s: float = 8.0
    splats: Dict[str, Splat] = field(default_factory=lambda: {
        "low": Splat(radius=0.12, force=9000.0, placement="anchored"),
        "high": Splat(radius=0.03, force=3500.0, placement="scatter", max_per_beat=5),
    })
    vorticity: Vorticity = field(default_factory=Vorticity)


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


def _merge(default, data):
    """Build a dataclass instance from defaults overlaid with a dict."""
    if data is None:
        return default
    kwargs = {}
    for f in default.__dataclass_fields__.values():
        cur = getattr(default, f.name)
        if f.name in data:
            val = data[f.name]
            if f.name == "splats" and isinstance(val, dict):
                kwargs[f.name] = {k: Splat(**v) for k, v in val.items()}
            elif f.name == "vorticity" and isinstance(val, dict):
                kwargs[f.name] = Vorticity(**val)
            else:
                kwargs[f.name] = val
        else:
            kwargs[f.name] = cur
    return type(default)(**kwargs)


def from_dict(d: dict) -> Recipe:
    d = dict(d or {})
    r = Recipe()
    return Recipe(
        name=d.get("name", r.name),
        seed=int(d.get("seed", r.seed)),
        fluid=_merge(FluidConfig(), d.get("fluid")),
        diffusion=_merge(DiffusionConfig(), d.get("diffusion")),
        post=_merge(PostConfig(), d.get("post")),
        prompts={**r.prompts, **(d.get("prompts") or {})},
    )


def load_recipe(name_or_path: str | Path) -> Recipe:
    """Load a recipe by file path or by bare name (looked up in ``recipes/``)."""
    p = Path(name_or_path)
    if not p.exists() and p.suffix == "":
        p = RECIPES_DIR / f"{name_or_path}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"recipe not found: {name_or_path}")
    return from_dict(yaml.safe_load(p.read_text()))
