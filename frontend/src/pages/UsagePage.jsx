import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, Legend,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

// 다크 서피스용 카테고리 팔레트 슬롯 1·2·3 (validate_palette dark 통과)
const C_IN = '#3987e5';
const C_OUT = '#199e70';
const C_GOLD = '#9a5fe0';
const INK_MUTED = '#898781';
const GRID = '#2a2e38';

const tooltipStyle = {
  backgroundColor: '#0a0c10',
  border: '1px solid #2a2e38',
  borderRadius: 4,
  fontSize: 12,
};

function fmtNum(n) {
  if (n == null) return '-';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

const RANGES = [
  { days: 30, granularity: 'day', label: '최근 30일 (일별)' },
  { days: 90, granularity: 'day', label: '최근 90일 (일별)' },
  { days: 365, granularity: 'month', label: '최근 1년 (월별)' },
];

export default function UsagePage() {
  const { user, logout } = useAuth();
  const [rangeIdx, setRangeIdx] = useState(0);
  const [data, setData] = useState(null);
  const [accum, setAccum] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const { days, granularity } = RANGES[rangeIdx];
    setData(null);
    setAccum(null);
    api.get('/api/usage', { params: { days, granularity } })
      .then((r) => setData(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
    api.get('/api/usage/accumulation', { params: { days, granularity } })
      .then((r) => setAccum(r.data))
      .catch(() => setAccum(null)); // 축적 데이터는 선택적 — 실패해도 페이지 유지
  }, [rangeIdx]);

  const accumSeries = useMemo(() => {
    if (!accum) return [];
    return accum.series.map((b) => ({ bucket: b.bucket, ...b.values }));
  }, [accum]);
  const hasAccum = accum && accum.series.length > 0
    && Object.values(accum.totals).some((v) => v > 0);

  const totals = useMemo(() => {
    if (!data) return null;
    const t = { runs: 0, ok: 0, stages: 0, tin: 0, tout: 0, up: 0, down: 0 };
    data.series.forEach((b) => {
      t.runs += b.runs; t.ok += b.runs_success; t.stages += b.stages;
      t.tin += b.tokens_in; t.tout += b.tokens_out;
      t.up += b.feedback_up; t.down += b.feedback_down;
    });
    return t;
  }, [data]);

  const successRate = totals && totals.runs > 0
    ? Math.round((totals.ok / totals.runs) * 100) : null;
  const hasFeedback = totals && (totals.up + totals.down) > 0;

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1><Link to="/">LLMOps</Link> · 사용량 통계</h1>
          <p className="subtitle">토큰 사용량 · LLM 호출 · 배치 성공률 · 사용자 피드백</p>
        </div>
        <div className="row-end">
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      {error && <section><pre className="error">{error}</pre></section>}

      <section>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>기간</h2>
          <select
            value={rangeIdx}
            onChange={(e) => setRangeIdx(Number(e.target.value))}
            style={{ background: '#0a0c10', color: '#e6e6e6', border: '1px solid #2a2e38', borderRadius: 4, padding: '6px 10px', fontSize: 13 }}
          >
            {RANGES.map((r, i) => <option key={r.label} value={i}>{r.label}</option>)}
          </select>
        </div>

        <div className="kpi-row">
          <div className="kpi-card">
            <div className="kpi-label">토큰 사용량</div>
            <div className="kpi-value">{totals ? fmtNum(totals.tin + totals.tout) : '—'}</div>
            <div className="kpi-sub">in {totals ? fmtNum(totals.tin) : '—'} · out {totals ? fmtNum(totals.tout) : '—'}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">LLM 호출</div>
            <div className="kpi-value">{totals ? fmtNum(totals.stages) : '—'}</div>
            <div className="kpi-sub">배치 실행 {totals ? fmtNum(totals.runs) : '—'}건</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">배치 성공률</div>
            <div className="kpi-value">{successRate != null ? `${successRate}%` : '—'}</div>
            <div className="kpi-sub">{totals ? `${totals.ok}/${totals.runs} 성공` : '—'}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">사용자 피드백</div>
            <div className="kpi-value sm">
              {hasFeedback ? `👍 ${totals.up} · 👎 ${totals.down}` : '수집 전'}
            </div>
            <div className="kpi-sub">
              {hasFeedback ? 'quality_judge=user-feedback' : 'consumer UI 연동 필요'}
            </div>
          </div>
        </div>
      </section>

      {data && (
        <>
          <section>
            <h2>토큰 사용량 ({data.granularity === 'day' ? '일별' : '월별'})</h2>
            {data.series.length === 0 ? (
              <p className="muted">기간 내 데이터 없음.</p>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={data.series} margin={{ top: 8, right: 16, left: -8, bottom: 0 }} barGap={2}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="bucket" tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} />
                  <YAxis tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} tickFormatter={fmtNum} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="tokens_in" name="tokens in" fill={C_IN} radius={[4, 4, 0, 0]} maxBarSize={28} />
                  <Bar dataKey="tokens_out" name="tokens out" fill={C_OUT} radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </section>

          <section>
            <h2>LLM 호출 횟수 ({data.granularity === 'day' ? '일별' : '월별'})</h2>
            {data.series.length === 0 ? (
              <p className="muted">기간 내 데이터 없음.</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.series} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="bucket" tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} />
                  <YAxis tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                  <Bar dataKey="stages" name="LLM 호출" fill={C_IN} radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </section>

          <section>
            <h2>수집·축적 추이 ({data.granularity === 'day' ? '일별' : '월별'})</h2>
            {!hasAccum ? (
              <p className="muted">
                기간 내 축적 metrics 없음 — consumer 가 §2-γ 키(items_ingested, corpus_added,
                golden_added 등)를 보고하면 채워집니다.
              </p>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={accumSeries} margin={{ top: 8, right: 16, left: -16, bottom: 0 }} barGap={2}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="bucket" tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} />
                    <YAxis tick={{ fill: INK_MUTED, fontSize: 11 }} stroke={GRID} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="items_ingested" name="신규 수집" fill={C_IN} radius={[4, 4, 0, 0]} maxBarSize={24} />
                    <Bar dataKey="corpus_added" name="RAG corpus 축적" fill={C_OUT} radius={[4, 4, 0, 0]} maxBarSize={24} />
                    <Bar dataKey="golden_added" name="골든셋 확정" fill={C_GOLD} radius={[4, 4, 0, 0]} maxBarSize={24} />
                  </BarChart>
                </ResponsiveContainer>
                <table style={{ marginTop: 12 }}>
                  <thead>
                    <tr>
                      <th>Consumer</th>
                      <th className="num">크롤</th>
                      <th className="num">신규 수집</th>
                      <th className="num">corpus 축적</th>
                      <th className="num">골든 후보</th>
                      <th className="num">골든 확정</th>
                      <th className="num">승인 / 반려 / 보류</th>
                    </tr>
                  </thead>
                  <tbody>
                    {accum.by_consumer.map((c) => (
                      <tr key={c.consumer_id}>
                        <td><code>{c.consumer_id}</code></td>
                        <td className="num">{fmtNum(c.values.items_crawled)}</td>
                        <td className="num">{fmtNum(c.values.items_ingested)}</td>
                        <td className="num">{fmtNum(c.values.corpus_added)}</td>
                        <td className="num">{fmtNum(c.values.golden_candidates)}</td>
                        <td className="num">{fmtNum(c.values.golden_added)}</td>
                        <td className="num">
                          {c.values.review_approved} / {c.values.review_rejected} / {c.values.review_abstained}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </section>

          <section>
            <h2>Consumer 별 사용량</h2>
            <table>
              <thead>
                <tr>
                  <th>Consumer</th>
                  <th className="num">배치 실행</th>
                  <th className="num">LLM 호출</th>
                  <th className="num">tokens in</th>
                  <th className="num">tokens out</th>
                </tr>
              </thead>
              <tbody>
                {data.by_consumer.map((c) => (
                  <tr key={c.consumer_id}>
                    <td><code>{c.consumer_id}</code></td>
                    <td className="num">{c.runs}</td>
                    <td className="num">{c.stages}</td>
                    <td className="num">{fmtNum(c.tokens_in)}</td>
                    <td className="num">{fmtNum(c.tokens_out)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small" style={{ marginTop: 8 }}>
              토큰이 0인 consumer 는 계측 미비 (AllergyInsight 챗 = duration 만 보고,
              kin-pipeline = stage 단위 집계라 토큰 생략). SkillRadar 는 2026-07-25 부터
              실측 토큰 보고.
            </p>
          </section>
        </>
      )}

      {!data && !error && <div className="loading">불러오는 중…</div>}
    </div>
  );
}
