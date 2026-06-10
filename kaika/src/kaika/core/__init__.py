"""Kaika core library (E1–E5 + orchestration).

The UI and the CLI both call this package. Common entry points are re-exported
here so callers can ``from kaika.core import run_pipeline, Project, load_recipe``.
"""
from .recipe import Recipe, load_recipe, from_dict as recipe_from_dict
from .score import Score
from .project import Project, Segment
from .analyze import analyze
from .pipeline import (run_pipeline, run_fluid, run_diffuse, init_project_run,
                       load_run, list_runs, RunResult)

__all__ = [
    "Recipe", "load_recipe", "recipe_from_dict", "Score", "Project", "Segment",
    "analyze", "run_pipeline", "run_fluid", "run_diffuse", "init_project_run",
    "load_run", "list_runs", "RunResult",
]
