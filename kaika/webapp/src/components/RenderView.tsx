import { useEffect, useState } from "react";
import { api, JobState, RunManifest, STAGES } from "../api";

interface Props {
  jobId: string | null;
  onSeeGallery: () => void;
}

export default function RenderView({ jobId, onSeeGallery }: Props) {
  const [job, setJob] = useState<JobState | null>(null);
  const [run, setRun] = useState<RunManifest | null>(null);

  useEffect(() => {
    if (!jobId) return;
    setRun(null);
    const ws = api.watchJob(jobId, setJob);
    return () => ws.close();
  }, [jobId]);

  useEffect(() => {
    if (job?.status === "done" && job.run_id) {
      api.run(job.run_id).then(setRun);
    }
  }, [job?.status, job?.run_id]);

  if (!jobId) {
    return (
      <div className="card" style={{ marginTop: 26 }}>
        <p className="muted">No active render. Start one from the Studio.</p>
      </div>
    );
  }

  const stageIndex = job?.stage ? STAGES.indexOf(job.stage) : -1;

  return (
    <div className="grid">
      <div className="card">
        <h3>Pipeline</h3>
        <div className="pipeline">
          {STAGES.map((name, i) => {
            const isCurrent = job?.stage === name && job.status === "running";
            const isDone =
              job?.status === "done" || (stageIndex > i) ||
              (stageIndex === i && job?.done === job?.total && job?.total! > 0);
            const pct =
              isDone ? 100 : isCurrent && job?.total ? Math.round((job.done / job.total) * 100) : 0;
            return (
              <div key={name} className={`stage-row ${isDone ? "done" : ""}`}>
                <span className="stage-name">{name}</span>
                <div className="bar">
                  <i style={{ width: `${pct}%` }} />
                </div>
                <span className="pct">{isDone ? "done" : isCurrent ? `${pct}%` : "—"}</span>
              </div>
            );
          })}
        </div>
        {job?.status === "error" && <p className="err">Error: {job.error}</p>}
      </div>

      <aside className="card">
        <h3>Result</h3>
        {run ? (
          <>
            <video src={api.finalUrl(run.id)} controls autoPlay loop />
            <div className="run-meta">
              <span className="mono">{run.recipe}</span>
              <span className="mono">{run.n_frames} frames</span>
            </div>
            {run.sync && (
              <p className="muted mono" style={{ marginTop: 6 }}>
                sync lag {run.sync.lag_frames}f · corr {run.sync.correlation}
              </p>
            )}
            <button className="btn ghost" onClick={onSeeGallery}>
              See in Gallery
            </button>
          </>
        ) : (
          <p className="muted">
            {job?.status === "error"
              ? "Render failed."
              : "Rendering… previews appear here when ready."}
          </p>
        )}
      </aside>
    </div>
  );
}
