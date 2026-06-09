// Typed client for the Kaika API. Same origin in production; Vite proxies in dev.

export interface Section { start: number; end: number; label: string; energy: number; }
export interface Beat { t: number; mag: number; }
export interface Analysis {
  audio_id: string;
  tempo_bpm: number;
  duration_s: number;
  fps: number;
  n_frames: number;
  sections: Section[];
  beats: Beat[];
  onset_counts: Record<string, number>;
  waveform: number[];
}
export interface RecipeEntry { name: string; yaml: string; recipe: any; }
export interface JobState {
  id: string; status: string; stage: string | null;
  done: number; total: number; run_id: string | null; error: string | null;
}
export interface RunManifest {
  id: string; created: number; recipe: string; fps: number; n_frames: number;
  status: string; sync: { lag_frames: number; correlation: number } | null;
  final?: string; stages: Record<string, any>;
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json() as Promise<T>;
}

export const api = {
  recipes: () => fetch("/api/recipes").then(j<RecipeEntry[]>),

  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/upload", { method: "POST", body: fd })
      .then(j<{ audio_id: string; name: string }>);
  },

  analyze: (audio_id: string, fps = 24) =>
    fetch(`/api/analyze?audio_id=${audio_id}&fps=${fps}`, { method: "POST" })
      .then(j<Analysis>),

  startRun: (body: { audio_id: string; recipe?: any; recipe_name?: string; seconds?: number }) =>
    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<{ job_id: string }>),

  job: (id: string) => fetch(`/api/jobs/${id}`).then(j<JobState>),
  runs: () => fetch("/api/runs").then(j<RunManifest[]>),
  run: (id: string) => fetch(`/api/runs/${id}`).then(j<RunManifest>),
  finalUrl: (id: string) => `/api/runs/${id}/final`,
  fileUrl: (id: string, sub: string) => `/api/runs/${id}/files/${sub}`,

  watchJob: (id: string, onMsg: (s: JobState) => void): WebSocket => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/jobs/${id}`);
    ws.onmessage = (e) => onMsg(JSON.parse(e.data));
    return ws;
  },
};

export const STAGES = ["analyze", "simulate", "control", "diffuse", "post"];
