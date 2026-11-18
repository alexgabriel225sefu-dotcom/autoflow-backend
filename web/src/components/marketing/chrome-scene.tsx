"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, Lightformer, useGLTF } from "@react-three/drei";
import * as THREE from "three";

/**
 * A product object as polished chrome, in 3D.
 *
 * The meshes were generated with Higgsfield (the A4 monogram from the logo with
 * Meshy 7, the others from a text prompt with Tripo), then stripped to geometry,
 * simplified and meshopt-compressed (150-270 KB each). The surface is not the baked
 * texture: it is a physical chrome material lit by an environment made of
 * three light panels (a soft white top, a pink strip on the left, a thin white
 * strip on the right), so the pink in the reflections is the brand pink and
 * nothing is fetched from a third-party HDRI host at run time.
 *
 * It moves a little: a slow sway, a response to the pointer, and a turn with
 * the scroll. With reduced motion it is drawn once and stays still.
 */

function Mark({ model, scale, reduced }: { model: string; scale: number; reduced: boolean }) {
  // Draco is switched off: the file uses meshopt, and the Draco decoder would
  // be downloaded from a third-party host.
  const gltf = useGLTF(model, false);
  const group = useRef<THREE.Group>(null);
  const pointer = useRef({ x: 0, y: 0 });

  const scene = useMemo(() => {
    const clone = gltf.scene.clone(true);
    const chrome = new THREE.MeshPhysicalMaterial({
      color: new THREE.Color("#e6e7ec"),
      metalness: 1,
      roughness: 0.2,
      clearcoat: 1,
      clearcoatRoughness: 0.08,
      envMapIntensity: 1.35,
    });
    clone.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.isMesh) mesh.material = chrome;
    });
    return clone;
  }, [gltf.scene]);

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
    const g = group.current;
    if (!g) return;
    if (reduced) {
      g.rotation.set(-0.08, -0.35, 0);
      return;
    }
    const t = state.clock.elapsedTime;
    const scroll = typeof window === "undefined" ? 0 : Math.min(window.scrollY, 1400);
    const targetY = Math.sin(t * 0.45) * 0.32 + pointer.current.x * 0.35 + scroll * 0.0016 - 0.3;
    const targetX = -0.08 + pointer.current.y * -0.12;
    g.rotation.y += (targetY - g.rotation.y) * 0.06;
    g.rotation.x += (targetX - g.rotation.x) * 0.06;
  });

  return (
    <group ref={group} scale={scale}>
      <primitive object={scene} />
    </group>
  );
}

function Studio() {
  return (
    <Environment resolution={256} frames={1}>
      {/* A dim grey room, so polished metal reflects something other than
          black where no light panel is: this is what makes it read as chrome. */}
      <mesh scale={30}>
        <sphereGeometry args={[1, 32, 16]} />
        <meshBasicMaterial color="#17171c" side={THREE.BackSide} />
      </mesh>
      {/* soft white top light: the broad highlight along the top edges */}
      <Lightformer form="rect" intensity={3} color="#ffffff" position={[0, 6, 3]} scale={[14, 3, 1]} />
      {/* brand pink strip on the left: the pink reflection in the chrome */}
      <Lightformer form="rect" intensity={4.5} color="#ff4fa3" position={[-6, 0.5, 3]} rotation-y={Math.PI / 2.6} scale={[7, 2, 1]} />
      {/* white strip on the right: the crisp edge */}
      <Lightformer form="rect" intensity={6} color="#ffffff" position={[6, 0.5, 2]} rotation-y={-Math.PI / 2.4} scale={[10, 1.2, 1]} />
      {/* front fill, low: keeps the faces from going flat black */}
      <Lightformer form="rect" intensity={0.8} color="#e9e4ea" position={[0, 3, 8]} scale={[16, 3, 1]} />
      {/* floor bounce */}
      <Lightformer form="rect" intensity={1.2} color="#ffd1e6" position={[0, -6, 2]} scale={[14, 2, 1]} />
    </Environment>
  );
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function ChromeScene({
  model,
  scale = 1.05,
  fallback,
}: {
  model: string;
  scale?: number;
  fallback: React.ReactNode;
}) {
  // This component is only ever rendered in a browser (it is loaded with
  // ssr: false), so the capability checks can run once, up front, and there is
  // no server markup for them to disagree with.
  const [ok] = useState<boolean | null>(() => (typeof document === "undefined" ? null : webglAvailable()));
  const [reduced] = useState<boolean>(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );

  if (ok === null) return null;
  if (!ok) return <>{fallback}</>;

  return (
    <Canvas
      dpr={[1, 1.75]}
      camera={{ position: [0, 0, 4.6], fov: 32 }}
      frameloop={reduced ? "demand" : "always"}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      style={{ background: "transparent" }}
      aria-hidden="true"
    >
      <Suspense fallback={null}>
        <Studio />
        <Mark model={model} scale={scale} reduced={reduced} />
      </Suspense>
    </Canvas>
  );
}
