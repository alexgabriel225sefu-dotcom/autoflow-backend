"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { Studio, webglAvailable } from "./chrome-scene";

/**
 * One chrome A4 that travels with the page.
 *
 * It is a fixed layer behind the copy. The scroll position (0 at the top, 1 at
 * the bottom) drives a path of poses: it starts off to the right beside the
 * hero, swings to the left of the stop-line section, sways side to side behind the product tour, and settles small in the
 * corner for the pricing and FAQ. Position, turn and size are smoothed so it
 * glides instead of snapping. Nothing here fetches from a third party, and
 * with reduced motion the layer is not rendered at all.
 */

type Pose = { at: number; x: number; y: number; z: number; ry: number; rx: number; s: number };

// at = page progress. x/y in scene units, ry/rx in radians, s = scale.
const PATH: Pose[] = [
  { at: 0.0, x: 1.6, y: 0.0, z: -1, ry: -0.3, rx: -0.08, s: 0.01 },
  { at: 0.1, x: -3.2, y: 0.3, z: -1.5, ry: 0.7, rx: 0.1, s: 0.7 },
  { at: 0.3, x: 3.2, y: -0.2, z: -1.2, ry: -0.7, rx: -0.12, s: 0.75 },
  { at: 0.5, x: -3.2, y: 0.2, z: -1.5, ry: 0.8, rx: 0.12, s: 0.7 },
  { at: 0.72, x: 3.2, y: 0.0, z: -1.2, ry: -0.8, rx: -0.1, s: 0.7 },
  { at: 1.0, x: 0.0, y: -1.1, z: -2, ry: 0.0, rx: 0.0, s: 0.4 },
];

function sample(p: number): Pose {
  const c = Math.min(Math.max(p, 0), 1);
  let i = 0;
  while (i < PATH.length - 2 && c > PATH[i + 1].at) i += 1;
  const a = PATH[i];
  const b = PATH[i + 1];
  const k = (c - a.at) / (b.at - a.at);
  const e = k * k * (3 - 2 * k); // smoothstep between poses
  const l = (u: number, v: number) => u + (v - u) * e;
  return { at: c, x: l(a.x, b.x), y: l(a.y, b.y), z: l(a.z, b.z), ry: l(a.ry, b.ry), rx: l(a.rx, b.rx), s: l(a.s, b.s) };
}

function Traveller({ model, narrow }: { model: string; narrow: boolean }) {
  const gltf = useGLTF(model, false);
  const group = useRef<THREE.Group>(null);
  const cur = useRef<Pose>(sample(0));

  const scene = useMemo(() => {
    const clone = gltf.scene.clone(true);
    const chrome = new THREE.MeshPhysicalMaterial({
      color: new THREE.Color("#e6e7ec"),
      metalness: 1,
      roughness: 0.22,
      clearcoat: 1,
      clearcoatRoughness: 0.1,
      envMapIntensity: 1.3,
    });
    clone.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) m.material = chrome;
    });
    return clone;
  }, [gltf.scene]);

  useFrame(() => {
    const g = group.current;
    if (!g) return;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const target = sample(max > 0 ? window.scrollY / max : 0);
    const c = cur.current;
    const f = 0.07;
    c.x += (target.x - c.x) * f;
    c.y += (target.y - c.y) * f;
    c.z += (target.z - c.z) * f;
    c.ry += (target.ry - c.ry) * f;
    c.rx += (target.rx - c.rx) * f;
    c.s += (target.s - c.s) * f;
    // On a phone the object sits behind the copy, so it stays centred and small.
    g.position.set(narrow ? c.x * 0.25 : c.x, c.y, c.z);
    g.rotation.set(c.rx, c.ry, 0);
    g.scale.setScalar(c.s * (narrow ? 0.7 : 1));
  });

  return (
    <group ref={group}>
      <primitive object={scene} />
    </group>
  );
}

export function ScrollBackdropScene({ model }: { model: string }) {
  const [ok] = useState<boolean | null>(() => (typeof document === "undefined" ? null : webglAvailable()));
  const [reduced] = useState<boolean>(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  const [narrow, setNarrow] = useState<boolean>(() => typeof window !== "undefined" && window.innerWidth < 740);

  useEffect(() => {
    const on = () => setNarrow(window.innerWidth < 740);
    window.addEventListener("resize", on, { passive: true });
    return () => window.removeEventListener("resize", on);
  }, []);

  if (!ok || reduced) return null;

  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0, 6], fov: 32 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      style={{ background: "transparent" }}
      aria-hidden="true"
    >
      <Suspense fallback={null}>
        <Studio />
        <Traveller model={model} narrow={narrow} />
      </Suspense>
    </Canvas>
  );
}
