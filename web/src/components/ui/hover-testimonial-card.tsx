"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface Testimonial {
  id: string;
  quote: string;
  author: { name: string; title?: string };
  /** Where the words come from, e.g. "Trustpilot". Shown with a link. */
  source?: { name: string; href: string };
}

interface TestimonialShowcaseProps {
  testimonials: readonly Testimonial[];
  className?: string;
  autoPlayInterval?: number;
}

function initials(name: string) {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

/**
 * One large review card with a glow that follows the pointer; click or use the
 * tiles to move between reviews. Text is rendered exactly as given: nothing is
 * generated or shortened here.
 */
export function TestimonialShowcase({ testimonials, className, autoPlayInterval = 6000 }: TestimonialShowcaseProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [isAnimating, setIsAnimating] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [glow, setGlow] = useState({ x: 0, y: 0 });
  const cardRef = useRef<HTMLDivElement>(null);
  const many = testimonials.length > 1;
  const active = testimonials[activeIndex];

  const switchTo = (next: number) => {
    if (next === activeIndex || isAnimating) return;
    setIsAnimating(true);
    window.setTimeout(() => {
      setActiveIndex(next);
      window.setTimeout(() => setIsAnimating(false), 100);
    }, 200);
  };

  useEffect(() => {
    if (!many || isHovered) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    const timer = window.setInterval(() => {
      setIsAnimating(true);
      window.setTimeout(() => {
        setActiveIndex((i) => (i + 1) % testimonials.length);
        window.setTimeout(() => setIsAnimating(false), 100);
      }, 200);
    }, autoPlayInterval);
    return () => window.clearInterval(timer);
  }, [many, isHovered, autoPlayInterval, testimonials.length]);

  if (!active) return null;

  return (
    <div className={cn("lp-rev", className)}>
      <div
        ref={cardRef}
        onMouseMove={(e) => {
          const rect = cardRef.current?.getBoundingClientRect();
          if (rect) setGlow({ x: e.clientX - rect.left, y: e.clientY - rect.top });
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        onClick={() => many && switchTo((activeIndex + 1) % testimonials.length)}
        className={cn("lp-rev-card", many && "lp-rev-click")}
      >
        <div className="lp-rev-dots" aria-hidden="true" />
        <div
          className="lp-rev-glow"
          aria-hidden="true"
          style={{ background: `radial-gradient(520px circle at ${glow.x}px ${glow.y}px, rgba(247,246,242,.08), transparent 40%)` }}
        />
        <div className="lp-rev-body">
          <q className={cn("lp-rev-quote", isAnimating && "is-out")}>{active.quote}</q>
          <div className={cn("lp-rev-foot", isAnimating && "is-out")}>
            <div className="lp-rev-who">
              <span aria-hidden="true" className="lp-rev-av">{initials(active.author.name)}</span>
              <div>
                <div className="lp-rev-name">{active.author.name}</div>
                {active.author.title && <div className="lp-rev-title">{active.author.title}</div>}
              </div>
            </div>
            {active.source && (
              <a
                href={active.source.href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="lp-rev-src"
              >
                {active.source.name}
              </a>
            )}
          </div>
        </div>
      </div>

      {many && (
        <div className="lp-rev-tabs" role="tablist" aria-label="Reviews">
          {testimonials.map((t, index) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={index === activeIndex}
              aria-label={`Review by ${t.author.name}`}
              onClick={() => switchTo(index)}
              className={cn("lp-rev-tab", index === activeIndex && "is-on")}
            >
              {initials(t.author.name)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
