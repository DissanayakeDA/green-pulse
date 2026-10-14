import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Don't write AGENTS.md into the repo on `next dev`.
  agentRules: false,
  // This folder is the project root, even if a stray package-lock.json sits in a parent folder.
  turbopack: { root: __dirname },
};

export default nextConfig;
