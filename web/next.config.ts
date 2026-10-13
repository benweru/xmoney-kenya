import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A static site in out/: S3 + CloudFront serve it on AWS, nginx in docker compose.
  output: "export",
  // /home/ → /home/index.html, which S3 and nginx can serve without per-route rewrites.
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
