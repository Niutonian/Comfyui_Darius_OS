import type { NextConfig } from "next";

const backendUrl = (process.env.DARIUS_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  distDir: process.env.DARIUS_NEXT_DIST_DIR || ".next",
  reactStrictMode: true,
  allowedDevOrigins: ["localhost", "127.0.0.1", ...(process.env.DARIUS_ALLOWED_DEV_ORIGINS ?? "").split(",").map(value => value.trim()).filter(Boolean)],
  // Let the assistant's 180-second client deadline handle long model/tool turns.
  experimental: { proxyTimeout: 320_000 },
  async rewrites() {
    return [
      {
        source: "/api/darius/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
