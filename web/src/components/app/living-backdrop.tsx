"use client";
/**
 * The living background behind the dashboard.
 *
 * Two ideas taken from the shader and node-based pieces on saved.design: a
 * wire mesh that rolls like terrain in the accent colour, and small blocks of
 * light that switch on and off on a grid. It is drawn on a canvas at a low
 * frame rate, it stops when the tab is hidden, and for anyone who asked for
 * less motion it draws one still frame. It is decoration: it reads no
 * account data and claims nothing.
 */
import { useEffect, useRef } from "react";

type Block = { cx: number; cy: number; born: number; life: number; hot: boolean };

function accent(el: HTMLElement): [number, number, number] {
  const raw = getComputedStyle(el).getPropertyValue("--a4t-accent").trim();
  const m = /^#?([0-9a-f]{6})$/i.exec(raw);
  if (!m) return [247, 246, 242];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function LivingBackdrop() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext?.("2d");
    if (!canvas || !ctx) return;
    const reduce = !!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    const light = document.documentElement.getAttribute("data-theme") === "light";
    let rgb = accent(document.documentElement);
    let w = 0, h = 0, raf = 0, last = 0, frame = 0;
    const blocks: Block[] = [];
    const CELL = 34;

    function size() {
      if (!canvas) return;
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = w; canvas.height = h;
    }

    function draw(t: number) {
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);
      const [r, g, b] = rgb;
      const dark = light ? 0 : 1;
      const strokeA = dark ? 0.55 : 0.3;

      // Rolling wire mesh, in perspective, fading toward the horizon.
      const horizon = h * 0.2, rows = 30, cols = 44, cam = 1.35;
      for (let zi = rows; zi >= 1; zi--) {
        const z = zi / rows;                        // 1 near .. 0 far
        const depth = 0.12 + (1 - z) * 2.6;
        const scale = (h * 0.62) / depth;
        ctx.beginPath();
        for (let xi = 0; xi <= cols; xi++) {
          const x = (xi / cols - 0.5) * 6.2;
          const y = Math.sin(x * 1.15 + t * 0.00055 + zi * 0.5) * 0.16 * (0.4 + z)
            + Math.cos(x * 0.62 - t * 0.0004 + zi * 0.33) * 0.12 * (0.4 + z);
          const sx = w / 2 + (x * scale) * 0.55;
          const sy = horizon + (cam - y) * scale * 0.32 + (1 - z) * h * 0.04;
          if (xi === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
        }
        ctx.strokeStyle = `rgba(${r},${g},${b},${(strokeA * (0.25 + z * 0.75)).toFixed(3)})`;
        ctx.lineWidth = 0.6 + z * 0.9;
        ctx.stroke();
      }

      // Blocks of light switching on a grid.
      if (!reduce && blocks.length < 16 && Math.random() < 0.18) {
        blocks.push({
          cx: Math.floor(Math.random() * (w / CELL)), cy: Math.floor(Math.random() * (h * 0.62 / CELL)),
          born: t, life: 1400 + Math.random() * 2200, hot: Math.random() < 0.18,
        });
      }
      for (let i = blocks.length - 1; i >= 0; i--) {
        const k = blocks[i], age = (t - k.born) / k.life;
        if (age >= 1) { blocks.splice(i, 1); continue; }
        const a = Math.sin(age * Math.PI);
        ctx.fillStyle = k.hot
          ? `rgba(${dark ? 255 : 20},${dark ? 255 : 20},${dark ? 255 : 20},${(a * 0.5).toFixed(3)})`
          : `rgba(${r},${g},${b},${(a * 0.38).toFixed(3)})`;
        ctx.fillRect(k.cx * CELL + 2, k.cy * CELL + 2, CELL - 4, CELL - 4);
      }
    }

    function loop(t: number) {
      raf = requestAnimationFrame(loop);
      if (t - last < 33) return;              // about 30 frames a second
      last = t;
      if (++frame % 90 === 0) rgb = accent(document.documentElement);
      draw(t);
    }

    size();
    window.addEventListener("resize", size);
    if (reduce) draw(4000);
    else raf = requestAnimationFrame(loop);
    const vis = () => { if (document.hidden) { cancelAnimationFrame(raf); } else if (!reduce) { raf = requestAnimationFrame(loop); } };
    document.addEventListener("visibilitychange", vis);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", size);
      document.removeEventListener("visibilitychange", vis);
    };
  }, []);

  return <canvas ref={ref} className="dash-canvas" aria-hidden="true" />;
}
