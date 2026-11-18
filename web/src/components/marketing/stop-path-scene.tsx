"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { Studio, webglAvailable } from "./chrome-scene";

/**
 * A limit that holds, in 3D.
 *
 * A price path in polished chrome is drawn once, wandering up and then coming
 * down onto a pink plane, and stops there. The plane is the rule's stop: the
 * product refuses to activate a rule that has none, and the risk limits are
 * enforced on the server. There is no market data in here and no number: the
 * path is a fixed curve, so the scene claims nothing about any result.
 *
 * Built in code, so it costs no generation credits and nothing is downloaded
 * for it except three.js itself, which the hero already loads.
 */

const STOP_Y = -0.95;
const SEGMENTS = 260;
const RADIAL = 12;
const DRAW_SECONDS = 4.2;
const START_DELAY = 0.5;

function makeCurve() {
  const pts = [
    [-3.1, 0.15, 0.0], [-2.5, 0.45, 0.1], [-1.9, 0.1, 0.0], [-1.3, 0.55, -0.1],
    [-0.6, 0.35, 0.0], [0.1, 1.15, 0.15], [0.8, 0.85, 0.05], [1.45, 0.25, 0.1],
    [2.05, -0.35, 0.0], [2.6, STOP_Y + 0.02, 0.05],
  ].map(([x, y, z]) => new THREE.Vector3(x, y, z));
  return new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.4);
}

function Scene({ reduced }: { reduced: boolean }) {
  const group = useRef<THREE.Group>(null);
  const tube = useRef<THREE.Mesh>(null);
  const hit = useRef<THREE.Mesh>(null);
  const entry = useRef<THREE.Mesh>(null);
  const pointer = useRef({ x: 0, y: 0 });

  const curve = useMemo(() => makeCurve(), []);
  const geometry = useMemo(() => new THREE.TubeGeometry(curve, SEGMENTS, 0.04, RADIAL, false), [curve]);
  const indexCount = geometry.index?.count ?? 0;
  const entryAt = useMemo(() => curve.getPoint(0.43), [curve]);
  const hitAt = useMemo(() => curve.getPoint(1), [curve]);

  const chrome = useMemo(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: new THREE.Color("#e6e7ec"),
        metalness: 1,
        roughness: 0.18,
        clearcoat: 1,
        clearcoatRoughness: 0.08,
        envMapIntensity: 1.35,
      }),
    [],
  );
  const pink = useMemo(() => new THREE.MeshBasicMaterial({ color: "#ff4fa3", toneMapped: false }), []);

  useEffect(() => {
    if (reduced) return;
    const onMove = (e: PointerEvent) => {
      pointer.current.x = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.current.y = (e.clientY / window.innerHeight) * 2 - 1;
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [reduced]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    // 0..1 progress of the drawing; the whole path is shown at once when the
    // visitor asked for reduced motion.
    const p = reduced ? 1 : Math.min(Math.max((t - START_DELAY) / DRAW_SECONDS, 0), 1);
    const eased = p * p * (3 - 2 * p);
    const tri = Math.floor((indexCount * eased) / 3) * 3;
    if (tube.current) tube.current.geometry.setDrawRange(0, tri);
    if (entry.current) entry.current.visible = eased > 0.43;
    if (hit.current) {
      hit.current.visible = eased > 0.985;
      const since = Math.max(t - (START_DELAY + DRAW_SECONDS), 0);
      const s = reduced ? 1 : 1 + Math.max(0, 0.8 - since * 1.6) * 0.9;
      hit.current.scale.setScalar(s);
    }
    if (group.current) {
      if (reduced) {
        group.current.rotation.set(-0.08, -0.25, 0);
      } else {
        const targetY = -0.25 + Math.sin(t * 0.35) * 0.12 + pointer.current.x * 0.25;
        const targetX = -0.08 + pointer.current.y * -0.08;
        group.current.rotation.y += (targetY - group.current.rotation.y) * 0.05;
        group.current.rotation.x += (targetX - group.current.rotation.x) * 0.05;
      }
    }
  });

  return (
    <group ref={group}>
      <mesh ref={tube} geometry={geometry} material={chrome} />
      <mesh ref={entry} position={entryAt} material={chrome} visible={false}>
        <sphereGeometry args={[0.085, 24, 16]} />
      </mesh>
      <mesh ref={hit} position={hitAt} material={pink} visible={false}>
        <sphereGeometry args={[0.11, 24, 16]} />
      </mesh>

      {/* the stop: a translucent pink plane and a bright pink front edge */}
      <mesh position={[0, STOP_Y, 0.2]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[7.4, 2.6]} />
        <meshBasicMaterial color="#ff4fa3" transparent opacity={0.13} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh position={[0, STOP_Y, 1.5]} material={pink}>
        <boxGeometry args={[7.4, 0.018, 0.018]} />
      </mesh>
    </group>
  );
}

export function StopPathScene({ fallback }: { fallback: React.ReactNode }) {
  // Rendered only in a browser (loaded with ssr: false), so these checks run once.
  const [ok] = useState<boolean | null>(() => (typeof document === "undefined" ? null : webglAvailable()));
  const [reduced] = useState<boolean>(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );

  if (ok === null) return null;
  if (!ok) return <>{fallback}</>;

  return (
    <Canvas
      dpr={[1, 1.75]}
      camera={{ position: [0, 0.35, 6.4], fov: 34 }}
      frameloop={reduced ? "demand" : "always"}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      style={{ background: "transparent" }}
      aria-hidden="true"
    >
      <Suspense fallback={null}>
        <Studio />
        <Scene reduced={reduced} />
      </Suspense>
    </Canvas>
  );
}
