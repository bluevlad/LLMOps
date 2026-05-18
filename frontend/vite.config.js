import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxyTarget =
    env.VITE_PROXY_TARGET || env.VITE_API_BASE_URL || 'http://localhost:9110';

  const allowedHostsEnv = (env.VITE_ALLOWED_HOSTS || '').trim();
  const allowedHosts = allowedHostsEnv
    ? allowedHostsEnv.split(',').map((s) => s.trim()).filter(Boolean)
    : ['localhost', '127.0.0.1', 'llmops.unmong.com'];

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 4110,
      allowedHosts,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
