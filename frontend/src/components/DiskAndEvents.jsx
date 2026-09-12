import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { ago, formatBytes } from './modelFormat.js';

const EVENT_LABEL = {
  discovered: '신규 설치',
  removed: '제거됨',
  reappeared: '복귀',
  digest_changed: 'digest 변경',
  size_changed: '크기 변경',
};
const EVENT_CLASS = {
  discovered: 'lc-active',
  removed: 'lc-retire',
  reappeared: 'lc-eval',
  digest_changed: 'lc-idle',
  size_changed: 'lc-uninst',
};

function eventDetail(e) {
  const d = e.detail || {};
  if (e.kind === 'digest_changed') return `${String(d.before).slice(0, 10)}… → ${String(d.after).slice(0, 10)}…`;
  if (e.kind === 'size_changed') return `${formatBytes(d.before)} → ${formatBytes(d.after)}`;
  if (d.size_bytes != null) return formatBytes(d.size_bytes);
  return '-';
}

export default function DiskAndEvents() {
  const [disk, setDisk] = useState(null);
  const [events, setEvents] = useState(null);

  useEffect(() => {
    api.get('/api/monitor/disk', { params: { top: 8 } }).then((r) => setDisk(r.data)).catch(() => setDisk(null));
    api.get('/api/monitor/events', { params: { days: 90, limit: 30 } }).then((r) => setEvents(r.data)).catch(() => setEvents(null));
  }, []);

  return (
    <>
      <section>
        <h2>모델 파일 디스크 사용량</h2>
        {!disk && <p className="muted">불러오는 중…</p>}
        {disk && (
          <>
            <div className="kpi-row">
              <div className="kpi-card">
                <div className="kpi-label">설치된 모델 합계</div>
                <div className="kpi-value sm">{formatBytes(disk.total_installed_bytes)}</div>
                <div className="kpi-sub">Ollama blobs + HF 캐시</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-label">회수 가능</div>
                <div className="kpi-value sm">
                  <span className={disk.reclaimable_bytes > 0 ? 'warn-text' : 'ok-text'}>
                    {formatBytes(disk.reclaimable_bytes)}
                  </span>
                </div>
                <div className="kpi-sub">deprecated 인데 파일이 남아 있음</div>
              </div>
              {disk.providers.map((p) => (
                <div className="kpi-card" key={p.provider}>
                  <div className="kpi-label">{p.provider}</div>
                  <div className="kpi-value sm">{formatBytes(p.active_bytes)}</div>
                  <div className="kpi-sub">
                    활성 {p.active_count}
                    {p.deprecated_installed_count > 0 && ` · 회수 대상 ${p.deprecated_installed_count}`}
                  </div>
                </div>
              ))}
            </div>
            <div className="table-scroll" style={{ marginTop: 12 }}>
              <table>
                <thead>
                  <tr>
                    <th>모델</th>
                    <th>Provider</th>
                    <th className="num">크기</th>
                    <th>상태</th>
                    <th>마지막 확인</th>
                  </tr>
                </thead>
                <tbody>
                  {disk.top_models.map((m) => (
                    <tr key={`${m.provider}/${m.model_id}`} className={m.installed ? '' : 'row-deprecated'}>
                      <td><code>{m.model_id}</code></td>
                      <td className="small muted">{m.provider}</td>
                      <td className="num">{formatBytes(m.size_bytes)}</td>
                      <td>
                        {!m.installed && <span className="badge badge-muted">파일 없음</span>}
                        {m.installed && m.deprecated && <span className="badge lc-retire">회수 가능</span>}
                        {m.installed && !m.deprecated && <span className="badge lc-active">사용 중</span>}
                      </td>
                      <td className="small muted">{ago(m.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small" style={{ marginTop: 10 }}>
              모델 파일 용량만 집계한다. 디스크 전체 여유 공간·파티션은 InfraWatcher 참조. 삭제는 호스트에서 직접(`ollama rm`).
            </p>
          </>
        )}
      </section>

      <section>
        <h2>인벤토리 변경 이력 (최근 90일)</h2>
        {!events && <p className="muted">불러오는 중…</p>}
        {events && events.length === 0 && <p className="muted">변경 없음. 폴러가 diff 를 감지하면 여기에 쌓인다.</p>}
        {events && events.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>시각</th>
                  <th>변경</th>
                  <th>모델</th>
                  <th>Provider</th>
                  <th>상세</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td className="small muted">{ago(e.at)}</td>
                    <td><span className={`badge ${EVENT_CLASS[e.kind] || 'lc-idle'}`}>{EVENT_LABEL[e.kind] || e.kind}</span></td>
                    <td><code>{e.model_id}</code></td>
                    <td className="small muted">{e.provider}</td>
                    <td className="small muted">{eventDetail(e)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small" style={{ marginTop: 10 }}>
          제거된 모델은 삭제하지 않고 <code>deprecated_at</code> 마크만 한다 (과거 집계 보존). 다시 설치되면 자동 해제.
        </p>
      </section>
    </>
  );
}
