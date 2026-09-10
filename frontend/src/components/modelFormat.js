// 모델 모니터링 화면 공용 포맷터 (ModelsPage / ModelDetailPage)

export function formatBytes(n) {
  if (n == null) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

export function formatDate(s) {
  if (!s) return '-';
  return new Date(s).toLocaleString();
}

export function formatDateShort(s) {
  if (!s) return '-';
  const d = new Date(s);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function formatMs(ms) {
  if (ms == null) return '-';
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${ms}ms`;
}

export function fmtNum(n) {
  if (n == null) return '-';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function pct(part, total) {
  if (!total) return null;
  return Math.round((part / total) * 1000) / 10;
}

// 상대 시간 ("3h 전", "12d 전") — 마지막 호출·수명주기 배지용
export function ago(s) {
  if (!s) return '-';
  const diff = Date.now() - new Date(s).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return '방금';
  if (m < 60) return `${m}m 전`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h 전`;
  return `${Math.floor(h / 24)}d 전`;
}

// 수명주기 → 배지 클래스 (styles.css .lc-*)
export const LIFECYCLE_CLASS = {
  active: 'lc-active',
  'eval-only': 'lc-eval',
  idle: 'lc-idle',
  'retire-candidate': 'lc-retire',
  uninstrumented: 'lc-uninst',
  deprecated: 'lc-deprecated',
};

export const ANOMALY_LABEL = {
  unregistered_model: '미등록 모델명',
  missing_model: 'model 누락',
  deprecated_model_called: 'deprecated 호출',
  tokens_unreported: '토큰 미보고',
  ok_unreported: 'ok 미보고',
  stage_failed: 'stage 실패',
};

// 상세 페이지 경로 — model_id 에 ':' '/' 가 있어 provider 세그먼트 + splat 로 받는다
export function detailPath(m) {
  return `/models/${encodeURIComponent(m.provider)}/${m.model_id.split('/').map(encodeURIComponent).join('/')}`;
}
