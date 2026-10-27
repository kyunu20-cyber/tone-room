import type { NextConfig } from "next";

// 맥 앱 빌드(packaging/build.sh)는 정적 HTML로 내보내 백엔드가 같이 서빙한다.
// 정적 내보내기는 PPR(cacheComponents)을 못 써서 끄고, 설명서를 읽는 "use cache"는 useCache로 유지한다.
const EXPORT = !!process.env.TONEROOM_EXPORT;

const nextConfig: NextConfig = {
  cacheComponents: !EXPORT,
  partialPrefetching: !EXPORT,
  ...(EXPORT && {
    output: "export",
    distDir: ".next-export",
    images: { unoptimized: true },
    experimental: { useCache: true },
  }),
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
