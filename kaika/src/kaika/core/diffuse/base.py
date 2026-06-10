"""E4 interface + shared scheduling logic.

The E3->E4 boundary ("control frames in, styled frames out") is the most
important interface in the project: vid2vid models churn every few months, so
everything model-specific lives behind :class:`Diffuser`. The chunk planning
and prompt scheduling here are model-agnostic and fully testable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..score import Score
from ..recipe import Recipe

ProgressFn = Callable[[int, int], None]


@dataclass
class DiffuseRequest:
    fluid_dir: Path
    control_dirs: Dict[str, Path]      # signal name -> dir
    out_dir: Path                      # styled frames written to out_dir/styled
    score: Score
    recipe: Recipe
    n_frames: int
    prompts: Optional[List[str]] = None   # per-frame prompts (per-segment); overrides recipe


@dataclass
class DiffuseResult:
    styled_dir: Path
    n_frames: int
    backend: str


class Diffuser(ABC):
    name = "base"

    @abstractmethod
    def run(self, req: DiffuseRequest,
            progress: Optional[ProgressFn] = None) -> DiffuseResult:
        ...


def section_for_time(score: Score, t: float) -> str:
    for s in score.sections:
        if s.start <= t < s.end:
            return s.label
    return score.sections[-1].label if score.sections else "default"


def build_prompt_schedule(score: Score, recipe: Recipe,
                          n_frames: int) -> List[str]:
    """One effective prompt per frame (base prefixed, default fallback)."""
    fps = score.audio.fps
    return [recipe.prompt_for(section_for_time(score, i / fps))
            for i in range(n_frames)]


def compress_schedule(per_frame: List[str]) -> List[Tuple[int, str]]:
    """Collapse a per-frame prompt list to (start_frame, prompt) change points."""
    out: List[Tuple[int, str]] = []
    last = None
    for i, p in enumerate(per_frame):
        if p != last:
            out.append((i, p))
            last = p
    return out


def plan_chunks(n_frames: int, chunk_frames: int, overlap: int,
                boundaries: Optional[List[int]] = None) -> List[Tuple[int, int]]:
    """Split [0, n_frames) into overlapping chunks, snapping cuts toward
    musical section boundaries so seams hide on transitions."""
    chunk_frames = max(2, chunk_frames)
    overlap = max(0, min(overlap, chunk_frames - 1))
    bset = sorted(set(boundaries or []))
    chunks: List[Tuple[int, int]] = []
    start = 0
    while start < n_frames:
        end = min(n_frames, start + chunk_frames)
        if end < n_frames and bset:
            window = overlap or chunk_frames // 4
            near = [b for b in bset if abs(b - end) <= window
                    and b > start + overlap and b < n_frames]
            if near:
                end = min(near, key=lambda b: abs(b - end))
        chunks.append((start, end))
        if end >= n_frames:
            break
        start = max(start + 1, end - overlap)
    return chunks


def section_boundary_frames(score: Score, n_frames: int) -> List[int]:
    fps = score.audio.fps
    fr = sorted({int(round(s.start * fps)) for s in score.sections})
    return [f for f in fr if 0 < f < n_frames]
