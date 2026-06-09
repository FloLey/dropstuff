"""Kaika command line.

The terminal starts the app; it never creates. ``kaika`` launches the local
app and opens the browser. ``kaika run`` is the second-citizen scripting entry
point — it calls the very same library the UI does.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cmd_run(args) -> int:
    from .core.pipeline import run_pipeline

    def progress(stage, done, total):
        bar = f"{done}/{total}" if total else ""
        print(f"\r[{stage:9}] {bar}    ", end="", flush=True)

    res = run_pipeline(args.audio, args.recipe, runs_root=args.out,
                       seconds=args.seconds, progress=progress)
    print()
    print(f"run {res.run_id} -> {res.final}")
    print(f"  frames={res.n_frames} backend={res.backend} "
          f"sync lag={res.sync_lag}f corr={res.sync_corr}")
    return 0


def _cmd_serve(args) -> int:
    from .server.app import serve
    serve(host=args.host, port=args.port, runs_root=args.out,
          open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kaika",
                                description="Turn music into a video clip.")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("run", help="render a clip (scripting/CI)")
    pr.add_argument("audio", help="path to an audio file")
    pr.add_argument("--recipe", default="eclosion", help="recipe name or path")
    pr.add_argument("--seconds", type=float, default=None,
                    help="render only the first N seconds (fast iteration)")
    pr.add_argument("--out", default="runs", help="runs root directory")
    pr.set_defaults(func=_cmd_run)

    ps = sub.add_parser("serve", help="launch the local app")
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=8400)
    ps.add_argument("--out", default="runs")
    ps.add_argument("--no-browser", action="store_true")
    ps.set_defaults(func=_cmd_serve)

    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        # bare `kaika` launches the app
        args = parser.parse_args(["serve"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
