import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Background, Handle, Position, ReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../api/client.js';

const COL_W = 280;
const ROW_H = 104;
const NODE_W = 224;

const STATUS_LABEL = { active: '운영', pending: '연동 대기', planned: '계획' };

function relTime(iso) {
  if (!iso) return null;
  const diffMs = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diffMs / 3_600_000);
  if (h < 1) return '1시간 내';
  if (h < 24) return `${h}시간 전`;
  return `${Math.floor(h / 24)}일 전`;
}

function FlowNode({ data }) {
  const n = data.node;
  const rate = n.stats && n.stats.runs_total > 0
    ? Math.round((n.stats.runs_success / n.stats.runs_total) * 100)
    : null;
  const body = (
    <div className={`flow-node flow-${n.status}`}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="flow-node-head">
        <span className="flow-node-label">{n.label}</span>
        <span className={`flow-badge flow-badge-${n.status}`}>{STATUS_LABEL[n.status]}</span>
      </div>
      <div className="flow-node-desc">{n.description}</div>
      {n.stats && (
        <div className="flow-node-stats">
          <span className={rate >= 90 ? 'ok-text' : rate >= 50 ? 'warn-text' : 'err-text'}>
            성공 {rate}%
          </span>
          <span> · {n.stats.runs_total}회</span>
          {n.stats.last_run_at && <span> · {relTime(n.stats.last_run_at)}</span>}
          {n.stats.avg_quality != null && <span> · 품질 {n.stats.avg_quality}</span>}
        </div>
      )}
      {!n.stats && n.consumer_id && (
        <div className="flow-node-stats muted">최근 30일 실행 없음</div>
      )}
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  );
  return n.href ? <Link to={n.href} className="flow-node-link">{body}</Link> : body;
}

const nodeTypes = { pipeline: FlowNode };

export default function PipelineFlow() {
  const [flow, setFlow] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get('/api/pipeline/flow')
      .then((r) => setFlow(r.data))
      .catch((e) => setError(e.response?.data?.detail || e.message));
  }, []);

  const { nodes, edges } = useMemo(() => {
    if (!flow) return { nodes: [], edges: [] };
    const byLayer = {};
    flow.nodes.forEach((n) => { (byLayer[n.layer] ||= []).push(n); });
    const maxRows = Math.max(...Object.values(byLayer).map((a) => a.length));
    const layerIdx = Object.fromEntries(flow.layers.map((l, i) => [l.id, i]));

    const nodes = flow.nodes.map((n) => {
      const col = layerIdx[n.layer];
      const rows = byLayer[n.layer];
      const row = rows.indexOf(n);
      const yOffset = ((maxRows - rows.length) * ROW_H) / 2;
      return {
        id: n.id,
        type: 'pipeline',
        position: { x: col * COL_W, y: row * ROW_H + yOffset + 36 },
        data: { node: n },
        draggable: false,
        style: { width: NODE_W },
      };
    });

    // 레이어 헤더 (수집 / LLM 처리 / 저장·산출 / 평가·자가진화)
    flow.layers.forEach((l, i) => {
      nodes.push({
        id: `layer-${l.id}`,
        type: 'default',
        position: { x: i * COL_W, y: -12 },
        data: { label: l.label },
        draggable: false,
        selectable: false,
        className: 'flow-layer-header',
        style: { width: NODE_W },
      });
    });

    const edges = flow.edges.map((e) => ({
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: e.kind === 'feedback',
      style: e.kind === 'feedback'
        ? { stroke: '#9085e9', strokeDasharray: '6 4' }
        : { stroke: '#3a4050' },
    }));

    return { nodes, edges };
  }, [flow]);

  if (error) return <pre className="error">{error}</pre>;
  if (!flow) return <div className="loading">파이프라인 불러오는 중…</div>;

  return (
    <div>
      <div style={{ height: 560, border: '1px solid #2a2e38', borderRadius: 6, background: '#14171d' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          minZoom={0.5}
          maxZoom={1.4}
          nodesConnectable={false}
          elementsSelectable={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#232732" gap={24} />
        </ReactFlow>
      </div>
      <div className="flow-legend muted small">
        <span><i className="dot dot-active" /> 운영 (batch-runs 연동)</span>
        <span><i className="dot dot-pending" /> 연동 대기 (계측 필요)</span>
        <span><i className="dot dot-planned" /> 계획</span>
        <span><i className="dash-feedback" /> 자가진화 피드백</span>
      </div>
    </div>
  );
}
