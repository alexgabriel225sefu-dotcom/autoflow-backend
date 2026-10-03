"use client";
/**
 * A panel that rotates upright and settles as it scrolls into view.
 *
 * Vendored. Two changes from the original: the reduced-motion preference is
 * honoured (the original animated regardless, and a rotating 3D panel is one
 * of the effects that reliably makes people queasy), and the breakpoint is
 * read through matchMedia rather than a resize listener on window.innerWidth.
 */
import React, { useEffect, useRef, useState } from "react";
import { motion, useScroll, useTransform, type MotionValue } from "framer-motion";

function useMedia(query: string) {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const sync = () => setMatches(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, [query]);
  return matches;
}

export function ContainerScroll({
  titleComponent,
  children,
}: {
  titleComponent: React.ReactNode;
  children: React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: containerRef });
  const isMobile = useMedia("(max-width: 768px)");
  const stillPreferred = useMedia("(prefers-reduced-motion: reduce)");

  const rotate = useTransform(scrollYProgress, [0, 1], stillPreferred ? [0, 0] : [20, 0]);
  const scale = useTransform(
    scrollYProgress,
    [0, 1],
    stillPreferred ? [1, 1] : isMobile ? [0.7, 0.9] : [1.05, 1],
  );
  const translate = useTransform(scrollYProgress, [0, 1], stillPreferred ? [0, 0] : [0, -100]);

  return (
    <div
      ref={containerRef}
      className="relative flex h-[60rem] items-center justify-center p-2 md:h-[80rem] md:p-20"
    >
      <div className="relative w-full py-10 md:py-40" style={{ perspective: "1000px" }}>
        <motion.div style={{ translateY: translate }} className="mx-auto max-w-5xl text-center">
          {titleComponent}
        </motion.div>
        <ScrollCard rotate={rotate} scale={scale}>
          {children}
        </ScrollCard>
      </div>
    </div>
  );
}

export function ScrollCard({
  rotate,
  scale,
  children,
}: {
  rotate: MotionValue<number>;
  scale: MotionValue<number>;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      style={{
        rotateX: rotate,
        scale,
        boxShadow:
          "0 0 #0000004d, 0 9px 20px #0000004a, 0 37px 37px #00000042, 0 84px 50px #00000026, 0 149px 60px #0000000a, 0 233px 65px #00000003",
      }}
      className="mx-auto -mt-12 h-[30rem] w-full max-w-5xl rounded-[30px] border-4 border-[#6C6C6C] bg-[#222222] p-2 shadow-2xl md:h-[40rem] md:p-6"
    >
      <div className="h-full w-full overflow-hidden rounded-2xl bg-gray-100 md:p-4 dark:bg-zinc-900">
        {children}
      </div>
    </motion.div>
  );
}

export default ContainerScroll;
