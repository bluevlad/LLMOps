import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { ago } from './modelFormat.js';

const errorText = (e) => typeof e.response?.data?.detail === 'string'
  ? e.response.data.detail : '저장하지 못했습니다. 입력과 연결 상태를 확인해 주세요.';

export default function AlertActions({ alertId, isAdmin }) {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [form, setForm] = useState({ action_type: '', note: '', discovery_source: 'manual', outcome: 'pending', result_note: '', evidence_url: '' });
  const [cancel, setCancel] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    api.get(`/api/monitor/alerts/${alertId}/actions`, { signal: controller.signal })
      .then(({ data }) => { setRows(data); setHasMore(data.length === 100); setError(null); })
      .catch((e) => { if (!controller.signal.aborted) setError(errorText(e)); });
    return () => controller.abort();
  }, [alertId, open, revision]);

  const update = (key, value) => {
    setForm((f) => ({ ...f, [key]: value }));
    setRequestId(crypto.randomUUID());
  };
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post(`/api/monitor/alerts/${alertId}/actions`, {
        ...form, request_id: requestId,
        evidence_url: form.evidence_url || null, result_note: form.result_note || null,
      });
      setForm({ action_type: '', note: '', discovery_source: 'manual', outcome: 'pending', result_note: '', evidence_url: '' });
      setRequestId(crypto.randomUUID()); setRevision((n) => n + 1);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const cancelAction = async (event) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      await api.post(`/api/monitor/alerts/${alertId}/actions/${cancel.id}/cancel`, {
        request_id: cancel.requestId, note: cancel.note,
      });
      setCancel(null); setRevision((n) => n + 1);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const more = async () => {
    setBusy(true);
    try {
      const { data } = await api.get(`/api/monitor/alerts/${alertId}/actions`, { params: { before_id: rows.at(-1).id } });
      setRows((previous) => [...previous, ...data]); setHasMore(data.length === 100);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const cancelled = new Set(rows.filter((r) => r.event_type === 'cancel').map((r) => r.target_action_id));
  return <div className="alert-actions">
    <button className="link-btn" onClick={() => setOpen(!open)}>실제 조치 기록 {open ? '접기' : '열기'}</button>
    {open && <>
      <p className="muted small">외부에서 수행한 모델 조치를 기록합니다. 알림 확인은 조치 실적에 포함되지 않습니다. 결과를 정정할 때는 기존 기록을 취소하고 새 기록에 검증 결과를 남겨 주세요.</p>
      {error && <p role="alert" className="err-text">{error}</p>}
      {rows.map((r) => <div key={r.id} className="alert-note small">
        <strong>{r.event_type === 'cancel' ? `조치 #${r.target_action_id} 취소` : `#${r.id} ${r.action_type}`}</strong>
        {cancelled.has(r.id) && ' (취소됨)'} · {r.actor} · {ago(r.at)}
        <div>{r.note}</div>
        {r.event_type === 'action' && <>
          <div>발견: {{ alert: '알림', dashboard: '관제 화면', manual: '수동 확인' }[r.discovery_source]} · 결과: {{ pending: '검증 대기', improved: '개선 확인', no_change: '개선 없음' }[r.outcome]}</div>
          {r.result_note && <div>{r.result_note}</div>}
          {r.evidence_url && <a href={r.evidence_url} target="_blank" rel="noreferrer">근거 보기</a>}
          {isAdmin && !cancelled.has(r.id) && <button disabled={busy} className="link-btn" onClick={() => setCancel({ id: r.id, note: '', requestId: crypto.randomUUID() })}>취소 기록</button>}
        </>}
      </div>)}
      {hasMore && <button disabled={busy} onClick={more}>이전 기록 더 보기</button>}
      {isAdmin && cancel && <form onSubmit={cancelAction}>
        <label>조치 #{cancel.id} 취소 사유 <input required maxLength={4000} value={cancel.note} disabled={busy} onChange={(e) => setCancel({ ...cancel, note: e.target.value, requestId: crypto.randomUUID() })} /></label>
        <button disabled={busy || !cancel.note.trim()}>취소 사유 저장</button>
        <button type="button" disabled={busy} onClick={() => setCancel(null)}>닫기</button>
      </form>}
      {isAdmin && <form onSubmit={submit}>
        <fieldset disabled={busy} className="action-fields">
          <label>조치 종류 <input required maxLength={80} placeholder="예: 모델 교체, 설정 변경" value={form.action_type} onChange={(e) => update('action_type', e.target.value)} /></label>
          <label>실행 내용 <textarea required maxLength={4000} value={form.note} onChange={(e) => update('note', e.target.value)} /></label>
          <label>최초 발견 경로 <select value={form.discovery_source} onChange={(e) => update('discovery_source', e.target.value)}>
            <option value="manual">수동 확인</option><option value="alert">LLMOps 알림</option><option value="dashboard">LLMOps 관제 화면</option>
          </select></label>
          <label>검증 결과 <select value={form.outcome} onChange={(e) => update('outcome', e.target.value)}>
            <option value="pending">검증 대기</option><option value="improved">개선 확인</option><option value="no_change">개선 없음</option>
          </select></label>
          <label>검증 내용 <textarea required={form.outcome !== 'pending'} maxLength={4000} value={form.result_note} onChange={(e) => update('result_note', e.target.value)} /></label>
          <label>근거 링크 (선택) <input type="url" value={form.evidence_url} onChange={(e) => update('evidence_url', e.target.value)} /></label>
          <button disabled={!form.note.trim() || !form.action_type.trim()}>실제 조치 저장</button>
        </fieldset>
      </form>}
    </>}
  </div>;
}
