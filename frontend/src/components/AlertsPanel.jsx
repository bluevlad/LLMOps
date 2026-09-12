import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { ago, formatBytes } from './modelFormat.js';

const SEVERITY_CLASS = { critical: 'lc-retire', warning: 'lc-idle', info: 'lc-eval' };
const SEVERITY_ICON = { critical: '🔴', warning: '🟡', info: '🔵' };
const KIND_LABEL = {
  ollama_unreachable: 'Ollama 도달 불가',
  expected_resident_missing: '상주 이탈',
  retire_candidate: '퇴출 후보',
  failure_spike: '실패율 급증',
  contract_anomaly: '보고 계약 위반',
};

function AckForm({ alert, onDone }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (undo) => {
    setBusy(true);
    try {
      await api.post(`/api/monitor/alerts/${alert.id}/ack`, { action_note: note || null, undo });
      onDone();
    } finally {
      setBusy(false);
    }
  };

  if (alert.acknowledged_at) {
    return (
      <div className="small muted">
        ✔ {alert.acknowledged_by} · {ago(alert.acknowledged_at)}
        {alert.action_note && <div className="alert-note">{alert.action_note}</div>}
        <button className="link-btn" disabled={busy} onClick={() => submit(true)}>조치 취소</button>
      </div>
    );
  }
  return (
    <div className="alert-ack">
      <input
        className="ack-input"
        placeholder="조치 내용 (예: ollama rm old:26b)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <button disabled={busy} onClick={() => submit(false)}>조치 기록</button>
    </div>
  );
}

export default function AlertsPanel({ isAdmin }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showResolved, setShowResolved] = useState(false);
  const [evaluating, setEvaluating] = useState(false);

  const load = useCallback(() => {
    api.get('/api/monitor/alerts', { params: { status: showResolved ? 'all' : 'open', days: 30 } })
      .then((r) => { setData(r.data); setError(null); })
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, [showResolved]);

  useEffect(() => { load(); }, [load]);

  const evaluate = async () => {
    setEvaluating(true);
    try {
      await api.post('/api/monitor/alerts/evaluate');
      load();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setEvaluating(false);
    }
  };

  const sev = data?.by_severity || {};
  const alerts = useMemo(() => data?.alerts || [], [data]);

  return (
    <section>
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>
          관제 알림
          {data && data.open_count > 0 && (
            <span className={`badge ${sev.critical ? 'lc-retire' : 'lc-idle'}`} style={{ marginLeft: 8 }}>
              열림 {data.open_count}
            </span>
          )}
        </h2>
        <div className="row-end small">
          <label>
            <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />{' '}
            해결된 알림 포함
          </label>
          {isAdmin && <button disabled={evaluating} onClick={evaluate}>{evaluating ? '평가 중…' : '지금 평가'}</button>}
        </div>
      </div>

      {error && <pre className="error">{error}</pre>}
      {!data && !error && <p className="muted">불러오는 중…</p>}

      {data && (
        <p className="muted small" style={{ marginBottom: 10 }}>
          마지막 평가 {data.last_evaluated_at ? ago(data.last_evaluated_at) : '없음 (스케줄러 기동 후 1회)'}
          {data.last_result && ` · 신호 ${data.last_result.signals} · 신규 ${data.last_result.opened} · 해결 ${data.last_result.resolved}`}
          {data.unacknowledged_count > 0 && ` · 미조치 ${data.unacknowledged_count}`}
        </p>
      )}

      {data && alerts.length === 0 && <p className="ok-text">열린 알림 없음.</p>}

      {alerts.map((a) => (
        <div key={a.id} className={`alert-card ${a.resolved_at ? 'alert-resolved' : ''}`}>
          <div className="alert-head">
            <span>{SEVERITY_ICON[a.severity] || '⚪'}</span>
            <span className={`badge ${SEVERITY_CLASS[a.severity] || 'lc-idle'}`}>{KIND_LABEL[a.kind] || a.kind}</span>
            <span className="alert-title">{a.title}</span>
            {a.resolved_at && <span className="badge badge-live">해결됨 {ago(a.resolved_at)}</span>}
          </div>
          <div className="alert-msg">{a.message}</div>
          <div className="alert-meta muted small">
            최초 {ago(a.first_seen_at)} · 최근 {ago(a.last_seen_at)}
            {a.notified_at && ' · Slack 발송됨'}
            {a.detail?.size_bytes ? ` · ${formatBytes(a.detail.size_bytes)}` : ''}
          </div>
          {isAdmin && !a.resolved_at && <AckForm alert={a} onDone={load} />}
          {a.resolved_at && a.action_note && <div className="alert-note small muted">✔ {a.action_note}</div>}
        </div>
      ))}
    </section>
  );
}
