import { useEffect, useRef } from "react";
import type { Segment } from "../api";

interface Props {
  waveform: number[];
  duration: number;
  segments: Segment[];
  selected: number;
  onSelect: (index: number) => void;
}

const TINT: Record<string, string> = {
  drop: "rgba(184,74,116,0.30)",
  build: "rgba(184,74,116,0.16)",
  intro: "rgba(52,128,138,0.16)",
  outro: "rgba(52,128,138,0.16)",
  verse: "rgba(140,149,161,0.14)",
};

export default function Waveform({ waveform, duration, segments, selected, onSelect }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    segments.forEach((s, i) => {
      const x = (s.start / duration) * w;
      const ww = ((s.end - s.start) / duration) * w;
      ctx.fillStyle = TINT[s.label] || "rgba(140,149,161,0.10)";
      ctx.fillRect(x, 0, ww, h);
      if (i === selected) {
        ctx.strokeStyle = "#b84a74"; ctx.lineWidth = 2;
        ctx.strokeRect(x + 1, 1, ww - 2, h - 2);
      }
      // boundary line
      ctx.strokeStyle = "rgba(255,255,255,0.18)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    });

    ctx.strokeStyle = "#8fc7bc"; ctx.lineWidth = 1;
    const mid = h / 2;
    ctx.beginPath();
    waveform.forEach((v, i) => {
      const x = (i / waveform.length) * w;
      ctx.moveTo(x, mid - v * mid * 0.92);
      ctx.lineTo(x, mid + v * mid * 0.92);
    });
    ctx.stroke();
  }, [waveform, duration, segments, selected]);

  const pick = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    const t = ((clientX - r.left) / r.width) * duration;
    const idx = segments.findIndex((s) => t >= s.start && t < s.end);
    if (idx >= 0) onSelect(idx);
  };

  return (
    <div className="wave-wrap">
      <canvas ref={ref} className="wave" onClick={(e) => pick(e.clientX)} />
      <div className="sec-row">
        {segments.map((s, i) => (
          <span
            key={i}
            className={`sec-chip ${s.label} ${i === selected ? "sel" : ""}`}
            onClick={() => onSelect(i)}
            style={{ cursor: "pointer" }}
          >
            {s.label} · {s.start.toFixed(1)}–{s.end.toFixed(1)}s
          </span>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        Click a segment to edit its prompt and fluid parameters.
      </p>
    </div>
  );
}
