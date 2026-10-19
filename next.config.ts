import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // /api/buildings reads the OSM building list from disk; serverless bundles don't include
  // public/ automatically, so trace it into the function explicitly.
  outputFileTracingIncludes: {
    "/api/buildings": ["./public/models/dartmouth-energy-twin/reports/osm-campus-names.json"],
  },
  async redirects() {
    // the standalone scene was previewed here before it replaced the Cesium view
    return [{ source: "/preview", destination: "/", permanent: false }];
  },
  async headers() {
    // when several rules set the same header, the last matching rule wins
    return [
      {
        // unversioned scene data: cache briefly, revalidate in the background
        source: "/models/dartmouth-campus/:file*",
        headers: [{ key: "Cache-Control", value: "public, max-age=3600, stale-while-revalidate=86400" }],
      },
      {
        // requested with ?v=<content hash> from campus-terrain.json, so safe to cache forever
        source: "/models/dartmouth-campus/terrain/:file(.*\\.(?:bin|jpg))",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
