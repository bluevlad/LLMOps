import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

export default function HomePage() {
  const { user, logout } = useAuth();
  const [health, setHealth] = useState(null);

  useEffect(() => {
    api.get('/api/health').then((r) => setHealth(r.data)).catch(() => setHealth(null));
  }, []);

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1>LLMOps</h1>
          <p className="subtitle">로컬 LLM 사용 현황·ROI 통합 관제</p>
        </div>
        <div className="row-end">
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      <section>
        <h2>Backend</h2>
        {health
          ? <pre>{JSON.stringify(health, null, 2)}</pre>
          : <p className="muted">로딩…</p>}
      </section>

      <section>
        <h2>화면</h2>
        <ul>
          <li><Link to="/models">모델 인벤토리</Link> — Ollama + MLX 자동 수집</li>
        </ul>
      </section>

      <section>
        <h2>Phase 진행 상황</h2>
        <ul>
          <li>✅ Phase 1a — Foundation (도메인 + 골격 + Sunset criteria)</li>
          <li>✅ Phase 1b — Backend (DDL + OAuth + 폴러 + /api/batch-runs)</li>
          <li>🟡 Phase 1c — Frontend (현재)</li>
          <li>⏳ Phase 2 — 계측 SDK 배포 (4개 서비스)</li>
          <li>⏳ Phase 3 — 시각화 (데이터 30일 후)</li>
        </ul>
      </section>
    </div>
  );
}
