import { useEffect, useRef, useState } from "react";
import { api, JobState, STAGES } from "../api";

interface Props {
  runId: string | null;
  jobId: string | null;
  onSeeGallery: () => void;
}

export default function RenderView({ runId, jobId, onSeeGallery }: Props) {
  const [job, setJob] = useState<JobState | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const watch = (id: string) => {
    wsRef.current?.close();
    setJob(null);
    wsRef.current = api.watchJob(id, setJob);
  };

  useEffect(() => {
    if (jobId) watch(jobId);
    return () => wsRef.current?.close();
  }, [jobId]);

  const generate = async () => {
    if (!runId) return;
    const { job_id } = await api.generateProject(runId);
    watch(job_id);
  };

  if (!jobId || !runId) {
    return (
      <div className="card" style={{ marginTop: 26 }}>
        <p className="muted">No active render. Start a fluid preview from the Studio.</p>
      </div>
    );
  }

  const kind = job?.kind || "fluid";
  const stageIndex = job?.stage ? STAGES.indexOf(job.stage) : -1;
  const done = job?.status === "done";
  const isFluid = kind === "fluid";
  // fluid stage stops at "post" without diffuse; show only the relevant stages
  const stages = isFluid ? STAGES.filter((s) => s !== "diffuse") : STAGES;

  return (
    <div className="grid">
      <div className="card">
        <h3>{isFluid ? "Fluid preview" : "Diffusion"}</h3>
        <div className="pipeline">
          {stages.map((name) => {
            const isCurrent = job?.stage === name && job.status === "running";
            const isDone = done || stageIndex > STAGES.indexOf(name) ||
              (job?.stage === name && job?.total! > 0 && job?.done === job?.total);
            const pct = isDone ? 100 : isCurrent && job?.total ? Math.round((job.done / job.total) * 100) : 0;
            return (
              <div key={name} className={`stage-row ${isDone ? "done" : ""}`}>
                <span className="stage-name">{name}</span>
                <div className="bar"><i style={{ width: `${pct}%` }} /></div>
                <span className="pct">{isDone ? "done" : isCurrent ? `${pct}%` : "—"}</span>
              </div>
            );
          })}
        </div>
        {job?.status === "error" && <p className="err">Error: {job.error}</p>}
      </div>

      <aside className="card">
        <h3>{done ? (isFluid ? "Fluid result" : "Final clip") : "Rendering…"}</h3>
        {done ? (
          <>
            <video
              src={isFluid ? api.previewUrl(runId) : api.finalUrl(runId)}
              controls autoPlay loop
            />
            {isFluid ? (
              <>
                <p className="muted" style={{ margin: "8px 0" }}>
                  Happy with the motion? Run the diffusion to get the final clip.
                </p>
                <button className="btn" onClick={generate}>Generate final (diffusion)</button>
              </>
            ) : (
              <button className="btn ghost" onClick={onSeeGallery}>See in Gallery</button>
            )}
          </>
        ) : (
          <p className="muted">
            {job?.status === "error" ? "Render failed — see the pipeline." :
              "Working… the result appears here when ready."}
          </p>
        )}
      </aside>
    </div>
  );
}
