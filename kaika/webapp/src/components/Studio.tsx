import { useEffect, useState } from "react";
import { api, Analysis, ProjectDoc, RecipeEntry, Segment } from "../api";
import Waveform from "./Waveform";

interface Props {
  onPreview: (runId: string, jobId: string) => void;
}

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

export default function Studio({ onPreview }: Props) {
  const [recipes, setRecipes] = useState<RecipeEntry[]>([]);
  const [recipeName, setRecipeName] = useState("eclosion");
  const [runId, setRunId] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDoc | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const [hover, setHover] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { api.recipes().then((r) => setRecipes(r)).catch(() => {}); }, []);

  const upload = async (file: File) => {
    setErr(""); setBusy(true);
    try {
      const { audio_id } = await api.upload(file);
      const payload = await api.createProject({ audio_id, recipe_name: recipeName });
      setRunId(payload.run_id);
      setProject(payload.project);
      setAnalysis(payload.analysis || null);
      setSel(0);
    } catch (e: any) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const updateSegment = (patch: Partial<Segment>) => {
    setProject((p) => {
      if (!p) return p;
      const segs = p.segments.map((s, i) => (i === sel ? { ...s, ...patch } : s));
      return { ...p, segments: segs };
    });
  };
  const setFluid = (path: string[], value: number) =>
    updateSegment({ fluid: setNested(project!.segments[sel].fluid, path, value) });

  const preview = async () => {
    if (!runId || !project) return;
    setBusy(true); setErr("");
    try {
      await api.updateProject(runId, { segments: project.segments });
      const { job_id } = await api.previewProject(runId);
      onPreview(runId, job_id);
    } catch (e: any) { setErr(String(e.message || e)); setBusy(false); }
  };

  const seg = project?.segments[sel];

  return (
    <div className="grid">
      <div>
        {!project && (
          <div
            className={`drop ${hover ? "hover" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setHover(true); }}
            onDragLeave={() => setHover(false)}
            onDrop={(e) => { e.preventDefault(); setHover(false); const f = e.dataTransfer.files[0]; if (f) upload(f); }}
          >
            <p style={{ fontSize: 18, marginBottom: 10 }}>Drop an audio file here</p>
            <p className="muted">analysis splits it into editable segments</p>
            <label className="btn ghost" style={{ display: "inline-block", width: "auto", marginTop: 12 }}>
              Choose file
              <input type="file" accept="audio/*" style={{ display: "none" }}
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
            <div style={{ marginTop: 16 }}>
              <select value={recipeName} onChange={(e) => setRecipeName(e.target.value)}>
                {recipes.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
              </select>
            </div>
          </div>
        )}

        {project && analysis && (
          <div className="card">
            <p className="muted mono" style={{ marginBottom: 12 }}>
              {analysis.tempo_bpm} BPM · {analysis.duration_s.toFixed(1)}s · {analysis.n_frames} frames ·{" "}
              {project.segments.length} segments
            </p>
            <Waveform
              waveform={analysis.waveform}
              duration={analysis.duration_s}
              segments={project.segments}
              selected={sel}
              onSelect={setSel}
            />
          </div>
        )}
        {err && <p className="err">{err}</p>}
      </div>

      <aside>
        {seg && (
          <div className="card">
            <h3>Segment · {seg.label}</h3>
            <p className="muted mono" style={{ marginBottom: 10 }}>
              {seg.start.toFixed(1)}s – {seg.end.toFixed(1)}s
            </p>

            <label className="field">Prompt (diffusion)</label>
            <textarea value={seg.prompt}
              onChange={(e) => updateSegment({ prompt: e.target.value })} />

            <label className="field">
              Vorticity max <span className="val">{getNested(seg.fluid, ["vorticity", "max"], 38)}</span>
            </label>
            <input type="range" min={5} max={90} step={1}
              value={getNested(seg.fluid, ["vorticity", "max"], 38)}
              onChange={(e) => setFluid(["vorticity", "max"], parseInt(e.target.value))} />

            <label className="field">
              Kick emit <span className="val">{getNested(seg.fluid, ["splats", "low", "emit"], 0.22)}</span>
            </label>
            <input type="range" min={0} max={0.6} step={0.02}
              value={getNested(seg.fluid, ["splats", "low", "emit"], 0.22)}
              onChange={(e) => setFluid(["splats", "low", "emit"], parseFloat(e.target.value))} />

            <label className="field">
              Hat emit <span className="val">{getNested(seg.fluid, ["splats", "high", "emit"], 0.11)}</span>
            </label>
            <input type="range" min={0} max={0.4} step={0.01}
              value={getNested(seg.fluid, ["splats", "high", "emit"], 0.11)}
              onChange={(e) => setFluid(["splats", "high", "emit"], parseFloat(e.target.value))} />

            <label className="field">
              Ambient stir <span className="val">{getNested(seg.fluid, ["ambient_strength"], 1.6)}</span>
            </label>
            <input type="range" min={0} max={6} step={0.2}
              value={getNested(seg.fluid, ["ambient_strength"], 1.6)}
              onChange={(e) => setFluid(["ambient_strength"], parseFloat(e.target.value))} />

            <button className="btn" disabled={busy || !runId} onClick={preview}>
              {busy ? "Working…" : "Preview fluid"}
            </button>
            <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              Renders the fluid (no GPU) so you can iterate. Diffusion happens after,
              from the Render screen.
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
