/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Images come from the API on another origin and are already small JPEGs.
  images: { unoptimized: true },
};

export default nextConfig;
