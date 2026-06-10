import { useEffect, useRef, useState } from "react";
import { api, RunManifest } from "../api";

interface Props {
  onOpenInStudio: (runId: string) => void;
}

function runVideoUrl(r: RunManifest): string | null {
  if (r.stage === "done" || r.status === "done") return api.finalUrl(r.id);
  if (r.fluid_preview) return api.previewUrl(r.id);
  return null;
}

/** Two videos, one transport: play/pause/seek both on the same timeline. */
function Compare({ a, b, onClose }: { a: RunManifest; b: RunManifest; onClose: () => void }) {
  const va = useRef<HTMLVideoElement>(null);
  const vb = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);

  const both = (fn: (v: HTMLVideoElement) => void) => {
    if (va.current) fn(va.current);
    if (vb.current) fn(vb.current);
  };
  const toggle = () => {
    if (playing) both((v) => v.pause());
    else { both((v) => { v.currentTime = va.current?.currentTime ?? 0; v.play(); }); }
    setPlaying(!playing);
  };
  const seek = (t: number) => both((v) => { v.currentTime = t; });

  return (
    <div className="card compare">
      <div className="compare-head">
        <h3>Compare</h3>
        <button className="btn ghost slim" onClick={onClose}>Close</button>
      </div>
      <div className="compare-grid">
        {[{ r: a, ref: va }, { r: b, ref: vb }].map(({ r, ref }) => (
          <div key={r.id}>
            <video ref={ref} src={runVideoUrl(r) ?? undefined} preload="auto" muted={ref === vb} />
            <p className="muted mono" style={{ fontSize: 11 }}>{r.recipe} · {r.id}</p>
          </div>
        ))}
      </div>
      <div className="transport" style={{ marginTop: 10 }}>
        <button className="play" onClick={toggle}>{playing ? "❚❚" : "▶"}</button>
        <input type="range" min={0} max={va.current?.duration || 60} step={0.05}
          style={{ flex: 1 }} defaultValue={0}
          onChange={(e) => seek(parseFloat(e.target.value))} />
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Same audio timeline, both videos locked together — judge one parameter change.
      </p>
    </div>
  );
}

export default function Gallery({ onOpenInStudio }: Props) {
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);

  useEffect(() => { api.runs().then(setRuns).catch(() => setRuns([])); }, []);

  const togglePick = (id: string) =>
    setPicked((p) => p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2));

  if (runs.length === 0) {
    return (
      <div className="card" style={{ marginTop: 26 }}>
        <p className="muted">No runs yet. Create one in the Studio.</p>
      </div>
    );
  }

  const pair = picked.map((id) => runs.find((r) => r.id === id)!).filter(Boolean);

  return (
    <>
      {comparing && pair.length === 2 ? (
        <Compare a={pair[0]} b={pair[1]} onClose={() => setComparing(false)} />
      ) : (
        picked.length === 2 && (
          <div className="card compare-bar">
            <span className="muted">2 runs selected</span>
            <button className="btn slim" style={{ width: "auto" }}
              onClick={() => setComparing(true)}>Compare side by side</button>
          </div>
        )
      )}

      <div className="runs">
        {runs.map((r) => {
          const url = runVideoUrl(r);
          const hasFinal = r.stage === "done" || r.status === "done";
          return (
            <div key={r.id} className={`card run-card ${picked.includes(r.id) ? "picked" : ""}`}>
              {url ? <video src={url} controls loop preload="metadata" />
                   : <p className="muted">({r.stage || r.status})</p>}
              <div className="run-meta">
                <span className="mono">{r.recipe}</span>
                <span className={`badge ${r.status}`}>{hasFinal ? "final" : (r.stage || r.status)}</span>
              </div>
              <div className="run-meta">
                <span>{r.n_frames ?? "—"} frames</span>
                {r.sync && <span className="mono">corr {r.sync.correlation}</span>}
              </div>
              <div className="run-actions">
                <button className="btn ghost slim" onClick={() => onOpenInStudio(r.id)}>
                  Open in Studio
                </button>
                <label className="check" style={{ marginTop: 0 }}>
                  <input type="checkbox" checked={picked.includes(r.id)}
                    onChange={() => togglePick(r.id)} />
                  compare
                </label>
              </div>
              <p className="muted mono" style={{ fontSize: 11, marginTop: 4 }}>
                {new Date(r.created * 1000).toLocaleString()}
              </p>
            </div>
          );
        })}
      </div>
    </>
  );
}
