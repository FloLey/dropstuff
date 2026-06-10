import { useState } from "react";
import Studio from "./components/Studio";
import RenderView from "./components/RenderView";
import Gallery from "./components/Gallery";

type View = "studio" | "render" | "gallery";

export default function App() {
  const [view, setView] = useState<View>("studio");
  const [runId, setRunId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const tab = (v: View, label: string) => (
    <button className={view === v ? "active" : ""} onClick={() => setView(v)}>
      {label}
    </button>
  );

  return (
    <div className="app">
      <header className="top">
        <span className="brand">Kaika <span className="kanji">開花</span></span>
        <nav className="tabs">
          {tab("studio", "Studio")}
          {tab("render", "Render")}
          {tab("gallery", "Gallery")}
        </nav>
      </header>

      {view === "studio" && (
        <Studio
          onPreview={(rid, jid) => { setRunId(rid); setJobId(jid); setView("render"); }}
        />
      )}
      {view === "render" && (
        <RenderView runId={runId} jobId={jobId} onSeeGallery={() => setView("gallery")} />
      )}
      {view === "gallery" && <Gallery />}
    </div>
  );
}
