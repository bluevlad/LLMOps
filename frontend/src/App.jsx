import { useEffect, useState } from 'react';

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>LLMOps</h1>
        <p className="subtitle">로컬 LLM 사용 현황·ROI 통합 관제</p>
      </header>

      <section className="status">
        <h2>Backend 상태</h2>
        {error && <pre className="error">에러: {error}</pre>}
        {!error && !health && <p>로딩 중…</p>}
        {health && (
          <pre>{JSON.stringify(health, null, 2)}</pre>
        )}
      </section>

      <section className="roadmap">
        <h2>Phase 1a — Foundation</h2>
        <ul>
          <li>✅ Repo 골격 + 도메인 등록 (llmops.unmong.com, 4110/9110)</li>
          <li>✅ README + Sunset Criteria (2026-11-18 평가)</li>
          <li>⏳ Phase 1b: DDL + OAuth + /api/models + /api/batch-runs</li>
          <li>⏳ Phase 1c: React 모델 인벤토리 탭</li>
        </ul>
      </section>
    </div>
  );
}
