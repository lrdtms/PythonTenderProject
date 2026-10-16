import type { NextConfig } from "next";

// `npm run dev` without Docker: set API_PROXY_TARGET=http://127.0.0.1:8000 so /api/* reaches the
// API on the same origin (the session cookie is scoped to /api). Unset in Compose and in
// production builds: Caddy does the routing there (ADR-0009).
const apiProxyTarget = process.env.API_PROXY_TARGET;

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return apiProxyTarget
      ? [{ source: "/api/:path*", destination: `${apiProxyTarget}/api/:path*` }]
      : [];
  },
};

export default nextConfig;
