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

from .recipe import Recipe, FluidConfig, _merge, from_dict as recipe_from_dict
from .score import Score


def _deep_merge(base: dict, over: dict) -> dict:
    """Recursively overlay ``over`` onto ``base`` (override wins, None ignored)."""
    out = dict(base)
    for k, v in (over or {}).items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
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
        """One effective :class:`FluidConfig` per frame (base + segment override)."""
        base_d = asdict(self.recipe.fluid)
        cache: dict = {}

        def cfg_for(idx: int) -> FluidConfig:
            if idx not in cache:
                ov = self.segments[idx].fluid if self.segments else {}
                cache[idx] = _merge(FluidConfig(), _deep_merge(base_d, ov))
            return cache[idx]

        if not self.segments:
            return [self.recipe.fluid] * n_frames
        return [cfg_for(self._seg_index_for_frame(i)) for i in range(n_frames)]

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
