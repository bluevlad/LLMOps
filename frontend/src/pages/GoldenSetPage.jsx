import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

const STATUS_TABS = [
  { key: 'candidate', label: '후보' },
  { key: 'approved', label: '승인' },
  { key: 'rejected', label: '반려' },
];

function fmtDt(s) {
  return s ? new Date(s).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' }) : '-';
}

function ContentBlock({ label, text }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="kpi-label">{label}</div>
      <pre style={{
        whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12,
        background: '#0a0c10', border: '1px solid #2a2e38', borderRadius: 4,
        padding: 10, maxHeight: 240, overflowY: 'auto', margin: '4px 0 0',
      }}
      >
        {text || '(없음)'}
      </pre>
    </div>
  );
}

function ItemRow({ item, onCurate }) {
  const [open, setOpen] = useState(false);
  const [gold, setGold] = useState(item.gold_response || '');
  const [note, setNote] = useState(item.note || '');
  const [busy, setBusy] = useState(false);

  const curate = async (patch) => {
    setBusy(true);
    try {
      await onCurate(item.id, patch);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <tr style={{ cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        <td className="num">{item.id}</td>
        <td><code>{item.consumer_id}</code></td>
        <td><code>{item.model || '-'}</code></td>
        <td>{item.gold_response ? '편집됨' : '초안 채택'}</td>
        <td>{item.curated_by || '-'}</td>
        <td>{fmtDt(item.updated_at)}</td>
        <td>{open ? '▾' : '▸'}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} style={{ background: '#0d0f14' }}>
            <ContentBlock label="Prompt" text={item.prompt} />
            <ContentBlock label="Response (초안 — 항상 보존)" text={item.response} />
            <div className="kpi-label">Gold Response (비우면 초안을 골든으로 채택)</div>
            <textarea
              value={gold}
              onChange={(e) => setGold(e.target.value)}
              rows={5}
              style={{
                width: '100%', fontSize: 12, background: '#0a0c10', color: '#e6e6e6',
                border: '1px solid #2a2e38', borderRadius: 4, padding: 8, margin: '4px 0 8px',
              }}
            />
            <div className="kpi-label">Note</div>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              style={{
                width: '100%', fontSize: 12, background: '#0a0c10', color: '#e6e6e6',
                border: '1px solid #2a2e38', borderRadius: 4, padding: 8, margin: '4px 0 10px',
              }}
            />
            <div className="row-end" style={{ gap: 8 }}>
              <button disabled={busy} onClick={() => curate({ gold_response: gold, note })}>
                저장
              </button>
              {item.status !== 'approved' && (
                <button disabled={busy} onClick={() => curate({ status: 'approved', gold_response: gold, note })}>
                  승인
                </button>
              )}
              {item.status !== 'rejected' && (
                <button disabled={busy} onClick={() => curate({ status: 'rejected', note })}>
                  반려
                </button>
              )}
              {item.status !== 'candidate' && (
                <button disabled={busy} onClick={() => curate({ status: 'candidate' })}>
                  후보로 되돌림
                </button>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function GoldenSetPage() {
  const { user, logout } = useAuth();
  const [summary, setSummary] = useState(null);
  const [tab, setTab] = useState('candidate');
  const [list, setList] = useState(null);
  const [promotable, setPromotable] = useState(null);
  const [error, setError] = useState(null);

  const loadSummary = useCallback(() => {
    api.get('/api/golden-set/summary')
      .then((r) => setSummary(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, []);

  const loadList = useCallback(() => {
    setList(null);
    api.get('/api/golden-set', { params: { status: tab, limit: 100 } })
      .then((r) => setList(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, [tab]);

  const loadPromotable = useCallback(() => {
    api.get('/api/golden-set/promotable', { params: { limit: 50 } })
      .then((r) => setPromotable(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, []);

  useEffect(() => { loadSummary(); loadPromotable(); }, [loadSummary, loadPromotable]);
  useEffect(() => { loadList(); }, [loadList]);

  const refreshAll = () => { loadSummary(); loadList(); loadPromotable(); };

  const promote = async (stageId) => {
    try {
      await api.post('/api/golden-set/promote', { stage_id: stageId });
      refreshAll();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const curate = async (id, patch) => {
    try {
      await api.patch(`/api/golden-set/${id}`, patch);
      refreshAll();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const exportJsonl = async () => {
    try {
      const r = await api.get('/api/golden-set/export', {
        params: { status: 'approved' }, responseType: 'blob',
      });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'golden_set_approved.jsonl';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1><Link to="/">LLMOps</Link> · 골든셋 큐레이션</h1>
          <p className="subtitle">
            batch_run content 샘플 → 승격 → 검수 → SFT export (파인튜닝은 model-tuner 담당)
          </p>
        </div>
        <div className="row-end">
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      {error && (
        <section>
          <pre className="error" onClick={() => setError(null)}>{String(error)} (클릭하여 닫기)</pre>
        </section>
      )}

      <section>
        <div className="kpi-row">
          <div className="kpi-card">
            <div className="kpi-label">후보</div>
            <div className="kpi-value">{summary ? summary.by_status.candidate : '—'}</div>
            <div className="kpi-sub">검수 대기</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">승인 (골든)</div>
            <div className="kpi-value">{summary ? summary.by_status.approved : '—'}</div>
            <div className="kpi-sub">
              <a onClick={exportJsonl} style={{ cursor: 'pointer' }}>JSONL export ↓</a>
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">반려</div>
            <div className="kpi-value">{summary ? summary.by_status.rejected : '—'}</div>
            <div className="kpi-sub">부정 라벨 (선호쌍 후보)</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">승격 가능 stage</div>
            <div className="kpi-value">{summary ? summary.promotable_stages : '—'}</div>
            <div className="kpi-sub">content 샘플 보유 · 미승격</div>
          </div>
        </div>
      </section>

      <section>
        <h2>승격 후보 (최근 30일 content 샘플)</h2>
        {!promotable && <div className="loading">불러오는 중…</div>}
        {promotable && promotable.length === 0 && (
          <p className="muted">승격 가능한 stage 없음 — consumer 의 content 샘플 보고가 쌓이면 나타납니다.</p>
        )}
        {promotable && promotable.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Stage</th><th>Consumer</th><th>Model</th><th className="num">quality</th>
                <th>Response 미리보기</th><th>실행 시각</th><th></th>
              </tr>
            </thead>
            <tbody>
              {promotable.map((s) => (
                <tr key={s.stage_id}>
                  <td className="num">{s.stage_id}</td>
                  <td><code>{s.consumer_id}</code></td>
                  <td><code>{s.model || '-'}</code></td>
                  <td className="num">{s.quality_score != null ? s.quality_score.toFixed(2) : '-'}</td>
                  <td className="muted" style={{ maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.response_preview}
                  </td>
                  <td>{fmtDt(s.run_started_at)}</td>
                  <td><button onClick={() => promote(s.stage_id)}>승격</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>골든셋 항목</h2>
          <div className="row-end" style={{ gap: 6 }}>
            {STATUS_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                style={tab === t.key ? {} : { background: '#14171d' }}
              >
                {t.label}{summary ? ` ${summary.by_status[t.key]}` : ''}
              </button>
            ))}
          </div>
        </div>
        {!list && <div className="loading">불러오는 중…</div>}
        {list && list.items.length === 0 && <p className="muted">항목 없음.</p>}
        {list && list.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th className="num">ID</th><th>Consumer</th><th>Model</th>
                <th>골든 상태</th><th>검수자</th><th>갱신</th><th></th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((it) => (
                <ItemRow key={it.id} item={it} onCurate={curate} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
