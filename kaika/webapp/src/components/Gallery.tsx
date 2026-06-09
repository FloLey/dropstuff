import { useEffect, useState } from "react";
import { api, RunManifest } from "../api";

export default function Gallery() {
  const [runs, setRuns] = useState<RunManifest[]>([]);

  useEffect(() => {
    api.runs().then(setRuns).catch(() => setRuns([]));
  }, []);

  if (runs.length === 0) {
    return (
      <div className="card" style={{ marginTop: 26 }}>
        <p className="muted">No runs yet. Render something in the Studio.</p>
      </div>
    );
  }

  return (
    <div className="runs">
      {runs.map((r) => (
        <div key={r.id} className="card run-card">
          {r.status === "done" ? (
            <video src={api.finalUrl(r.id)} controls loop preload="metadata" />
          ) : (
            <p className="muted">({r.status})</p>
          )}
          <div className="run-meta">
            <span className="mono">{r.recipe}</span>
            <span className={`badge ${r.status}`}>{r.status}</span>
          </div>
          <div className="run-meta">
            <span>{r.n_frames ?? "—"} frames</span>
            {r.sync && <span className="mono">corr {r.sync.correlation}</span>}
          </div>
          <p className="muted mono" style={{ fontSize: 11, marginTop: 4 }}>
            {new Date(r.created * 1000).toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}
