import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import {
  ANOMALY_LABEL, LIFECYCLE_CLASS, ago, fmtNum, formatBytes, formatDate, formatMs, pct,
} from '../components/modelFormat.js';

// UsagePage 와 동일한 다크 서피스 팔레트
const C_IN = '#3987e5';
const C_OUT = '#199e70';
const C_WARN = '#e0a03a';
const C_ERR = '#e05a5a';
const INK_MUTED = '#898781';
const GRID = '#2a2e38';
const tooltipStyle = { backgroundColor: '#0a0c10', border: '1px solid #2a2e38', borderRadius: 4, fontSize: 12 };

const RANGES = [
  { days: 7, label: '최근 7일' },
  { days: 30, label: '최근 30일' },
  { days: 90, label: '최근 90일' },
];

function Kpi({ label, value, sub, tone }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone || ''}`}>{value}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}

export default function ModelDetailPage() {
  const { user, logout } = useAuth();
  const params = useParams();
  const provider = decodeURIComponent(params.provider || '');
  const modelId = decodeURIComponent(params['*'] || '');

  const [rangeIdx, setRangeIdx] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.get('/api/models/detail', { params: { provider, model_id: modelId, days: RANGES[rangeIdx].days } })
      .then((r) => setData(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, [provider, modelId, rangeIdx]);

  const m = data?.model;
  const failPct = m ? pct(m.fails, m.calls) : null;
  const truncPct = m ? pct(m.truncated, m.calls) : null;

  const series = useMemo(() => (data?.series || []).map((p) => ({
    ...p,
    p50_s: p.p50_ms != null ? +(p.p50_ms / 1000).toFixed(1) : null,
    p95_s: p.p95_ms != null ? +(p.p95_ms / 1000).toFixed(1) : null,
  })), [data]);

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1>
            <Link to="/">LLMOps</Link> · <Link to="/models">모델</Link> · {modelId || '…'}
          </h1>
          <p className="subtitle">
            {m ? `${m.provider} · ${m.family || '-'} · ${m.parameter_size || '-'} · ${m.quantization || '-'} · ${formatBytes(m.size_bytes)}` : '모델 상세'}
          </p>
        </div>
        <div className="row-end">
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      {error && <section><pre className="error">{error}</pre></section>}
      {!data && !error && <div className="loading">불러오는 중…</div>}

      {m && (
        <>
          {/* 1. 헤더: 상태 · 상주 · 역할 */}
          <section>
            <div className="row" style={{ marginBottom: 12 }}>
              <h2 style={{ margin: 0 }}>상태</h2>
              <select value={rangeIdx} onChange={(e) => setRangeIdx(Number(e.target.value))} className="select">
                {RANGES.map((r, i) => <option key={r.days} value={i}>{r.label}</option>)}
              </select>
            </div>
            <div className="detail-grid">
              <div className="detail-card">
                <div className="kpi-label">수명주기</div>
                <div style={{ marginTop: 6 }}>
                  <span className={`badge ${LIFECYCLE_CLASS[m.lifecycle] || 'lc-idle'}`}>{m.lifecycle_label}</span>
                </div>
                <dl className="kv" style={{ marginTop: 10 }}>
                  <dt>마지막 호출</dt><dd title={m.last_call_ever || ''}>{ago(m.last_call_ever)}</dd>
                  <dt>마지막 비교</dt><dd title={m.last_comparison_at || ''}>{ago(m.last_comparison_at)} ({m.comparison_runs} run)</dd>
                  <dt>adopted</dt><dd>{m.adopted_at || '-'}</dd>
                  <dt>deprecated</dt><dd>{m.deprecated_at ? `${m.deprecated_at}${m.replaced_by ? ` → ${m.replaced_by}` : ''}` : '-'}</dd>
                </dl>
              </div>

              <div className="detail-card">
                <div className="kpi-label">상주 (Ollama /api/ps)</div>
                {!data.live_reachable && <div className="err-text" style={{ marginTop: 6 }}>Ollama 도달 불가</div>}
                {data.live_reachable && !data.live && <div className="muted" style={{ marginTop: 6 }}>미로드 — 다음 호출 시 로드</div>}
                {data.live && (
                  <dl className="kv" style={{ marginTop: 6 }}>
                    <dt>상주 메모리</dt><dd><strong>{formatBytes(data.live.size_vram)}</strong> / {formatBytes(data.live.size_bytes)}</dd>
                    <dt>context</dt><dd>{fmtNum(data.live.context_length)}</dd>
                    <dt>만료</dt><dd>{formatDate(data.live.expires_at)}</dd>
                  </dl>
                )}
                <p className="muted small" style={{ marginTop: 8 }}>
                  호스트 RAM/CPU 는 <a href="https://infrawatcher.unmong.com/" target="_blank" rel="noreferrer">InfraWatcher</a>.
                  MLX 러너는 num_ctx 를 무시하므로 context 는 참고값.
                </p>
              </div>

              <div className="detail-card">
                <div className="kpi-label">역할 · 소비자</div>
                <div className="tags" style={{ marginTop: 6 }}>
                  {m.role_tags.length === 0 && <span className="muted">-</span>}
                  {m.role_tags.map((t) => <span key={t} className="tag">{t}</span>)}
                </div>
                <ul className="small" style={{ marginTop: 8 }}>
                  {m.roles.map((r, i) => (
                    <li key={i}>
                      <code>{r.consumer_id || '(consumer 없음)'}</code> · {r.role}
                      {!r.instrumented && <span className="muted"> · 계측 밖</span>}
                      {r.note && <div className="muted">{r.note}</div>}
                    </li>
                  ))}
                  {m.consumers.filter((c) => !m.roles.some((r) => r.consumer_id === c)).map((c) => (
                    <li key={c}><code>{c}</code> · <span className="warn-text">스냅샷 밖 (관측됨)</span></li>
                  ))}
                </ul>
                {m.notes && <p className="muted small" style={{ marginTop: 6 }}>{m.notes}</p>}
              </div>
            </div>
          </section>

          {/* 2. KPI */}
          <section>
            <h2>사용 KPI ({RANGES[rangeIdx].label})</h2>
            <div className="kpi-row kpi-row-6">
              <Kpi label="LLM 호출" value={fmtNum(m.calls)} sub={`${m.consumer_count} consumer`} />
              <Kpi label="p50 / p95 지연" value={<span className="sm">{formatMs(m.p50_ms)} / {formatMs(m.p95_ms)}</span>} sub={`평균 ${formatMs(m.avg_ms)}`} />
              <Kpi label="실패율" value={failPct != null ? `${failPct}%` : '—'} sub={`${m.fails} / ${m.calls}`} tone={m.fails > 0 ? 'err-text' : ''} />
              <Kpi label="절단율" value={truncPct != null ? `${truncPct}%` : '—'} sub={`content_truncated ${m.truncated}`} tone={m.truncated > 0 ? 'warn-text' : ''} />
              <Kpi label="tokens in" value={fmtNum(m.tokens_in)} sub={m.tokens_in == null ? '미보고' : '보고값 합'} />
              <Kpi label="tokens out" value={fmtNum(m.tokens_out)} sub={m.tokens_out == null ? '미보고' : '보고값 합'} />
            </div>
          </section>

          {/* 3. consumer × stage 분해 */}
          <section>
            <h2>Consumer × Stage 분해</h2>
            {data.breakdown.length === 0 ? (
              <p className="muted">기간 내 호출 없음.</p>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Consumer</th>
                      <th>Stage</th>
                      <th className="num">호출</th>
                      <th className="num">실패</th>
                      <th className="num">avg</th>
                      <th className="num">p95</th>
                      <th className="num">tokens in / out</th>
                      <th className="num">절단</th>
                      <th className="num">품질</th>
                      <th>마지막</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.breakdown.map((r, i) => (
                      <tr key={i}>
                        <td><code>{r.consumer_id}</code></td>
                        <td>{r.stage_name || '-'}</td>
                        <td className="num">{fmtNum(r.calls)}</td>
                        <td className={`num ${r.fails > 0 ? 'err-text' : ''}`}>{r.fails}</td>
                        <td className="num">{formatMs(r.avg_ms)}</td>
                        <td className="num">{formatMs(r.p95_ms)}</td>
                        <td className="num">{fmtNum(r.tokens_in)} / {fmtNum(r.tokens_out)}</td>
                        <td className={`num ${r.truncated > 0 ? 'warn-text' : ''}`}>{r.truncated}</td>
                        <td className="num">{r.avg_quality ?? '-'}</td>
                        <td className="small muted" title={r.last_call_at || ''}>{ago(r.last_call_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* 4. 시계열 */}
          <section>
            <h2>일별 호출 · 실패 · 절단</h2>
            {series.length === 0 ? <p className="muted">기간 내 데이터 없음.</p> : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={series} margin={{ top: 8, right: 16, left: -16, bottom: 0 }} barGap={2}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="bucket" tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} />
                  <YAxis tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="calls" name="호출" fill={C_IN} radius={[4, 4, 0, 0]} maxBarSize={24} />
                  <Bar dataKey="fails" name="실패" fill={C_ERR} radius={[4, 4, 0, 0]} maxBarSize={24} />
                  <Bar dataKey="truncated" name="절단" fill={C_WARN} radius={[4, 4, 0, 0]} maxBarSize={24} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </section>

          <section>
            <h2>일별 지연 p50 / p95 (초)</h2>
            {series.length === 0 ? <p className="muted">기간 내 데이터 없음.</p> : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={series} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="bucket" tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} />
                  <YAxis tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="p50_s" name="p50 (s)" stroke={C_OUT} dot={false} strokeWidth={2} connectNulls />
                  <Line type="monotone" dataKey="p95_s" name="p95 (s)" stroke={C_WARN} dot={false} strokeWidth={2} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            )}
          </section>

          {/* 5. 품질 · 비교 · 골든셋 */}
          <section>
            <h2>품질 · 비교 실험 · 골든셋</h2>
            <div className="detail-grid">
              <div className="detail-card">
                <div className="kpi-label">운영 품질 (quality_score, judge 별)</div>
                {data.quality.length === 0 ? <p className="muted small">보고된 quality 없음.</p> : (
                  <table style={{ marginTop: 6 }}>
                    <thead><tr><th>judge</th><th className="num">n</th><th className="num">평균</th></tr></thead>
                    <tbody>
                      {data.quality.map((q) => (
                        <tr key={q.judge}><td><code>{q.judge}</code></td><td className="num">{q.n}</td><td className="num">{q.avg}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="detail-card">
                <div className="kpi-label">골든셋 (이 모델 응답 출처)</div>
                <dl className="kv" style={{ marginTop: 6 }}>
                  <dt>후보</dt><dd>{data.golden_set.candidate}</dd>
                  <dt>승인</dt><dd className="ok-text">{data.golden_set.approved}</dd>
                  <dt>반려</dt><dd>{data.golden_set.rejected}</dd>
                </dl>
                <p className="small" style={{ marginTop: 8 }}><Link to="/golden-set">골든셋 큐레이션 →</Link></p>
              </div>
            </div>

            <h3 className="sub-h">비교 실험 참여 이력 (전체 기간)</h3>
            {data.comparisons.length === 0 ? <p className="muted small">참여한 비교 실험 없음.</p> : (
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Case</th>
                    <th>Judge</th>
                    <th>일시</th>
                    <th className="num">순위</th>
                    <th className="num">품질</th>
                    <th className="num">승률</th>
                    <th className="num">avg</th>
                    <th className="num">n</th>
                  </tr>
                </thead>
                <tbody>
                  {data.comparisons.map((c) => (
                    <tr key={c.id}>
                      <td><Link to="/comparisons">#{c.id}</Link></td>
                      <td>{c.case_name}<div className="muted small">{c.prompt_set_id}</div></td>
                      <td className="small"><code>{c.judge_model || '-'}</code></td>
                      <td className="small muted">{formatDate(c.started_at)}</td>
                      <td className={`num ${c.rank === 1 ? 'ok-text' : ''}`}>{c.rank} / {c.model_count}</td>
                      <td className="num">{c.avg_quality ?? '-'}</td>
                      <td className="num">{c.win_rate != null ? `${Math.round(c.win_rate * 100)}%` : '-'}</td>
                      <td className="num">{formatMs(c.avg_duration_ms)}</td>
                      <td className="num">{c.result_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* 6. 이상 징후 */}
          <section>
            <h2>이상 징후 · 보고 계약 (이 모델)</h2>
            {data.anomalies.length === 0 ? <p className="ok-text">이상 없음.</p> : (
              <table>
                <thead>
                  <tr><th>종류</th><th>Consumer</th><th className="num">건수</th><th>마지막</th><th>조치 힌트</th></tr>
                </thead>
                <tbody>
                  {data.anomalies.map((a, i) => (
                    <tr key={i}>
                      <td><span className={`badge ${a.kind === 'stage_failed' ? 'lc-retire' : 'lc-idle'}`}>{ANOMALY_LABEL[a.kind] || a.kind}</span></td>
                      <td><code>{a.consumer_id}</code></td>
                      <td className="num">{a.count}</td>
                      <td className="small muted">{ago(a.last_seen_at)}</td>
                      <td className="small muted">{a.hint}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="muted small" style={{ marginTop: 10 }}>
              분기 리포트 초안(<code>models/{'{model_id}'}-report-YYYYQQ.md</code>)은 이 화면의 KPI·분해·비교 이력을 근거로 작성한다 —
              Sunset 평가(2026-11-18) KPI 는 리포트 산출량.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
