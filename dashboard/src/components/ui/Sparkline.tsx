/** A small trend line for stat tiles. Gaps in the data stay gaps. */
export function Sparkline({ values, color, label }: { values: (number | null)[]; color: string; label: string }) {
  const valid = values.filter((v): v is number => v !== null);
  if (valid.length < 2) return <div className="h-9" />;

  const W = 120;
  const H = 36;
  const lo = Math.min(...valid);
  const hi = Math.max(...valid);
  const span = hi - lo || 1;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => H - 3 - ((v - lo) / span) * (H - 6);

  let line = "";
  let pen = false;
  values.forEach((v, i) => {
    if (v === null) {
      pen = false;
      return;
    }
    line += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  const first = values.findIndex((v) => v !== null);
  const last = values.length - 1 - [...values].reverse().findIndex((v) => v !== null);
  const area = `${line}L${x(last).toFixed(1)},${H}L${x(first).toFixed(1)},${H}Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-9 w-full" role="img" aria-label={label}>
      <path d={area} fill={color} opacity="0.1" />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
