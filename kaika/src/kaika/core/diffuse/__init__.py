"""E4 diffusion: pick a backend behind the stable E3->E4 interface."""
from __future__ import annotations

from ..recipe import Recipe
from .base import (Diffuser, DiffuseRequest, DiffuseResult, build_prompt_schedule,
                   compress_schedule, plan_chunks, section_boundary_frames)
from .local import LocalStylizer
from .comfy import ComfyDiffuser, ComfyUnavailable

__all__ = [
    "Diffuser", "DiffuseRequest", "DiffuseResult", "LocalStylizer",
    "ComfyDiffuser", "ComfyUnavailable", "get_diffuser", "build_prompt_schedule",
    "compress_schedule", "plan_chunks", "section_boundary_frames",
]


def get_diffuser(recipe: Recipe, **kwargs) -> Diffuser:
    backend = recipe.diffusion.backend
    if backend == "local":
        return LocalStylizer()
    if backend == "comfyui":
        return ComfyDiffuser(**kwargs)
    raise ValueError(f"unknown diffusion backend: {backend}")
