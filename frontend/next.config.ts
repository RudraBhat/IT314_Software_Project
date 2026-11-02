import type { NextConfig } from "next";

const backendUrl = (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  experimental: { agentUpgrade: "security" },
  output: "standalone",
  async rewrites() {
    // Only the unauthenticated public API is exposed through the frontend origin.
    // Everything else goes through the BFF routes in src/app/api/*, which attach the session token.
    return [{ source: "/api/v1/public/:path*", destination: `${backendUrl}/api/v1/public/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
        ],
      },
    ];
  },
};

export default nextConfig;
