/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'https://autoflow-backend-production-9b95.up.railway.app',
  },
};

module.exports = nextConfig;
