import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, LabelList, Legend,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

// 카테고리 팔레트 (다크 서피스용 — CVD 검증된 고정 순서, 순환 금지)
const SERIES_COLORS = [
  '#3987e5', '#199e70', '#c98500', '#008300',
  '#9085e9', '#e66767', '#d55181', '#d95926',
];
const INK_MUTED = '#898781';
const GRID = '#2a2e38';

function fmtMs(ms) {
  if (ms == null) return '-';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}
function fmtPct(v) {
  return v == null ? '-' : `${Math.round(v * 100)}%`;
}
function fmtCost(v) {
  if (v == null) return '무료 (로컬)';
  return `$${v.toFixed(4)}`;
}

const tooltipStyle = {
  backgroundColor: '#0a0c10',
  border: '1px solid #2a2e38',
  borderRadius: 4,
  fontSize: 12,
};

export default function ComparisonsPage() {
  const { user, logout } = useAuth();
  const [runs, setRuns] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get('/api/comparisons')
      .then((r) => {
        setRuns(r.data);
        if (r.data.length > 0) setSelectedId(r.data[0].id);
      })
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, []);

  useEffect(() => {
    if (selectedId == null) return;
    setDetail(null);
    api.get(`/api/comparisons/${selectedId}`)
      .then((r) => setDetail(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, [selectedId]);

  // 색은 순위가 아닌 모델(엔티티)을 따라감 — model_id 사전순으로 슬롯 고정
  const colorByModel = useMemo(() => {
    if (!detail) return {};
    const keys = detail.aggregates.map((a) => a.model_id).sort();
    return Object.fromEntries(keys.map((k, i) => [k, SERIES_COLORS[i % SERIES_COLORS.length]]));
  }, [detail]);

  // 차원별 grouped bar 데이터: [{dimension, <model>: score, ...}]
  const dimensionRows = useMemo(() => {
    if (!detail) return [];
    const dims = [...new Set(detail.aggregates.flatMap((a) => Object.keys(a.dimensions)))];
    return dims.map((dim) => {
      const row = { dimension: dim };
      detail.aggregates.forEach((a) => { row[a.model_id] = a.dimensions[dim] ?? null; });
      return row;
    });
  }, [detail]);

  // 품질 vs 응답시간 산점 (모델별 집계 1점)
  const paretoPoints = useMemo(() => {
    if (!detail) return [];
    return detail.aggregates
      .filter((a) => a.avg_quality != null && a.avg_duration_ms != null)
      .map((a) => ({
        model: a.model_id,
        duration_s: +(a.avg_duration_ms / 1000).toFixed(2),
        quality: a.avg_quality,
      }));
  }, [detail]);

  const selectedRun = runs?.find((r) => r.id === selectedId);

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1><Link to="/">LLMOps</Link> · 교사후보 평가</h1>
          <p className="subtitle">모델 비교 실험 스코어보드 — LLM-as-judge 품질 · 속도 · 비용</p>
        </div>
        <div className="row-end">
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      {error && <section><pre className="error">{error}</pre></section>}

      {runs && runs.length === 0 && (
        <section>
          <p className="muted">
            아직 비교 실험 데이터가 없습니다. <code>backend/scripts/run_comparison.py</code> 로
            실험을 실행하면 여기에 결과가 표시됩니다.
          </p>
        </section>
      )}

      {runs && runs.length > 0 && (
        <section>
          <div className="row" style={{ marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>실험 선택</h2>
            <select
              value={selectedId ?? ''}
              onChange={(e) => setSelectedId(Number(e.target.value))}
              style={{ background: '#0a0c10', color: '#e6e6e6', border: '1px solid #2a2e38', borderRadius: 4, padding: '6px 10px', fontSize: 13 }}
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  #{r.id} {r.case_name} · {new Date(r.started_at).toLocaleDateString()}
                </option>
              ))}
            </select>
          </div>
          {selectedRun && (
            <dl className="kv">
              <dt>프롬프트 셋</dt><dd><code>{selectedRun.prompt_set_id}</code></dd>
              <dt>Judge 모델</dt><dd>{selectedRun.judge_model || '-'}</dd>
              <dt>규모</dt>
              <dd>프롬프트 {selectedRun.prompt_count} × 모델 {selectedRun.model_count} = 결과 {selectedRun.result_count}</dd>
              {selectedRun.note && (<><dt>노트</dt><dd>{selectedRun.note}</dd></>)}
            </dl>
          )}
        </section>
      )}

      {detail && (
        <>
          <section>
            <h2>모델 스코어보드</h2>
            <table>
              <thead>
                <tr>
                  <th>모델</th>
                  <th>Provider</th>
                  <th className="num">종합 품질</th>
                  <th className="num">Win rate</th>
                  <th className="num">평균 응답</th>
                  <th className="num">tokens/s</th>
                  <th className="num">비용 (전체)</th>
                </tr>
              </thead>
              <tbody>
                {detail.aggregates.map((a) => (
                  <tr key={`${a.provider}:${a.model_id}`}>
                    <td>
                      <span style={{ color: colorByModel[a.model_id], marginRight: 6 }}>●</span>
                      {a.model_id}
                    </td>
                    <td><code>{a.provider}</code></td>
                    <td className="num">{a.avg_quality?.toFixed(3) ?? '-'}</td>
                    <td className="num">{fmtPct(a.win_rate)} ({a.win_count}승)</td>
                    <td className="num">{fmtMs(a.avg_duration_ms)}</td>
                    <td className="num">{a.tokens_out_per_sec ?? '-'}</td>
                    <td className="num">{fmtCost(a.total_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {dimensionRows.length > 0 && (
            <section>
              <h2>평가 차원별 품질 (judge: {detail.run.judge_model || '-'})</h2>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={dimensionRows} margin={{ top: 8, right: 16, left: -16, bottom: 0 }} barGap={2}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="dimension" tick={{ fill: INK_MUTED, fontSize: 12 }} stroke={GRID} />
                  <YAxis domain={[0, 1]} tick={{ fill: INK_MUTED, fontSize: 12 }} stroke={GRID} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {detail.aggregates.map((a) => (
                    <Bar
                      key={a.model_id}
                      dataKey={a.model_id}
                      fill={colorByModel[a.model_id]}
                      radius={[4, 4, 0, 0]}
                      maxBarSize={36}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </section>
          )}

          {paretoPoints.length > 0 && (
            <section>
              <h2>품질 vs 응답 속도 (좌상단이 유리)</h2>
              <ResponsiveContainer width="100%" height={300}>
                <ScatterChart margin={{ top: 24, right: 40, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke={GRID} />
                  <XAxis
                    type="number" dataKey="duration_s" name="평균 응답(초)" unit="s"
                    tick={{ fill: INK_MUTED, fontSize: 12 }} stroke={GRID}
                  />
                  <YAxis
                    type="number" dataKey="quality" name="종합 품질" domain={[0, 1]}
                    tick={{ fill: INK_MUTED, fontSize: 12 }} stroke={GRID}
                  />
                  <ZAxis range={[120, 120]} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: '4 4', stroke: INK_MUTED }} />
                  {paretoPoints.map((p) => (
                    <Scatter key={p.model} name={p.model} data={[p]} fill={colorByModel[p.model]}>
                      <LabelList dataKey="model" position="top" style={{ fill: '#c3c2b7', fontSize: 11 }} />
                    </Scatter>
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
              <p className="muted small">
                점 = 모델별 평균. 무료 로컬 모델이 유료 API 품질에 근접할수록 교사후보(distillation teacher) 로 유리.
              </p>
            </section>
          )}
        </>
      )}

      {runs && runs.length > 0 && !detail && !error && <div className="loading">불러오는 중…</div>}
    </div>
  );
}
