// 목록 행용 미니 막대 스파크라인 (의존성 없음, inline SVG)
export default function Sparkline({ values, width = 84, height = 18, color = '#3987e5' }) {
  if (!values || values.length === 0) return null;
  const max = Math.max(...values, 1);
  const n = values.length;
  const gap = 1;
  const bw = Math.max(1, (width - gap * (n - 1)) / n);
  const total = values.reduce((a, b) => a + b, 0);
  return (
    <svg
      width={width}
      height={height}
      className="sparkline"
      role="img"
      aria-label={`최근 ${n}일 호출 ${total}건`}
    >
      <title>{`최근 ${n}일: ${values.join(', ')}`}</title>
      {values.map((v, i) => {
        const h = v === 0 ? 1 : Math.max(2, Math.round((v / max) * height));
        return (
          <rect
            key={i}
            x={i * (bw + gap)}
            y={height - h}
            width={bw}
            height={h}
            fill={v === 0 ? '#2a2e38' : color}
            rx={1}
          />
        );
      })}
    </svg>
  );
}
