import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

const SUNSET_DATE = '2026-11-18';

// Phase 카드 정의 — 정본: Claude-Opus-bluevlad/services/llmops/README.md §로드맵
const PHASES = [
  {
    id: 'p1',
    code: 'Phase 1',
    title: '모델 인벤토리',
    status: 'done',
    summary: 'Ollama/MLX 자동 수집 → llm_models 테이블',
    deliverable: '/api/models, 인벤토리 화면',
    action: { type: 'internal', to: '/models', label: '인벤토리 열기 →' },
  },
  {
    id: 'p1.5',
    code: 'Phase 1.5 (α)',
    title: '표준 v0.2.0',
    status: 'done',
    summary: 'stages[].quality + paid-api provider + Sunset 재정의',
    deliverable: 'BATCH_RUN_REPORTING v0.2.0, LLM_INVENTORY v0.2.0',
    action: {
      type: 'external',
      to: 'https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/observability/BATCH_RUN_REPORTING.md',
      label: '표준 문서 →',
    },
  },
  {
    id: 'p2',
    code: 'Phase 2 (γ)',
    title: '무료 vs 유료 비교',
    status: 'active',
    summary: 'CLI 평행 실행 + LLM-as-judge → comparison_runs (UI 대기)',
    deliverable: 'scripts/run_comparison.py, scripts/generate_report.py',
    action: {
      type: 'external',
      to: 'https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/services/llmops/PHASE_2_DESIGN.md',
      label: '설계 문서 →',
    },
  },
  {
    id: 'p3',
    code: 'Phase 3 (β)',
    title: 'Consumer DB 통합',
    status: 'wait',
    summary: 'AllergyInsight DB read-only → 일일 학습 데이터 시계열',
    deliverable: 'corpus_snapshots 테이블, 자동 prompt sampling',
    action: { type: 'disabled', label: '설계 대기' },
  },
  {
    id: 'p4',
    code: 'Phase 4',
    title: '자동 인사이트 리포트',
    status: 'wait',
    summary: '월 1회 "모델 교체 권고" 마크다운 자동 생성',
    deliverable: 'nightly LLM-judge + reports/ 누적',
    action: { type: 'disabled', label: '데이터 60일 후' },
  },
  {
    id: 'p5',
    code: 'Phase 5 / 6',
    title: 'SDK + 시각화',
    status: 'wait',
    summary: 'shared/llmops_client.py + 모델↔서비스 매트릭스',
    deliverable: '4 consumer 계측, Pareto 차트',
    action: { type: 'disabled', label: '데이터 누적 후' },
  },
];

const STATUS_LABEL = { done: '✅ 완료', active: '🟡 진행', wait: '⏳ 대기' };

function daysUntil(yyyymmdd) {
  const target = new Date(yyyymmdd + 'T00:00:00Z');
  const diffMs = target.getTime() - Date.now();
  return Math.ceil(diffMs / (1000 * 60 * 60 * 24));
}

export default function HomePage() {
  const { user, logout } = useAuth();
  const [models, setModels] = useState(null);
  const [health, setHealth] = useState(null);

  useEffect(() => {
    api.get('/api/health').then((r) => setHealth(r.data)).catch(() => setHealth({ status: 'error' }));
    api.get('/api/models').then((r) => setModels(r.data)).catch(() => setModels([]));
  }, []);

  const sunsetDday = useMemo(() => daysUntil(SUNSET_DATE), []);
  const modelCount = Array.isArray(models) ? models.length : null;
  const activePhase = PHASES.find((p) => p.status === 'active');

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1>LLMOps</h1>
          <p className="subtitle">로컬 LLM 능력 측정 + paid API ROI 분석 (R&amp;D 플랫폼 v0.2.0)</p>
        </div>
        <div className="row-end">
          <span className={`health-dot ${health?.status === 'ok' ? 'ok' : 'err'}`}>●</span>
          <span className="muted small">backend {health?.status || '...'}</span>
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      <section>
        <h2>KPI</h2>
        <div className="kpi-row">
          <div className="kpi-card">
            <div className="kpi-label">등록 모델</div>
            <div className="kpi-value">{modelCount ?? '—'}</div>
            <div className="kpi-sub">Ollama + MLX 자동 수집</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">비교 실험</div>
            <div className="kpi-value">—</div>
            <div className="kpi-sub">CLI 산출 (UI 미구현)</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">진행 Phase</div>
            <div className="kpi-value sm">{activePhase?.code || '—'}</div>
            <div className="kpi-sub">{activePhase?.title || '—'}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Sunset 평가</div>
            <div className="kpi-value sm">D−{sunsetDday}</div>
            <div className="kpi-sub">{SUNSET_DATE} 평가 (KPI: 인사이트 산출량)</div>
          </div>
        </div>
      </section>

      <section>
        <h2>구현 로드맵</h2>
        <div className="phase-grid">
          {PHASES.map((p) => (
            <div key={p.id} className={`phase-card phase-${p.status}`}>
              <div className="phase-head">
                <span className={`status-badge badge-${p.status}`}>{STATUS_LABEL[p.status]}</span>
                <span className="phase-code">{p.code}</span>
              </div>
              <div className="phase-title">{p.title}</div>
              <div className="phase-summary">{p.summary}</div>
              <div className="phase-deliverable muted small">→ {p.deliverable}</div>
              <div className="phase-action">
                {p.action.type === 'internal' && (
                  <Link to={p.action.to}>{p.action.label}</Link>
                )}
                {p.action.type === 'external' && (
                  <a href={p.action.to} target="_blank" rel="noreferrer">
                    {p.action.label}
                  </a>
                )}
                {p.action.type === 'disabled' && (
                  <span className="muted small">— {p.action.label}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>참고 / 외부</h2>
        <ul>
          <li>
            정본: <a href="https://github.com/bluevlad/Claude-Opus-bluevlad/tree/main/services/llmops" target="_blank" rel="noreferrer">
              Claude-Opus-bluevlad/services/llmops/
            </a> (private — 로드맵·결정 이력·Phase 설계)
          </li>
          <li>
            코드: <a href="https://github.com/bluevlad/LLMOps" target="_blank" rel="noreferrer">bluevlad/LLMOps</a> (public)
          </li>
          <li>
            관련 서비스: <a href="https://infrawatcher.unmong.com/" target="_blank" rel="noreferrer">infrawatcher.unmong.com</a> (헬스체크/리소스 — 분석은 LLMOps, 관제는 InfraWatcher)
          </li>
        </ul>
      </section>
    </div>
  );
}
