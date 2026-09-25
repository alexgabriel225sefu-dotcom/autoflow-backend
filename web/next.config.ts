import path from "node:path";
import type { NextConfig } from "next";

/**
 * WHY `turbopack.root` IS SET EXPLICITLY
 *
 * This repository holds two products. The root carries its own package.json
 * and package-lock.json for the legacy Express sales site; this directory
 * carries the Next.js client's own. Turbopack walks upwards looking for a
 * workspace root, finds the root lockfile, and infers the repository root
 * rather than this directory — which changes how modules resolve and what the
 * build traces into its output.
 *
 * Next 16 warns about exactly this. Naming the root removes the ambiguity
 * instead of depending on which lockfile the inference happens to reach
 * first, and it does so without touching the other product's files.
 */
const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
