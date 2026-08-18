/** @type {import('next').NextConfig} */
const nextConfig = {
  // Docker 部署优化
  output: "standalone",

  // 开发环境 webpack 配置
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        poll: 1000,
        aggregateTimeout: 300,
      };
    }

    return config;
  },
};

module.exports = nextConfig;
