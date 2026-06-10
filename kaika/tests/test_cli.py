"""Phase 9: CLI surface + recipe discovery."""
from __future__ import annotations

from kaika.cli import build_parser
from kaika.core import recipe as R


def test_parser_has_commands():
    p = build_parser()
    ns = p.parse_args(["run", "x.wav", "--recipe", "eclosion", "--seconds", "5"])
    assert ns.cmd == "run" and ns.seconds == 5.0
    ns2 = p.parse_args(["serve", "--port", "9000"])
    assert ns2.cmd == "serve" and ns2.port == 9000


def test_recipes_dir_resolves():
    assert R.RECIPES_DIR.is_dir()
    assert (R.RECIPES_DIR / "eclosion.yaml").exists()
