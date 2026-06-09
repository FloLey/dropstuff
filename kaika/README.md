# Kaika 開花

Turn a piece of music into a video clip. A fluid simulation is *danced* by audio
analysis, then metamorphosed into living forms by a video diffusion model — all
driven from a local web app launched with a single command.

Full specification: [`../project_ideas/kaika.md`](../project_ideas/kaika.md).

```
SON ──▶ FLUIDE ──▶ FLORAISON
   du son, un fluide ; du fluide, une fleur
```

## Quickstart

```bash
uv venv && . .venv/bin/activate
uv pip install -e ".[dev]"

pytest                                   # the whole suite (no GPU needed)
kaika run path/to/track.wav --recipe eclosion --seconds 4   # render a 4s extract
kaika serve                              # launch the local app (http://localhost:8400)
kaika                                    # bare command = serve + open browser
```

`uvx kaika` works once published: the compiled frontend and the recipes ship
embedded in the wheel, so there is no npm at runtime and no config file to edit.

## The pipeline

Five stages in a chain, each with files on disk, each independently testable.

| Stage | Module | In → Out |
| --- | --- | --- |
| **E1** analyze   | `kaika.core.analyze`  | audio → `score.json` (frame-aligned partition) |
| **E2** simulate  | `kaika.core.simulate` | score + recipe → `fluid/*.png`, `velocity/*.npy`, `fluid_stats.json` |
| **E3** control   | `kaika.core.control`  | fluid → `control/{depth,canny,flow}/` |
| **E4** diffuse   | `kaika.core.diffuse`  | fluid + control → `styled/*.png` |
| **E5** post      | `kaika.core.post`     | styled + audio → `kaika_final.mp4` |

`kaika.core.pipeline.run_pipeline` orchestrates them into a reproducible
`runs/<id>/` directory (frozen recipe + score + every intermediate + manifest).

### Design notes

- **E2 is the movement skeleton**, not the final image: a deterministic NumPy
  stable-fluids solver (toroidal, Jos-Stam style). Same seed → identical video.
  (Taichi/GPU is a drop-in acceleration; NumPy keeps it runnable and testable
  everywhere.)
- **The E3→E4 boundary is the most important interface** — "control frames in,
  styled frames out". Everything model-specific lives behind `Diffuser`, so E4
  is replaceable when vid2vid models churn.
- **E4 has two backends.** `local` is a deterministic, GPU-free stylizer so the
  whole pipeline produces a clip on any machine (it is *not* the figurative
  metamorphosis — that needs the GPU). `comfyui` drives ComfyUI / Wan 2.2 on a
  rented GPU: chunking with section-aligned seams, a prompt schedule from the
  score, near-lossless **video** transfer (never thousands of PNGs), and a
  versioned workflow template (`diffuse/workflows/`). Provisioning scaffold in
  `diffuse/provision.py`.
- **Sync check** (E5) correlates the audio RMS envelope with the fluid's
  kinetic energy — deterministically audio-driven — not styled-frame luminance.

## The app

`kaika serve` runs FastAPI + a single-worker job queue + SQLite + WebSocket
progress, and serves the React/Vite/TS frontend. Three screens:

1. **Studio** — drop audio, see the annotated waveform (beats/onsets/sections),
   edit the recipe (sliders + prompts), drag-select an extract, render.
2. **Render** — the five stages live, with progress and the result player.
3. **Gallery** — every run, replayable, with its frozen recipe and sync info.

Nothing the UI shows is hidden state: runs live on disk under `runs/`.

## Developing the frontend

The built frontend is committed under `src/kaika/webapp_dist/`. To change it:

```bash
cd webapp
npm install
npm run dev      # http://localhost:5173, proxies /api + /ws to :8400 (run `kaika serve` too)
npm run build    # re-emits into ../src/kaika/webapp_dist
```

## Layout

```
kaika/
├── recipes/                 # YAML visual identities (eclosion, encre)
├── src/kaika/
│   ├── core/                # E1–E5 library + pipeline (UI and CLI both call this)
│   │   ├── analyze.py  simulate.py  control.py  post.py  pipeline.py
│   │   ├── recipe.py  score.py  media.py
│   │   └── diffuse/         # E4: base, local, comfy, provision, workflows/
│   ├── server/              # FastAPI app, job queue, SQLite
│   ├── webapp_dist/         # built frontend (embedded)
│   └── cli.py               # `kaika` (serve) · `kaika run …` (scripting)
├── webapp/                  # React/Vite/TS sources
├── tests/                   # pytest, one module per stage + server + e2e
└── runs/                    # one dir per render (gitignored)
```

## Sandbox honesty

Everything in this repo runs and is tested with **no GPU** (`pytest` is green
end-to-end). The figurative flower metamorphosis requires the `comfyui` backend
on a rented NVIDIA GPU; that code path is structured, unit-tested offline, and
gated behind a reachable ComfyUI endpoint, but is not exercised here.
