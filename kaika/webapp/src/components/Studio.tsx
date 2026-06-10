import { useCallback, useEffect, useRef, useState } from "react";
import yaml from "js-yaml";
import { api, Analysis, ProjectDoc, RecipeEntry, Segment } from "../api";
import Waveform from "./Waveform";

interface Props {
  initialRunId?: string | null;       // reopen an existing project (Gallery)
  onPreview: (runId: string, jobId: string) => void;
}

const MIN_SEG_S = 0.4;

// read/write a nested value in a segment's partial fluid-override object
function setNested(obj: any, path: string[], value: any) {
  const next = structuredClone(obj || {});
  let o = next;
  for (let i = 0; i < path.length - 1; i++) o = o[path[i]] ??= {};
  o[path[path.length - 1]] = value;
  return next;
}
function getNested(obj: any, path: string[], fallback: number): number {
  let o = obj;
  for (const k of path) { if (o == null) return fallback; o = o[k]; }
  return o == null ? fallback : o;
}
function hasNested(obj: any, path: string[]): boolean {
  let o = obj;
  for (const k of path) { if (o == null || typeof o !== "object" || !(k in o)) return false; o = o[k]; }
  return o !== undefined;
}

// [label, path, default, min, max, step]
type Row = [string, string[], number, number, number, number];
const PRIMARY: Row[] = [
  ["Vorticity max", ["vorticity", "max"], 38, 5, 90, 1],
  ["Kick emit", ["splats", "low", "emit"], 0.22, 0, 0.6, 0.02],
  ["Hat emit", ["splats", "high", "emit"], 0.11, 0, 0.4, 0.01],
  ["Ambient stir", ["ambient_strength"], 1.6, 0, 6, 0.2],
];
const ADVANCED: Row[] = [
  ["Kick lifetime (s)", ["splats", "low", "lifetime_s"], 0.8, 0.2, 3, 0.1],
  ["Hat lifetime (s)", ["splats", "high", "lifetime_s"], 0.3, 0.1, 1.5, 0.05],
  ["Kick speed", ["splats", "low", "speed"], 1.3, 0, 4, 0.1],
  ["Hat speed", ["splats", "high", "speed"], 2.6, 0, 5, 0.1],
  ["Exposure", ["exposure"], 1.9, 0.5, 4, 0.1],
  ["Bloom", ["bloom"], 0.65, 0, 2, 0.05],
  ["Dissipation", ["dissipation"], 0.9, 0.8, 0.99, 0.01],
];

export default function Studio({ initialRunId, onPreview }: Props) {
  const [recipes, setRecipes] = useState<RecipeEntry[]>([]);
  const [recipeName, setRecipeName] = useState("eclosion");
  const [runId, setRunId] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDoc | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const [hover, setHover] = useState(false);
  const [err, setErr] = useState("");
  const [draft, setDraft] = useState(true);
  const [tab, setTab] = useState<"segment" | "recipe" | "yaml">("segment");
  const [yamlText, setYamlText] = useState("");
  const [yamlErr, setYamlErr] = useState("");
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const saveTimer = useRef<number | undefined>(undefined);

  useEffect(() => { api.recipes().then(setRecipes).catch(() => {}); }, []);

  const adopt = (p: Awaited<ReturnType<typeof api.getProject>>) => {
    setRunId(p.run_id);
    setProject(p.project);
    if (p.analysis) setAnalysis(p.analysis);
    setAudioUrl(p.audio_url ?? null);
    setSel(0);
  };

  useEffect(() => {
    if (initialRunId) {
      api.getProject(initialRunId).then(adopt).catch((e) => setErr(String(e.message || e)));
    }
  }, [initialRunId]);

  // playhead follows the audio element while playing
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const a = audioRef.current;
      if (a) setPlayhead(a.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  // debounced autosave of segment edits
  const scheduleSave = useCallback((segs: Segment[]) => {
    if (!runId) return;
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      api.updateProject(runId, { segments: segs }).catch(() => {});
    }, 700);
  }, [runId]);

  const setSegments = (segs: Segment[]) => {
    setProject((p) => (p ? { ...p, segments: segs } : p));
    scheduleSave(segs);
  };

  const upload = async (file: File) => {
    setErr(""); setBusy(true);
    try {
      const { audio_id } = await api.upload(file);
      adopt(await api.createProject({ audio_id, recipe_name: recipeName }));
    } catch (e: any) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  // ---- segment operations -------------------------------------------------
  const updateSegment = (patch: Partial<Segment>) => {
    if (!project) return;
    setSegments(project.segments.map((s, i) => (i === sel ? { ...s, ...patch } : s)));
  };
  const setFluid = (path: string[], value: number) =>
    updateSegment({ fluid: setNested(project!.segments[sel].fluid, path, value) });

  const moveBoundary = (b: number, t: number) => {
    if (!project) return;
    const segs = structuredClone(project.segments);
    const lo = segs[b - 1].start + MIN_SEG_S;
    const hi = segs[b].end - MIN_SEG_S;
    const tt = Math.max(lo, Math.min(hi, t));
    segs[b - 1].end = tt;
    segs[b].start = tt;
    setSegments(segs);
  };

  const splitAtPlayhead = () => {
    if (!project) return;
    const t = playhead;
    const i = project.segments.findIndex((s) => t > s.start + MIN_SEG_S && t < s.end - MIN_SEG_S);
    if (i < 0) return;
    const segs = structuredClone(project.segments);
    const s = segs[i];
    const right: Segment = { ...structuredClone(s), start: t };
    s.end = t;
    segs.splice(i + 1, 0, right);
    setSegments(segs);
    setSel(i + 1);
  };

  const mergeWithNext = () => {
    if (!project || sel >= project.segments.length - 1) return;
    const segs = structuredClone(project.segments);
    segs[sel].end = segs[sel + 1].end;
    segs.splice(sel + 1, 1);
    setSegments(segs);
  };

  // ---- recipe (global) ----------------------------------------------------
  const setRecipeField = (path: string[], value: any) => {
    if (!project || !runId) return;
    const rec = setNested(project.recipe, path, value);
    setProject({ ...project, recipe: rec });
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      api.updateProject(runId, { recipe: rec }).catch(() => {});
    }, 700);
  };

  const openYaml = () => {
    setYamlText(yaml.dump(project?.recipe ?? {}, { noRefs: true }));
    setYamlErr("");
    setTab("yaml");
  };
  const applyYaml = async () => {
    if (!project || !runId) return;
    try {
      const rec = yaml.load(yamlText) as any;
      setProject({ ...project, recipe: rec });
      await api.updateProject(runId, { recipe: rec });
      setYamlErr("");
      setTab("recipe");
    } catch (e: any) { setYamlErr(String(e.message || e)); }
  };

  // ---- actions ------------------------------------------------------------
  const flushSave = async () => {
    if (!runId || !project) return;
    window.clearTimeout(saveTimer.current);
    await api.updateProject(runId, { segments: project.segments, recipe: project.recipe });
  };
  const previewSegment = async () => {
    if (!runId) return;
    setBusy(true); setErr("");
    try {
      await flushSave();
      const { job_id } = await api.previewSegment(runId, sel, draft);
      onPreview(runId, job_id);
    } catch (e: any) { setErr(String(e.message || e)); setBusy(false); }
  };
  const previewFull = async () => {
    if (!runId) return;
    setBusy(true); setErr("");
    try {
      await flushSave();
      const { job_id } = await api.previewProject(runId, draft);
      onPreview(runId, job_id);
    } catch (e: any) { setErr(String(e.message || e)); setBusy(false); }
  };

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) { a.play(); setPlaying(true); }
    else { a.pause(); setPlaying(false); }
  };
  const seek = (t: number) => {
    const a = audioRef.current;
    if (a) a.currentTime = t;
    setPlayhead(t);
  };

  const resetSegment = () => updateSegment({ fluid: {} });

  const seg = project?.segments[sel];
  const nSeg = project?.segments.length ?? 0;
  const palette: string[] = project?.recipe?.fluid?.palette ?? [];

  const sliderRow = ([name, path, dflt, min, max, step]: Row) => {
    const ov = seg ? hasNested(seg.fluid, path) : false;
    return (
      <div key={name} className="slider-row">
        <label className={`field ${ov ? "ov" : ""}`}>
          {ov && <span className="ov-dot" title="overridden for this segment">●</span>}
          {name} <span className="val">{getNested(seg!.fluid, path, dflt)}</span>
        </label>
        <input type="range" min={min} max={max} step={step}
          value={getNested(seg!.fluid, path, dflt)}
          onChange={(e) => setFluid(path, parseFloat(e.target.value))} />
      </div>
    );
  };

  return (
    <div className="grid">
      <div>
        {!project && (
          <div className={`drop ${hover ? "hover" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setHover(true); }}
            onDragLeave={() => setHover(false)}
            onDrop={(e) => { e.preventDefault(); setHover(false); const f = e.dataTransfer.files[0]; if (f) upload(f); }}>
            <p style={{ fontSize: 18, marginBottom: 10 }}>Drop an audio file here</p>
            <p className="muted">analysis splits it into editable segments</p>
            <label className="btn ghost" style={{ display: "inline-block", width: "auto", marginTop: 12 }}>
              Choose file
              <input type="file" accept="audio/*" style={{ display: "none" }}
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
            <div style={{ marginTop: 18 }}>
              <label className="field" style={{ textAlign: "center" }}>Visual identity</label>
              <select value={recipeName} onChange={(e) => setRecipeName(e.target.value)}
                style={{ maxWidth: 240, margin: "0 auto" }}>
                {recipes.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
              </select>
            </div>
          </div>
        )}

        {project && analysis && (
          <div className="card">
            <div className="transport">
              <button className="play" onClick={togglePlay}>{playing ? "❚❚" : "▶"}</button>
              <span className="mono muted">{playhead.toFixed(1)}s / {analysis.duration_s.toFixed(1)}s</span>
              <span className="mono muted" style={{ marginLeft: "auto" }}>
                {analysis.tempo_bpm} BPM · {project.segments.length} segments
              </span>
            </div>
            {audioUrl && (
              <audio ref={audioRef} src={audioUrl} onEnded={() => setPlaying(false)} />
            )}
            <Waveform
              waveform={analysis.waveform}
              duration={analysis.duration_s}
              segments={project.segments}
              selected={sel}
              beats={(analysis.beats || []).map((b) => b.t)}
              onsets={{ low: analysis.onsets?.low ?? [], high: analysis.onsets?.high ?? [] }}
              playhead={playhead}
              onSelect={setSel}
              onSeek={seek}
              onMoveBoundary={moveBoundary}
            />
            <div className="seg-ops">
              <button className="btn ghost slim" onClick={splitAtPlayhead}>Split at playhead</button>
              <button className="btn ghost slim" onClick={mergeWithNext}
                disabled={!project || sel >= project.segments.length - 1}>
                Merge with next
              </button>
            </div>
          </div>
        )}
        {err && <p className="err">{err}</p>}
      </div>

      <aside>
        {project && (
          <div className="card inspector">
            <div className="insp-tabs">
              <button className={tab === "segment" ? "active" : ""} onClick={() => setTab("segment")}>Segment</button>
              <button className={tab === "recipe" ? "active" : ""} onClick={() => setTab("recipe")}>Recipe</button>
              <button className={tab === "yaml" ? "active" : ""} onClick={openYaml}>YAML</button>
            </div>

            <div className="insp-body">
              {tab === "segment" && seg && (
                <>
                  <div className="seg-nav">
                    <button disabled={sel === 0} onClick={() => setSel(sel - 1)}>‹</button>
                    <span className="mono">{sel + 1}/{nSeg} · {seg.start.toFixed(1)}–{seg.end.toFixed(1)}s</span>
                    <button disabled={sel >= nSeg - 1} onClick={() => setSel(sel + 1)}>›</button>
                  </div>

                  <label className="field">Label</label>
                  <input type="text" value={seg.label}
                    onChange={(e) => updateSegment({ label: e.target.value })} />

                  <label className="field">Prompt (diffusion)</label>
                  <textarea value={seg.prompt}
                    onChange={(e) => updateSegment({ prompt: e.target.value })} />

                  {PRIMARY.map(sliderRow)}

                  <details className="advanced">
                    <summary>More settings</summary>
                    {ADVANCED.map(sliderRow)}
                  </details>

                  <button className="btn ghost slim reset" onClick={resetSegment}>
                    Reset segment to recipe defaults
                  </button>
                </>
              )}

              {tab === "recipe" && (
                <>
                  <p className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                    Global defaults — segments inherit these unless overridden.
                  </p>
                  <label className="field">Seed</label>
                  <input type="number" value={project.recipe.seed ?? 0}
                    onChange={(e) => setRecipeField(["seed"], parseInt(e.target.value) || 0)} />

                  <label className="field">Palette</label>
                  <div className="palette-row">
                    {palette.map((c, i) => (
                      <input key={i} type="color" value={c}
                        onChange={(e) => {
                          const p = [...palette]; p[i] = e.target.value;
                          setRecipeField(["fluid", "palette"], p);
                        }} />
                    ))}
                    <button className="btn ghost slim" onClick={() =>
                      setRecipeField(["fluid", "palette"], [...palette, "#888888"])}>+</button>
                    {palette.length > 1 && (
                      <button className="btn ghost slim" onClick={() =>
                        setRecipeField(["fluid", "palette"], palette.slice(0, -1))}>−</button>
                    )}
                  </div>
                  <p className="muted" style={{ fontSize: 12 }}>
                    First colour = kicks; the rest cycle on hats.
                  </p>

                  <label className="field">
                    Denoise strength <span className="val">{project.recipe.diffusion?.strength ?? 0.5}</span>
                  </label>
                  <input type="range" min={0.1} max={0.9} step={0.05}
                    value={project.recipe.diffusion?.strength ?? 0.5}
                    onChange={(e) => setRecipeField(["diffusion", "strength"], parseFloat(e.target.value))} />
                </>
              )}

              {tab === "yaml" && (
                <>
                  <p className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                    Full recipe — total control. Apply to use it.
                  </p>
                  <textarea className="yaml" value={yamlText}
                    onChange={(e) => setYamlText(e.target.value)} spellCheck={false} />
                  {yamlErr && <p className="err">{yamlErr}</p>}
                  <button className="btn ghost" onClick={applyYaml}>Apply YAML</button>
                </>
              )}
            </div>

            <div className="insp-footer">
              <label className="check" title="Caps resolution for fast iteration; the final Generate always runs full quality.">
                <input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
                Draft quality (fast)
              </label>
              <button className="btn" disabled={busy || !runId} onClick={previewSegment}>
                {busy ? "Working…" : `Preview segment (${seg ? (seg.end - seg.start).toFixed(1) : "?"}s)`}
              </button>
              <button className="btn ghost" disabled={busy || !runId} onClick={previewFull}>
                Preview full track
              </button>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
