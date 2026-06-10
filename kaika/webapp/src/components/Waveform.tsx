import { useEffect, useRef, useState } from "react";
import type { Segment } from "../api";

interface Props {
  waveform: number[];
  duration: number;
  segments: Segment[];
  selected: number;
  beats: number[];
  onsets: { low: number[]; high: number[] };
  playhead: number;            // seconds
  onSelect: (index: number) => void;
  onSeek: (t: number) => void;
  onMoveBoundary: (boundaryIndex: number, t: number) => void; // between seg i-1 and i
}

const TINT: Record<string, string> = {
  drop: "rgba(184,74,116,0.30)",
  build: "rgba(184,74,116,0.16)",
  intro: "rgba(52,128,138,0.16)",
  outro: "rgba(52,128,138,0.16)",
  verse: "rgba(140,149,161,0.14)",
};
const GRAB_PX = 6;            // hit zone around a draggable boundary

export default function Waveform(props: Props) {
  const { waveform, duration, segments, selected, beats, onsets, playhead,
          onSelect, onSeek, onMoveBoundary } = props;
  const ref = useRef<HTMLCanvasElement>(null);
  const [dragBoundary, setDragBoundary] = useState<number | null>(null);
  const [hoverBoundary, setHoverBoundary] = useState<number | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    const X = (t: number) => (t / duration) * w;

    // segment bands + boundaries
    segments.forEach((s, i) => {
      ctx.fillStyle = TINT[s.label] || "rgba(140,149,161,0.10)";
      ctx.fillRect(X(s.start), 0, X(s.end) - X(s.start), h);
      if (i === selected) {
        ctx.strokeStyle = "#b84a74"; ctx.lineWidth = 2;
        ctx.strokeRect(X(s.start) + 1, 1, X(s.end) - X(s.start) - 2, h - 2);
      }
    });
    for (let i = 1; i < segments.length; i++) {
      const x = X(segments[i].start);
      const hot = i === dragBoundary || i === hoverBoundary;
      ctx.strokeStyle = hot ? "#e891b4" : "rgba(255,255,255,0.30)";
      ctx.lineWidth = hot ? 2.5 : 1;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      // grip
      ctx.fillStyle = hot ? "#e891b4" : "rgba(255,255,255,0.45)";
      ctx.fillRect(x - 2.5, h / 2 - 7, 5, 14);
    }

    // beats: faint ticks along the bottom
    ctx.strokeStyle = "rgba(255,255,255,0.25)";
    ctx.lineWidth = 1;
    beats.forEach((t) => {
      const x = X(t);
      ctx.beginPath(); ctx.moveTo(x, h - 10); ctx.lineTo(x, h); ctx.stroke();
    });
    // onsets: kicks as dots near the bottom, hats near the top
    ctx.fillStyle = "#e0a458";
    onsets.low.forEach((t) => { ctx.beginPath(); ctx.arc(X(t), h - 16, 2.2, 0, 7); ctx.fill(); });
    ctx.fillStyle = "#8fc7bc";
    onsets.high.forEach((t) => { ctx.beginPath(); ctx.arc(X(t), 8, 1.6, 0, 7); ctx.fill(); });

    // waveform
    ctx.strokeStyle = "#8fc7bc"; ctx.lineWidth = 1;
    const mid = h / 2;
    ctx.beginPath();
    waveform.forEach((v, i) => {
      const x = (i / waveform.length) * w;
      ctx.moveTo(x, mid - v * mid * 0.8);
      ctx.lineTo(x, mid + v * mid * 0.8);
    });
    ctx.stroke();

    // playhead
    if (playhead > 0) {
      const x = X(Math.min(playhead, duration));
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
  }, [waveform, duration, segments, selected, beats, onsets, playhead,
      dragBoundary, hoverBoundary]);

  const toSec = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    return Math.max(0, Math.min(duration, ((clientX - r.left) / r.width) * duration));
  };
  const boundaryAt = (clientX: number): number | null => {
    const r = ref.current!.getBoundingClientRect();
    for (let i = 1; i < segments.length; i++) {
      const x = (segments[i].start / duration) * r.width + r.left;
      if (Math.abs(clientX - x) <= GRAB_PX) return i;
    }
    return null;
  };

  return (
    <div className="wave-wrap">
      <canvas
        ref={ref}
        className="wave"
        style={{ cursor: hoverBoundary != null || dragBoundary != null ? "col-resize" : "pointer" }}
        onMouseDown={(e) => {
          const b = boundaryAt(e.clientX);
          if (b != null) setDragBoundary(b);
        }}
        onMouseMove={(e) => {
          if (dragBoundary != null) onMoveBoundary(dragBoundary, toSec(e.clientX));
          else setHoverBoundary(boundaryAt(e.clientX));
        }}
        onMouseUp={(e) => {
          if (dragBoundary != null) { setDragBoundary(null); return; }
          const t = toSec(e.clientX);
          onSeek(t);
          const idx = segments.findIndex((s) => t >= s.start && t < s.end);
          if (idx >= 0) onSelect(idx);
        }}
        onMouseLeave={() => { setDragBoundary(null); setHoverBoundary(null); }}
      />
      <div className="sec-row">
        {segments.map((s, i) => (
          <span key={i}
            className={`sec-chip ${s.label} ${i === selected ? "sel" : ""}`}
            onClick={() => onSelect(i)} style={{ cursor: "pointer" }}>
            {s.label} · {s.start.toFixed(1)}–{s.end.toFixed(1)}s
          </span>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        Click to select & seek · drag a boundary handle to move it · dots = detected
        kicks (amber) and hats (teal).
      </p>
    </div>
  );
}
