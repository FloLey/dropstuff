import { useEffect, useState } from "react";
import { api, Analysis, RecipeEntry } from "../api";
import Waveform from "./Waveform";

interface Props {
  onStarted: (jobId: string) => void;
}

export default function Studio({ onStarted }: Props) {
  const [recipes, setRecipes] = useState<RecipeEntry[]>([]);
  const [recipeName, setRecipeName] = useState("eclosion");
  const [recipe, setRecipe] = useState<any>(null);
  const [audioId, setAudioId] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selection, setSelection] = useState<[number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [hover, setHover] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.recipes().then((r) => {
      setRecipes(r);
      const e = r.find((x) => x.name === recipeName) || r[0];
      if (e) {
        setRecipeName(e.name);
        setRecipe(structuredClone(e.recipe));
      }
    });
  }, []);

  const pickRecipe = (name: string) => {
    const e = recipes.find((x) => x.name === name);
    if (e) {
      setRecipeName(name);
      setRecipe(structuredClone(e.recipe));
    }
  };

  const upload = async (file: File) => {
    setErr("");
    setBusy(true);
    try {
      const { audio_id } = await api.upload(file);
      setAudioId(audio_id);
      setFileName(file.name);
      const a = await api.analyze(audio_id, recipe?.post?.fps ?? 24);
      setAnalysis(a);
      setSelection(null);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const start = async (full: boolean) => {
    if (!audioId) return;
    setBusy(true);
    setErr("");
    try {
      const seconds = full || !selection ? undefined : selection[1] - selection[0];
      const { job_id } = await api.startRun({ audio_id: audioId, recipe, seconds });
      onStarted(job_id);
    } catch (e: any) {
      setErr(String(e.message || e));
      setBusy(false);
    }
  };

  const setIn = (path: string[], value: any) => {
    setRecipe((r: any) => {
      const next = structuredClone(r);
      let o = next;
      for (let i = 0; i < path.length - 1; i++) o = o[path[i]];
      o[path[path.length - 1]] = value;
      return next;
    });
  };

  return (
    <div className="grid">
      <div>
        {!analysis && (
          <div
            className={`drop ${hover ? "hover" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setHover(true);
            }}
            onDragLeave={() => setHover(false)}
            onDrop={(e) => {
              e.preventDefault();
              setHover(false);
              const f = e.dataTransfer.files[0];
              if (f) upload(f);
            }}
          >
            <p style={{ fontSize: 18, marginBottom: 10 }}>Drop an audio file here</p>
            <p className="muted">or</p>
            <label className="btn ghost" style={{ display: "inline-block", width: "auto", marginTop: 12 }}>
              Choose file
              <input
                type="file"
                accept="audio/*"
                style={{ display: "none" }}
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              />
            </label>
          </div>
        )}

        {analysis && (
          <div className="card">
            <h3>{fileName}</h3>
            <p className="muted mono" style={{ marginBottom: 12 }}>
              {analysis.tempo_bpm} BPM · {analysis.duration_s.toFixed(1)}s ·{" "}
              {analysis.n_frames} frames · onsets{" "}
              {Object.entries(analysis.onset_counts).map(([k, v]) => `${k}:${v}`).join(" ")}
            </p>
            <Waveform
              waveform={analysis.waveform}
              duration={analysis.duration_s}
              sections={analysis.sections}
              selection={selection}
              onSelect={setSelection}
            />
          </div>
        )}
        {err && <p className="err">{err}</p>}
      </div>

      <aside>
        <div className="card">
          <h3>Recipe</h3>
          <label className="field">Identity</label>
          <select value={recipeName} onChange={(e) => pickRecipe(e.target.value)}>
            {recipes.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          </select>

          {recipe && (
            <>
              <label className="field">
                Denoise strength <span className="val">{recipe.diffusion.strength}</span>
              </label>
              <input
                type="range" min={0.1} max={0.9} step={0.05}
                value={recipe.diffusion.strength}
                onChange={(e) => setIn(["diffusion", "strength"], parseFloat(e.target.value))}
              />

              <label className="field">
                Vorticity max <span className="val">{recipe.fluid.vorticity.max}</span>
              </label>
              <input
                type="range" min={5} max={80} step={1}
                value={recipe.fluid.vorticity.max}
                onChange={(e) => setIn(["fluid", "vorticity", "max"], parseInt(e.target.value))}
              />

              <label className="field">
                Lookahead (s) <span className="val">{recipe.fluid.lookahead_s}</span>
              </label>
              <input
                type="range" min={0} max={16} step={0.5}
                value={recipe.fluid.lookahead_s}
                onChange={(e) => setIn(["fluid", "lookahead_s"], parseFloat(e.target.value))}
              />

              <label className="field">Seed</label>
              <input
                type="number" value={recipe.seed}
                onChange={(e) => setIn(["seed"], parseInt(e.target.value) || 0)}
              />

              <label className="field">Prompt · base</label>
              <textarea
                value={recipe.prompts.base}
                onChange={(e) => setIn(["prompts", "base"], e.target.value)}
              />
              <label className="field">Prompt · drop</label>
              <textarea
                value={recipe.prompts.drop || ""}
                onChange={(e) => setIn(["prompts", "drop"], e.target.value)}
              />
            </>
          )}

          <button
            className="btn"
            disabled={!audioId || busy}
            onClick={() => start(false)}
          >
            {selection
              ? `Render extract (${(selection[1] - selection[0]).toFixed(1)}s)`
              : "Render extract"}
          </button>
          <button
            className="btn ghost"
            disabled={!audioId || busy}
            onClick={() => start(true)}
          >
            Render full clip
          </button>
        </div>
      </aside>
    </div>
  );
}
