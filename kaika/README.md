# Kaika 開花

Turn a piece of music into a video clip. A fluid simulation is *danced* by audio
analysis, then metamorphosed into living forms by a video diffusion model — all
driven from a local web app launched with a single command.

See `../project_ideas/kaika.md` for the full specification.

## Quickstart

```bash
uv venv && . .venv/bin/activate
uv pip install -e ".[dev]"
pytest                       # run the test suite
kaika --help                 # CLI
kaika run path/to/track.wav --recipe eclosion --seconds 4   # render a short clip
kaika serve                  # launch the local app (http://localhost:8400)
```

## Pipeline

| Stage | Module | In → Out |
| --- | --- | --- |
| E1 analyze   | `kaika.core.analyze`  | audio → `score.json` |
| E2 simulate  | `kaika.core.simulate` | score + recipe → fluid frames + velocity |
| E3 control   | `kaika.core.control`  | fluid → depth / canny / flow |
| E4 diffuse   | `kaika.core.diffuse`  | fluid + control → styled frames |
| E5 post      | `kaika.core.post`     | styled frames + audio → `final.mp4` |

Each stage reads and writes a run directory (`runs/<id>/`) and is independently
testable. E4 ships with a deterministic local stylizer fallback so the whole
pipeline runs end-to-end with no GPU; the ComfyUI / rented-GPU backend is a
drop-in replacement behind the same interface.
