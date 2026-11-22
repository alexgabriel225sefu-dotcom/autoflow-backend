"use client";
import { useRef } from "react";

export function Magnet({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) {
  const ref = useRef<HTMLAnchorElement>(null);
  const move = (e: React.MouseEvent) => {
    const el = ref.current; if (!el) return;
    const r = el.getBoundingClientRect();
    const dx = (e.clientX - (r.left + r.width / 2)) * 0.25;
    const dy = (e.clientY - (r.top + r.height / 2)) * 0.35;
    el.style.transform = `translate(${dx}px, ${dy}px)`;
  };
  const leave = () => { if (ref.current) ref.current.style.transform = ""; };
  return <a ref={ref} href={href} className={className} onMouseMove={move} onMouseLeave={leave}>{children}</a>;
}
