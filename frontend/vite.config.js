import { resolve } from 'node:path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  // .env 는 저장소 루트(../)에 단일 출처로 둔다. Docker 빌드 시에는
  // build ARG → ENV VITE_GOOGLE_CLIENT_ID 로 process.env 를 통해 주입된다.
  const envDir = resolve(process.cwd(), '..');
  const env = loadEnv(mode, envDir, '');
  const proxyTarget =
    env.VITE_PROXY_TARGET || env.VITE_API_BASE_URL || 'http://localhost:9110';

  const allowedHostsEnv = (env.VITE_ALLOWED_HOSTS || '').trim();
  const allowedHosts = allowedHostsEnv
    ? allowedHostsEnv.split(',').map((s) => s.trim()).filter(Boolean)
    : ['localhost', '127.0.0.1', 'llmops.unmong.com'];

  return {
    envDir,
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
