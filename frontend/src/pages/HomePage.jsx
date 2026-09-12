import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

const SUNSET_DATE = '2026-11-18';
const DOCPIPELINE_ADMIN = 'https://docpipeline.unmong.com/admin';

// 관제 범위 — 정본: Ai-Legacy-bluevlad/services/llmops/MODEL_MONITOR_AGENT_PLAN.md §2
const SCOPE = [
  { title: '인벤토리', desc: 'Ollama /api/tags + MLX(HF cache) 자동 수집. 비활성화는 deprecated_at 마크만.' },
  { title: '상주 상태', desc: 'Ollama /api/ps — 지금 메모리에 올라온 모델 · VRAM · 만료 시각.' },
  { title: '사용 통계', desc: 'consumer 가 보고한 batch_runs 를 모델 단위로 집계 — 호출 · p95 · 토큰 · 실패율.' },
  { title: '수명주기', desc: '60일 미호출 + 90일 비교 0 → 퇴출 후보. 역할 슬롯(enrich/compose/…) 스냅샷.' },
  { title: '이상 징후', desc: '미등록 모델명 호출 · deprecated 모델 호출 · 보고 계약 위반 감지.' },
];

// 구현 플랜 v0.3.0 (M0~M3) — 정본 §7·§9
const PLAN = [
  { code: 'M0', title: '정본 문서', status: 'done', summary: '범위 한정 결정 · S2S 계약 · Sunset KPI 재정의' },
  { code: 'M1', title: 'S2S 읽기 키', status: 'done', summary: 'LLMOPS_READ_KEYS — DocPipeline 이 읽기 API 를 pull' },
  { code: 'M2', title: '파이프라인 뷰 이관', status: 'active', summary: 'Flow Map · 사용량 · 골든셋 · 비교 이력 → DocPipeline /admin' },
  { code: "M2'", title: 'LLMOps 축소', status: 'active', summary: '화면을 /models 로 한정, 홈은 모델 관제 개요' },
  { code: 'M3', title: '관제 강화', status: 'wait', summary: '상주 이탈 · 퇴출 후보 · 실패율 알림, 디스크 사용량, 인벤토리 변경 이력' },
];

const STATUS_LABEL = { done: '✅ 완료', active: '🟡 진행', wait: '⏳ 대기' };

function daysUntil(yyyymmdd) {
  const target = new Date(yyyymmdd + 'T00:00:00Z');
  return Math.ceil((target.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

export default function HomePage() {
  const { user, logout } = useAuth();
  const [health, setHealth] = useState(null);
  const [overview, setOverview] = useState(null);

  useEffect(() => {
    api.get('/api/health').then((r) => setHealth(r.data)).catch(() => setHealth({ status: 'error' }));
    // 공개 집계 API — 비로그인(read-only) 홈에서도 KPI 표시
    api.get('/api/public/overview').then((r) => setOverview(r.data)).catch(() => setOverview(null));
  }, []);

  const sunsetDday = useMemo(() => daysUntil(SUNSET_DATE), []);
  const kpi = overview?.kpi;
  const fmt = (v) => (v == null ? '—' : v.toLocaleString());

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1>LLMOps</h1>
          <p className="subtitle">MacBook 로컬 LLM 모델 관제 에이전트 (v0.3.0) — 인벤토리 · 상주 · 사용 · 수명주기 · 이상 징후</p>
        </div>
        <div className="row-end">
          <span className={`health-dot ${health?.status === 'ok' ? 'ok' : 'err'}`}>●</span>
          <span className="muted small">backend {health?.status || '...'}</span>
          {user ? (
            <>
              <span className="muted">{user.email} · <code>{user.role}</code></span>
              <button onClick={logout}>Logout</button>
            </>
          ) : (
            <Link to="/login"><button>관리자 로그인</button></Link>
          )}
        </div>
      </header>

      <section>
        <h2>모델 관제 KPI (최근 {overview?.days ?? 30}일)</h2>
        <div className="kpi-row">
          <div className="kpi-card">
            <div className="kpi-label">활성 모델</div>
            <div className="kpi-value">{fmt(kpi?.model_count)}</div>
            <div className="kpi-sub">Ollama + MLX 자동 수집</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">상주 모델</div>
            <div className="kpi-value">
              {overview && !overview.ollama_reachable ? <span className="err-text">—</span> : fmt(kpi?.resident_count)}
            </div>
            <div className="kpi-sub">
              {overview && !overview.ollama_reachable ? <span className="err-text">Ollama 도달 불가</span> : 'Ollama /api/ps 기준'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">LLM 호출</div>
            <div className="kpi-value">{fmt(kpi?.calls_30d)}</div>
            <div className="kpi-sub">batch_runs stage 단위</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">이상 징후</div>
            <div className="kpi-value">
              <span className={kpi?.anomaly_count_30d > 0 ? 'warn-text' : 'ok-text'}>{fmt(kpi?.anomaly_count_30d)}</span>
            </div>
            <div className="kpi-sub">{user ? <Link to="/models">모델 모니터링 →</Link> : '로그인 후 상세'}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Sunset 평가</div>
            <div className="kpi-value sm">D−{sunsetDday}</div>
            <div className="kpi-sub">{SUNSET_DATE} (KPI: 관제 조치 수)</div>
          </div>
        </div>
      </section>

      <section>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>관제 범위</h2>
          <div className="row-end small">
            {user ? <Link to="/models">모델 모니터링 열기 →</Link> : <Link to="/login">관리자 로그인 →</Link>}
          </div>
        </div>
        <div className="phase-grid">
          {SCOPE.map((s) => (
            <div key={s.title} className="phase-card phase-done">
              <div className="phase-title">{s.title}</div>
              <div className="phase-summary">{s.desc}</div>
            </div>
          ))}
        </div>
        <p className="muted small" style={{ marginTop: 10 }}>
          범위 밖: consumer 관점 파이프라인 뷰(Flow Map · 사용량 · 골든셋 큐레이션 · 비교 실험)는{' '}
          <a href={DOCPIPELINE_ADMIN} target="_blank" rel="noreferrer">DocPipeline 관리자 화면</a> 으로 이관.
          프로세스·컨테이너 헬스는 InfraWatcher.
        </p>
      </section>

      <section>
        <h2>구현 플랜 (v0.3.0)</h2>
        <div className="phase-grid">
          {PLAN.map((p) => (
            <div key={p.code} className={`phase-card phase-${p.status}`}>
              <div className="phase-head">
                <span className={`status-badge badge-${p.status}`}>{STATUS_LABEL[p.status]}</span>
                <span className="phase-code">{p.code}</span>
              </div>
              <div className="phase-title">{p.title}</div>
              <div className="phase-summary">{p.summary}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>참고 / 외부</h2>
        <ul>
          <li>
            정본: <a href="https://github.com/bluevlad/Ai-Legacy-bluevlad/tree/main/services/llmops" target="_blank" rel="noreferrer">
              Ai-Legacy-bluevlad/services/llmops/
            </a> (private — MODEL_MONITOR_AGENT_PLAN.md · 결정 이력)
          </li>
          <li>
            코드: <a href="https://github.com/bluevlad/LLMOps" target="_blank" rel="noreferrer">bluevlad/LLMOps</a> (public)
          </li>
          <li>
            파이프라인 뷰: <a href={DOCPIPELINE_ADMIN} target="_blank" rel="noreferrer">docpipeline.unmong.com/admin</a> (LLM 파이프라인 Flow Map · 사용량 · 골든셋 · 비교 이력)
          </li>
          <li>
            관련 서비스: <a href="https://infrawatcher.unmong.com/" target="_blank" rel="noreferrer">infrawatcher.unmong.com</a> (프로세스·컨테이너 헬스 — 모델 단위 관제는 LLMOps)
          </li>
        </ul>
      </section>
    </div>
  );
}
