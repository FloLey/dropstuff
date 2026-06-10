"""Phase 2: recipe loading, defaults, and prompt resolution."""
from __future__ import annotations

from kaika.core import recipe as R


def test_load_named_recipe():
    r = R.load_recipe("eclosion")
    assert r.name == "eclosion"
    assert r.seed == 4217
    assert r.fluid.splats["low"].placement == "anchored"
    assert r.diffusion.strength == 0.5


def test_prompt_base_is_prefixed():
    r = R.load_recipe("eclosion")
    p = r.prompt_for("drop")
    assert p.startswith(r.prompts["base"])
    assert "peonies" in p


def test_unknown_label_falls_back_to_default():
    r = R.load_recipe("eclosion")
    p = r.prompt_for("chorus")  # not defined
    assert r.prompts["default"] in p


def test_partial_dict_uses_defaults():
    r = R.from_dict({"name": "tiny", "fluid": {"resolution": 32}})
    assert r.name == "tiny"
    assert r.fluid.resolution == 32
    assert r.fluid.dissipation == R.FluidConfig().dissipation  # default kept
    assert r.diffusion.backend == "local"


def test_yaml_roundtrip(tmp_path):
    r = R.load_recipe("eclosion")
    p = tmp_path / "r.yaml"
    r.to_yaml(p)
    again = R.load_recipe(p)
    assert again.seed == r.seed
    assert again.prompt_for("drop") == r.prompt_for("drop")
