import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import AlertsPanel from '../components/AlertsPanel.jsx';
import DiskAndEvents from '../components/DiskAndEvents.jsx';
import Sparkline from '../components/Sparkline.jsx';
import {
  ANOMALY_LABEL, LIFECYCLE_CLASS, ago, detailPath, fmtNum, formatBytes, formatMs, pct,
} from '../components/modelFormat.js';

const DAYS = 30;

function LiveBadge({ live, reachable }) {
  if (!reachable) return <span className="badge badge-muted" title="Ollama 도달 불가">확인 불가</span>;
  if (!live) return <span className="badge badge-muted">미로드</span>;
  return (
    <span
      className="badge badge-live"
      title={`상주 ${formatBytes(live.size_vram)} · ctx ${fmtNum(live.context_length)} · 만료 ${live.expires_at ? new Date(live.expires_at).toLocaleTimeString() : '-'}`}
    >
      ● 로드됨 {formatBytes(live.size_vram)}
    </span>
  );
}

function LifecycleBadge({ m }) {
  const cls = LIFECYCLE_CLASS[m.lifecycle] || 'lc-idle';
  let title = m.lifecycle_label;
  if (m.lifecycle === 'retire-candidate') title = '60일 호출 0 + 90일 비교 실험 0';
  if (m.lifecycle === 'uninstrumented') title = '임베딩 등 batch_runs 보고가 없는 경로 — 호출 0 이 미사용을 뜻하지 않음';
  if (m.lifecycle === 'deprecated' && m.replaced_by) title = `→ ${m.replaced_by}`;
  return <span className={`badge ${cls}`} title={title}>{m.lifecycle_label}</span>;
}

export default function ModelsPage() {
  const { user, logout } = useAuth();
  const [stats, setStats] = useState(null);
  const [live, setLive] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState(null);
  const [includeDeprecated, setIncludeDeprecated] = useState(false);
  const [family, setFamily] = useState('all');

  const load = useCallback(() => {
    setError(null);
    api.get('/api/models/stats', { params: { days: DAYS, include_deprecated: includeDeprecated } })
      .then((r) => setStats(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
    api.get('/api/models/live').then((r) => setLive(r.data)).catch(() => setLive(null));
    api.get('/api/models/anomalies', { params: { days: DAYS } })
      .then((r) => setAnomalies(r.data))
      .catch(() => setAnomalies(null));
  }, [includeDeprecated]);

  useEffect(() => { load(); }, [load]);

  // 상주 상태는 15초 서버 캐시 — 화면은 30초마다 갱신
  useEffect(() => {
    const t = setInterval(() => {
      api.get('/api/models/live').then((r) => setLive(r.data)).catch(() => {});
    }, 30_000);
    return () => clearInterval(t);
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    setRefreshResult(null);
    try {
      const { data } = await api.post('/api/models/refresh');
      setRefreshResult(data);
      load();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setRefreshing(false);
    }
  };

  const liveByModel = useMemo(() => {
    const m = new Map();
    (live?.models || []).forEach((x) => m.set(x.model_id, x));
    return m;
  }, [live]);

  const families = useMemo(() => {
    const set = new Set((stats?.models || []).map((m) => m.family || 'unknown'));
    return ['all', ...Array.from(set).sort()];
  }, [stats]);

  const rows = useMemo(() => {
    if (!stats) return null;
    return stats.models.filter((m) => family === 'all' || (m.family || 'unknown') === family);
  }, [stats, family]);

  const totals = useMemo(() => {
    if (!rows) return null;
    const t = { calls: 0, fails: 0, trunc: 0, loaded: 0, vram: 0, retire: 0 };
    rows.forEach((m) => {
      t.calls += m.calls; t.fails += m.fails; t.trunc += m.truncated;
      if (m.lifecycle === 'retire-candidate') t.retire += 1;
    });
    (live?.models || []).forEach((x) => { t.loaded += 1; t.vram += x.size_vram || 0; });
    return t;
  }, [rows, live]);

  const anomalySummary = useMemo(() => {
    if (!anomalies) return null;
    const byKind = {};
    anomalies.forEach((a) => { byKind[a.kind] = (byKind[a.kind] || 0) + a.count; });
    return byKind;
  }, [anomalies]);

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1><Link to="/">LLMOps</Link> · 모델 모니터링</h1>
          <p className="subtitle">설치된 로컬 LLM (Ollama + MLX) — 인벤토리 · 상주 상태 · 최근 {DAYS}일 사용 · 수명주기 · 관제 알림</p>
        </div>
        <div className="row-end">
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      {error && <section><pre className="error">{error}</pre></section>}

      <AlertsPanel isAdmin={user.role === 'llmops_admin'} />

      <section>
        <h2>요약 (최근 {DAYS}일)</h2>
        <div className="kpi-row">
          <div className="kpi-card">
            <div className="kpi-label">활성 모델</div>
            <div className="kpi-value">{rows ? rows.filter((m) => !m.deprecated_at).length : '—'}</div>
            <div className="kpi-sub">{totals && totals.retire > 0 ? <span className="warn-text">퇴출 후보 {totals.retire}</span> : '퇴출 후보 없음'}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">지금 로드됨</div>
            <div className="kpi-value">{live ? (live.reachable ? totals?.loaded ?? '—' : '?') : '—'}</div>
            <div className="kpi-sub">
              {live && !live.reachable ? <span className="err-text">Ollama 도달 불가</span> : `상주 ${formatBytes(totals?.vram || 0)}`}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">LLM 호출</div>
            <div className="kpi-value">{totals ? fmtNum(totals.calls) : '—'}</div>
            <div className="kpi-sub">
              실패 {totals?.fails ?? '—'} · 절단 {totals?.trunc ?? '—'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">이상 징후</div>
            <div className="kpi-value">{anomalies ? anomalies.length : '—'}</div>
            <div className="kpi-sub">
              {anomalySummary
                ? Object.entries(anomalySummary).slice(0, 3).map(([k, v]) => `${ANOMALY_LABEL[k] || k} ${v}`).join(' · ')
                : '—'}
            </div>
          </div>
        </div>
      </section>

      <section>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>모델 ({rows?.length ?? '…'})</h2>
          <div className="row-end filter-bar">
            <label className="small muted">
              <input
                type="checkbox"
                checked={includeDeprecated}
                onChange={(e) => setIncludeDeprecated(e.target.checked)}
              />
              {' '}deprecated 포함
            </label>
            <select value={family} onChange={(e) => setFamily(e.target.value)} className="select">
              {families.map((f) => <option key={f} value={f}>{f === 'all' ? '모든 패밀리' : f}</option>)}
            </select>
            <button onClick={refresh} disabled={refreshing}>
              {refreshing ? 'Refreshing…' : 'Refresh (수동 폴링)'}
            </button>
          </div>
        </div>

        {refreshResult && (
          <pre className="ok" style={{ marginBottom: 12 }}>
            Ollama: {refreshResult.ollama_upserted} 개 / MLX: {refreshResult.mlx_upserted} 개 갱신
          </pre>
        )}

        {rows && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Family / Param / Quant</th>
                  <th className="num">Size</th>
                  <th>상주</th>
                  <th>역할 · 소비자</th>
                  <th className="num">호출 {DAYS}d</th>
                  <th>추이 14d</th>
                  <th className="num">p50 / p95</th>
                  <th className="num">실패 · 절단</th>
                  <th>마지막 호출</th>
                  <th>수명주기</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => {
                  const lv = liveByModel.get(m.model_id);
                  const failPct = pct(m.fails, m.calls);
                  const truncPct = pct(m.truncated, m.calls);
                  return (
                    <tr key={`${m.provider}:${m.model_id}`} className={m.deprecated_at ? 'row-deprecated' : ''}>
                      <td>
                        <Link to={detailPath(m)}><strong>{m.model_id}</strong></Link>
                        <div className="muted small"><code>{m.provider}</code></div>
                      </td>
                      <td className="small">
                        {m.family || '-'} · {m.parameter_size || '-'} · {m.quantization || '-'}
                      </td>
                      <td className="num">{formatBytes(m.size_bytes)}</td>
                      <td><LiveBadge live={lv} reachable={live ? live.reachable : true} /></td>
                      <td className="small">
                        <div className="tags">
                          {m.role_tags.map((t) => <span key={t} className="tag">{t}</span>)}
                        </div>
                        <div className="muted">
                          {m.consumers.length > 0 ? `${m.consumers.length} consumer` : '없음'}
                        </div>
                      </td>
                      <td className="num">{fmtNum(m.calls)}</td>
                      <td><Sparkline values={m.daily_calls} /></td>
                      <td className="num small">{formatMs(m.p50_ms)} / {formatMs(m.p95_ms)}</td>
                      <td className="num small">
                        <span className={m.fails > 0 ? 'err-text' : ''}>{failPct != null ? `${failPct}%` : '-'}</span>
                        {' · '}
                        <span className={m.truncated > 0 ? 'warn-text' : ''}>{truncPct != null ? `${truncPct}%` : '-'}</span>
                      </td>
                      <td className="small" title={m.last_call_ever || ''}>{ago(m.last_call_ever)}</td>
                      <td><LifecycleBadge m={m} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {rows && rows.length === 0 && (
          <p className="muted">아직 수집된 모델 없음. Refresh 클릭 또는 잠시 후 새로고침.</p>
        )}
        {!rows && !error && <div className="loading">불러오는 중…</div>}

        <p className="muted small" style={{ marginTop: 10 }}>
          호출·지연·절단은 consumer 가 보고한 batch_run_stages 기준. "계측 밖" 은 임베딩처럼 보고 경로가 없는 모델.
          역할 태그는 llm_models.role_tags 가 비어 있으면 service-registry 스냅샷으로 채움.
          호스트 RAM/CPU 는 InfraWatcher 참조.
        </p>
      </section>

      <section>
        <h2>이상 징후 · 보고 계약 (최근 {DAYS}일)</h2>
        {!anomalies && <p className="muted">불러오는 중…</p>}
        {anomalies && anomalies.length === 0 && <p className="ok-text">이상 없음.</p>}
        {anomalies && anomalies.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>종류</th>
                <th>모델 (보고값)</th>
                <th>Consumer</th>
                <th className="num">건수</th>
                <th>마지막</th>
                <th>조치 힌트</th>
              </tr>
            </thead>
            <tbody>
              {anomalies.map((a, i) => (
                <tr key={i}>
                  <td><span className={`badge ${a.kind === 'stage_failed' || a.kind === 'unregistered_model' ? 'lc-retire' : 'lc-idle'}`}>{ANOMALY_LABEL[a.kind] || a.kind}</span></td>
                  <td><code>{a.model ?? 'NULL'}</code></td>
                  <td><code>{a.consumer_id}</code></td>
                  <td className="num">{a.count}</td>
                  <td className="small muted">{ago(a.last_seen_at)}</td>
                  <td className="small muted">{a.hint}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <DiskAndEvents />
    </div>
  );
}
