import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

function formatBytes(n) {
  if (n == null) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

function formatDate(s) {
  if (!s) return '-';
  return new Date(s).toLocaleString();
}

export default function ModelsPage() {
  const { user, logout } = useAuth();
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState(null);

  const load = () => {
    setError(null);
    api.get('/api/models')
      .then((r) => setModels(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
  };

  useEffect(() => { load(); }, []);

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

  return (
    <div className="app">
      <header className="row">
        <div>
          <h1><Link to="/">LLMOps</Link> · 모델 인벤토리</h1>
          <p className="subtitle">설치된 로컬 LLM 자동 수집 (Ollama + MLX)</p>
        </div>
        <div className="row-end">
          <span className="muted">{user.email} · <code>{user.role}</code></span>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      <section>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>모델 ({models?.length ?? '…'})</h2>
          <div className="row-end">
            <button onClick={refresh} disabled={refreshing}>
              {refreshing ? 'Refreshing…' : 'Refresh (수동 폴링)'}
            </button>
          </div>
        </div>

        {refreshResult && (
          <pre className="ok">
            Ollama: {refreshResult.ollama_upserted} 개 / MLX: {refreshResult.mlx_upserted} 개 갱신
          </pre>
        )}
        {error && <pre className="error">{error}</pre>}

        {models && (
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model ID</th>
                <th>Family</th>
                <th>Param</th>
                <th>Quant</th>
                <th>Size</th>
                <th>Modified</th>
                <th>First seen</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={`${m.provider}:${m.model_id}`}>
                  <td><code>{m.provider}</code></td>
                  <td>{m.model_id}</td>
                  <td>{m.family || '-'}</td>
                  <td>{m.parameter_size || '-'}</td>
                  <td>{m.quantization || '-'}</td>
                  <td className="num">{formatBytes(m.size_bytes)}</td>
                  <td className="muted small">{formatDate(m.source_modified_at)}</td>
                  <td className="muted small">{formatDate(m.first_seen_at)}</td>
                  <td className="muted small">{formatDate(m.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {models && models.length === 0 && (
          <p className="muted">아직 수집된 모델 없음. Refresh 클릭 또는 잠시 후 새로고침.</p>
        )}
      </section>
    </div>
  );
}
