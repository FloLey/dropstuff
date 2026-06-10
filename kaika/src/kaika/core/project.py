"""Project model — the mutable working document the editor drives.

A run is a one-shot immutable artifact; a Project is the thing you *edit*: an
audio track split into segments (seeded from the analysis, then reworkable),
each segment carrying its own prompt and partial fluid-parameter overrides.
A single continuous simulation reads these per-frame, so parameters vary by
segment without breaking the flow. Persisted as ``project.json`` (no hidden
state).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from .recipe import (Recipe, FluidConfig, _build, _deep_merge,
                     from_dict as recipe_from_dict)
from .score import Score

# Parameters glide across segment boundaries over this window instead of
# jumping — a hard cut in vorticity/exposure reads as a glitch in the fluid.
SMOOTH_S = 0.6


def _lerp_cfg(a: dict, b: dict, w: float) -> dict:
    """Numeric-field interpolation between two config dicts (w: 0=a, 1=b).

    Ints stay ints (counts), non-numeric fields switch at the midpoint."""
    out = {}
    for k, va in a.items():
        vb = b.get(k, va)
        both_num = (isinstance(va, (int, float)) and isinstance(vb, (int, float))
                    and not isinstance(va, bool) and not isinstance(vb, bool))
        if both_num:
            mixed = va + (vb - va) * w
            out[k] = int(round(mixed)) if isinstance(va, int) and isinstance(vb, int) else mixed
        elif isinstance(va, dict) and isinstance(vb, dict):
            out[k] = _lerp_cfg(va, vb, w)
        else:
            out[k] = va if w < 0.5 else vb
    return out


@dataclass
class Segment:
    start: float
    end: float
    label: str
    prompt: str = ""                       # full effective prompt for this segment
    fluid: dict = field(default_factory=dict)   # partial fluid overrides


@dataclass
class Project:
    audio: str                             # audio id / filename under the run
    recipe: Recipe
    segments: List[Segment]
    fps: int = 24
    seconds: Optional[float] = None        # optional render-length cap

    # ---- construction ------------------------------------------------------
    @staticmethod
    def from_score(score: Score, recipe: Recipe, audio: str) -> "Project":
        segs = [Segment(start=s.start, end=s.end, label=s.label,
                        prompt=recipe.prompt_for(s.label), fluid={})
                for s in score.sections]
        return Project(audio=audio, recipe=recipe, segments=segs,
                       fps=score.audio.fps)

    # ---- per-frame resolution ---------------------------------------------
    def _seg_index_for_frame(self, i: int) -> int:
        t = i / self.fps
        for idx, s in enumerate(self.segments):
            if s.start <= t < s.end:
                return idx
        return len(self.segments) - 1 if self.segments else 0

    def frame_configs(self, n_frames: int) -> List[FluidConfig]:
        """One effective :class:`FluidConfig` per frame (base + segment override),
        with numeric parameters smoothed across boundaries over ``SMOOTH_S``."""
        if not self.segments:
            return [self.recipe.fluid] * n_frames
        base_d = asdict(self.recipe.fluid)
        seg_dicts = [_deep_merge(base_d, s.fluid or {}) for s in self.segments]
        seg_cfgs = [_build(FluidConfig, d) for d in seg_dicts]

        half = SMOOTH_S / 2.0
        out: List[FluidConfig] = []
        for i in range(n_frames):
            t = i / self.fps
            idx = self._seg_index_for_frame(i)
            cfg = seg_cfgs[idx]
            # blend into the neighbour when inside the smoothing window
            if idx + 1 < len(self.segments):
                tb = self.segments[idx].end
                if t > tb - half:
                    w = (t - (tb - half)) / SMOOTH_S          # 0 .. 0.5 at boundary
                    cfg = _build(FluidConfig,
                                 _lerp_cfg(seg_dicts[idx], seg_dicts[idx + 1], w))
            if idx > 0:
                tb = self.segments[idx].start
                if t < tb + half:
                    w = (t - (tb - half)) / SMOOTH_S          # 0.5 .. 1 after boundary
                    cfg = _build(FluidConfig,
                                 _lerp_cfg(seg_dicts[idx - 1], seg_dicts[idx], w))
            out.append(cfg)
        return out

    def prompt_schedule(self, n_frames: int) -> List[str]:
        if not self.segments:
            return [self.recipe.prompt_for("default")] * n_frames
        return [self.segments[self._seg_index_for_frame(i)].prompt
                for i in range(n_frames)]

    # ---- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict:
        return {"audio": self.audio, "fps": self.fps, "seconds": self.seconds,
                "recipe": self.recipe.to_dict(),
                "segments": [asdict(s) for s in self.segments]}

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @staticmethod
    def from_dict(d: dict) -> "Project":
        return Project(
            audio=d["audio"],
            recipe=recipe_from_dict(d.get("recipe") or {}),
            segments=[Segment(**s) for s in d.get("segments", [])],
            fps=int(d.get("fps", 24)),
            seconds=d.get("seconds"),
        )

    @staticmethod
    def from_json(path: str | Path) -> "Project":
        return Project.from_dict(json.loads(Path(path).read_text()))
