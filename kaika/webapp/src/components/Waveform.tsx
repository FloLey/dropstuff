import { useEffect, useRef, useState } from "react";
import type { Section } from "../api";

interface Props {
  waveform: number[];
  duration: number;
  sections: Section[];
  selection: [number, number] | null; // seconds
  onSelect: (sel: [number, number] | null) => void;
}

const SECTION_TINT: Record<string, string> = {
  drop: "rgba(184,74,116,0.30)",
  build: "rgba(184,74,116,0.16)",
  intro: "rgba(52,128,138,0.16)",
  outro: "rgba(52,128,138,0.16)",
  verse: "rgba(140,149,161,0.14)",
};

export default function Waveform({ waveform, duration, sections, selection, onSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [drag, setDrag] = useState<{ x0: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    // section bands
    for (const s of sections) {
      const x = (s.start / duration) * w;
      const ww = ((s.end - s.start) / duration) * w;
      ctx.fillStyle = SECTION_TINT[s.label] || "rgba(140,149,161,0.10)";
      ctx.fillRect(x, 0, ww, h);
    }
    // waveform
    ctx.strokeStyle = "#8fc7bc";
    ctx.lineWidth = 1;
    const mid = h / 2;
    ctx.beginPath();
    waveform.forEach((v, i) => {
      const x = (i / waveform.length) * w;
      ctx.moveTo(x, mid - v * mid * 0.92);
      ctx.lineTo(x, mid + v * mid * 0.92);
    });
    ctx.stroke();
    // selection
    if (selection) {
      const x = (selection[0] / duration) * w;
      const ww = ((selection[1] - selection[0]) / duration) * w;
      ctx.fillStyle = "rgba(184,74,116,0.22)";
      ctx.fillRect(x, 0, ww, h);
      ctx.strokeStyle = "#b84a74";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x, 0, ww, h);
    }
  }, [waveform, duration, sections, selection]);

  const toSec = (clientX: number) => {
    const r = canvasRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(duration, ((clientX - r.left) / r.width) * duration));
  };

  return (
    <div className="wave-wrap">
      <canvas
        ref={canvasRef}
        className="wave"
        onMouseDown={(e) => setDrag({ x0: toSec(e.clientX) })}
        onMouseMove={(e) => {
          if (!drag) return;
          const x1 = toSec(e.clientX);
          onSelect([Math.min(drag.x0, x1), Math.max(drag.x0, x1)]);
        }}
        onMouseUp={() => setDrag(null)}
        onMouseLeave={() => setDrag(null)}
      />
      <div className="sec-row">
        {sections.map((s, i) => (
          <span key={i} className={`sec-chip ${s.label}`}>
            {s.label} · {s.start.toFixed(1)}–{s.end.toFixed(1)}s
          </span>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        Drag on the waveform to select an extract for a fast partial render.
      </p>
    </div>
  );
}
