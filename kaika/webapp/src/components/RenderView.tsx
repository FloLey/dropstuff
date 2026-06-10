import { useEffect, useRef, useState } from "react";
import { api, JobState, STAGES } from "../api";

const LIVE_POLL_MS = 1200;

interface Props {
  runId: string | null;
  jobId: string | null;
  onSeeGallery: () => void;
}

export default function RenderView({ runId, jobId, onSeeGallery }: Props) {
  const [job, setJob] = useState<JobState | null>(null);
  const [liveFrame, setLiveFrame] = useState<string | null>(null);
  const [watchedJob, setWatchedJob] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const watch = (id: string) => {
    wsRef.current?.close();
    setJob(null);
    setWatchedJob(id);
    wsRef.current = api.watchJob(id, setJob);
  };

  useEffect(() => {
    if (jobId) watch(jobId);
    return () => wsRef.current?.close();
  }, [jobId]);

  // live peek: poll the newest frame on disk while the job runs
  const running = job?.status === "running";
  useEffect(() => {
    if (!running || !runId) { setLiveFrame(null); return; }
    const t = window.setInterval(() => {
      setLiveFrame(`/api/runs/${runId}/latest_frame?ts=${Date.now()}`);
    }, LIVE_POLL_MS);
    return () => window.clearInterval(t);
  }, [running, runId]);

  const cancel = async () => {
    if (!watchedJob) return;
    await fetch(`/api/jobs/${watchedJob}/cancel`, { method: "POST" }).catch(() => {});
  };

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
  const isSegment = kind === "fluid_segment";
  const isFluid = kind === "fluid" || isSegment;
  // show only the stages this kind of job actually runs
  const stages = isSegment ? ["simulate", "post"]
    : isFluid ? STAGES.filter((s) => s !== "diffuse" && s !== "control") : STAGES;

  return (
    <div className="grid">
      <div className="card">
        <h3>{isSegment ? "Segment preview" : isFluid ? "Fluid preview" : "Diffusion"}</h3>
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
        {job?.status === "cancelled" && <p className="muted">Cancelled.</p>}
        {running && (
          <button className="btn ghost slim" style={{ marginTop: 14 }} onClick={cancel}>
            Cancel render
          </button>
        )}
        {running && liveFrame && (
          <div style={{ marginTop: 14 }}>
            <p className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Live frame</p>
            <img className="live-frame" src={liveFrame}
              onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
              onLoad={(e) => ((e.target as HTMLImageElement).style.display = "block")} />
          </div>
        )}
      </div>

      <aside className="card">
        <h3>{done ? (isFluid ? "Fluid result" : "Final clip") : "Rendering…"}</h3>
        {done ? (
          <>
            <video
              src={isSegment ? api.segPreviewUrl(runId)
                : isFluid ? api.previewUrl(runId) : api.finalUrl(runId)}
              poster={api.posterUrl(runId)}
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
